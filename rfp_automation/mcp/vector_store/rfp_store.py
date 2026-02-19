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

    def query_all(
        self,
        rfp_id: str,
        top_k: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Retrieve all chunks for an RFP namespace (broad retrieval).
        Uses a generic query to pull as many chunks as possible.
        Results are sorted by chunk_index for document order.
        """
        index = self._get_index()
        # Use a generic query to get broad coverage of the namespace
        query_embedding = self._embedder.embed_single("document contents overview")

        results = index.query(
            vector=query_embedding,
            top_k=top_k,
            namespace=rfp_id,
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

        # Sort by chunk_index to preserve document order
        chunks.sort(key=lambda c: c.get("chunk_index", -1))
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
