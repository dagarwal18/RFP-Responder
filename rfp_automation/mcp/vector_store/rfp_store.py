"""
RFP Vector Store — stores chunked + embedded incoming RFP documents.
Agents query this to retrieve RFP context instead of reading raw files.

Internally uses embeddings/ for the real implementation;
those details are hidden from agents.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RFPVectorStore:
    """Interface to the RFP vector store inside the MCP server."""

    def __init__(self, mock_mode: bool = True):
        self.mock_mode = mock_mode

        if not self.mock_mode:
            from rfp_automation.mcp.embeddings.embedding_model import EmbeddingModel
            from rfp_automation.services.parsing_service import TextChunker

            self._embedding = EmbeddingModel()
            self._chunker = TextChunker()
            # TODO: wire VectorDBClient

    def embed_document(self, rfp_id: str, text: str, metadata: dict[str, Any] | None = None) -> bool:
        """Chunk a raw text, embed it, and store in the vector DB."""
        if self.mock_mode:
            logger.info(f"[MOCK] Embedded document for {rfp_id}")
            return True

        chunks = self._chunker.chunk(text)
        texts = [c["text"] for c in chunks]
        vectors = self._embedding.embed(texts)
        # TODO: upsert into vector DB
        logger.info(f"Embedded {len(chunks)} chunks for {rfp_id}")
        return True

    def query(self, query_text: str, rfp_id: str = "", top_k: int = 5) -> list[dict[str, Any]]:
        """Retrieve relevant chunks from the RFP store."""
        if self.mock_mode:
            return [
                {
                    "chunk_id": f"chunk_{i}",
                    "text": f"Mock RFP chunk {i} relevant to: {query_text[:50]}",
                    "score": round(0.95 - i * 0.05, 2),
                    "metadata": {"rfp_id": rfp_id, "page": i + 1},
                }
                for i in range(min(top_k, 3))
            ]
        raise NotImplementedError

    def delete_document(self, rfp_id: str) -> bool:
        """Remove all embeddings for an RFP."""
        if self.mock_mode:
            logger.info(f"[MOCK] Deleted embeddings for {rfp_id}")
            return True
        raise NotImplementedError
