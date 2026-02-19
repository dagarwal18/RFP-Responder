"""
RFP Vector Store — stores chunked + embedded incoming RFP documents in Pinecone.

Each RFP gets its own Pinecone namespace (rfp_id as namespace).
Agents query this store to retrieve relevant RFP context.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from rfp_automation.config import get_settings
from rfp_automation.mcp.embeddings.embedding_model import EmbeddingModel
from rfp_automation.services.parsing_service import ParsingService

logger = logging.getLogger(__name__)


class RFPVectorStore:
    """
    Pinecone-backed vector store for incoming RFP documents.
    Uses namespaces to isolate each RFP's vectors.
    """

    def __init__(self):
        self.settings = get_settings()
        self._embedder = EmbeddingModel()
        self._index = None

    def _get_index(self):
        """Lazy-init: connect to (or create) the Pinecone index."""
        if self._index is not None:
            return self._index

        from pinecone import Pinecone, ServerlessSpec

        pc = Pinecone(api_key=self.settings.pinecone_api_key)
        index_name = self.settings.pinecone_index_name

        # Create the index if it doesn't exist
        existing = [idx.name for idx in pc.list_indexes()]
        if index_name not in existing:
            logger.info(f"Creating Pinecone index: {index_name}")
            pc.create_index(
                name=index_name,
                dimension=self._embedder.dimension,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud=self.settings.pinecone_cloud,
                    region=self.settings.pinecone_region,
                ),
            )

        self._index = pc.Index(index_name)
        logger.info(f"Connected to Pinecone index: {index_name}")
        return self._index

    def embed_document(
        self,
        rfp_id: str,
        raw_text: str,
        metadata: dict[str, Any] | None = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> int:
        """
        Chunk raw text, embed, and upsert into Pinecone.
        Returns the number of chunks stored.
        """
        index = self._get_index()
        chunks = ParsingService.chunk_text(raw_text, chunk_size, chunk_overlap)

        if not chunks:
            logger.warning(f"[{rfp_id}] No chunks produced from text")
            return 0

        # Generate embeddings for all chunks
        embeddings = self._embedder.embed(chunks)

        # Build upsert vectors
        vectors = []
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            vec_id = f"{rfp_id}_chunk_{i:04d}"
            vec_metadata = {
                "rfp_id": rfp_id,
                "chunk_index": i,
                "text": chunk[:1000],  # Pinecone metadata limit
                **(metadata or {}),
            }
            vectors.append((vec_id, emb, vec_metadata))

        # Upsert in batches (Pinecone limit is 100 per request)
        batch_size = 100
        for batch_start in range(0, len(vectors), batch_size):
            batch = vectors[batch_start : batch_start + batch_size]
            index.upsert(vectors=batch, namespace=rfp_id)

        logger.info(f"[{rfp_id}] Embedded {len(chunks)} chunks into Pinecone")
        return len(chunks)

    def embed_chunks(
        self,
        rfp_id: str,
        chunks: list[dict[str, Any]],
        extra_metadata: dict[str, Any] | None = None,
    ) -> int:
        """
        Embed pre-structured chunks and upsert into Pinecone.

        Each chunk dict must have: chunk_id, content_type, section_hint,
        text, page_start, page_end  (from ParsingService.prepare_chunks).

        Returns the number of vectors stored.
        """
        index = self._get_index()

        # Filter out table_mock chunks (placeholder text, not useful for semantic search)
        embeddable = [c for c in chunks if c.get("content_type") != "table_mock"]
        if not embeddable:
            logger.warning(f"[{rfp_id}] No embeddable chunks after filtering")
            return 0

        # Extract text for batch embedding
        texts = [c["text"] for c in embeddable]
        embeddings = self._embedder.embed(texts)

        # Build upsert vectors with structured metadata
        vectors = []
        for i, (chunk, emb) in enumerate(zip(embeddable, embeddings)):
            vec_id = f"{rfp_id}_chunk_{i:04d}"
            vec_metadata = {
                "rfp_id": rfp_id,
                "chunk_index": i,
                "chunk_id": chunk.get("chunk_id", ""),
                "content_type": chunk.get("content_type", "text"),
                "section_hint": chunk.get("section_hint", ""),
                "page_start": chunk.get("page_start", 0),
                "page_end": chunk.get("page_end", 0),
                "text": chunk["text"][:1000],  # Pinecone metadata limit
                **(extra_metadata or {}),
            }
            vectors.append((vec_id, emb, vec_metadata))

        # Upsert in batches (Pinecone limit is 100 per request)
        batch_size = 100
        for batch_start in range(0, len(vectors), batch_size):
            batch = vectors[batch_start : batch_start + batch_size]
            index.upsert(vectors=batch, namespace=rfp_id)

        logger.info(
            f"[{rfp_id}] Embedded {len(vectors)} structured chunks into Pinecone "
            f"(skipped {len(chunks) - len(embeddable)} table_mock)"
        )
        return len(vectors)

    def query(
        self,
        query_text: str,
        rfp_id: str = "",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Embed the query and search Pinecone for matching chunks.
        Returns list of {text, score, chunk_index, metadata}.
        """
        index = self._get_index()
        query_embedding = self._embedder.embed_single(query_text)

        results = index.query(
            vector=query_embedding,
            top_k=top_k,
            namespace=rfp_id if rfp_id else None,
            include_metadata=True,
        )

        chunks = []
        for match in results.get("matches", []):
            chunks.append({
                "id": match["id"],
                "score": match["score"],
                "text": match.get("metadata", {}).get("text", ""),
                "chunk_index": match.get("metadata", {}).get("chunk_index", -1),
                "metadata": match.get("metadata", {}),
            })
        return chunks

    def delete_document(self, rfp_id: str) -> bool:
        """Delete all vectors for an RFP by deleting its namespace."""
        index = self._get_index()
        try:
            index.delete(delete_all=True, namespace=rfp_id)
            logger.info(f"[{rfp_id}] Deleted all vectors from Pinecone")
            return True
        except Exception as e:
            logger.error(f"[{rfp_id}] Failed to delete: {e}")
            return False
