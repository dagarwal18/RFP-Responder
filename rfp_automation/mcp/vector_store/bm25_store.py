"""
BM25 Store — lightweight in-memory BM25 index per RFP namespace.

Used alongside Pinecone (dense) for hybrid retrieval via
Reciprocal Rank Fusion (RRF).

Provides sparse keyword matching that catches lexical matches
that embedding-based search misses (e.g., "ISO 27001").
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class BM25Store:
    """
    In-memory BM25 index per RFP namespace.

    Each RFP gets its own BM25 index built from chunk texts.
    Indices are rebuilt on each call to index() — no persistence.
    """

    def __init__(self):
        self._indices: dict[str, Any] = {}   # rfp_id → BM25Okapi instance
        self._chunks: dict[str, list[dict[str, Any]]] = {}  # rfp_id → chunk list

    def index(self, rfp_id: str, chunks: list[dict[str, Any]]) -> None:
        """
        Build (or replace) a BM25 index from chunk texts.

        Each chunk must have a "text" field.
        """
        from rank_bm25 import BM25Okapi

        if not chunks:
            logger.warning(f"[BM25] No chunks to index for {rfp_id}")
            return

        tokenized_corpus = [
            self._tokenize(chunk.get("text", "")) for chunk in chunks
        ]

        self._indices[rfp_id] = BM25Okapi(tokenized_corpus)
        self._chunks[rfp_id] = list(chunks)  # shallow copy

        logger.info(
            f"[BM25] Indexed {len(chunks)} chunks for rfp_id={rfp_id}"
        )

    def query(
        self,
        rfp_id: str,
        query: str,
        top_k: int = 20,
    ) -> list[dict[str, Any]]:
        """
        BM25 keyword search over an RFP's chunks.

        Returns ranked list of chunk dicts with added "bm25_score" field.
        Only returns chunks with score > 0.
        """
        if rfp_id not in self._indices:
            logger.debug(f"[BM25] No index for rfp_id={rfp_id}")
            return []

        bm25 = self._indices[rfp_id]
        chunks = self._chunks[rfp_id]
        tokenized_query = self._tokenize(query)

        scores = bm25.get_scores(tokenized_query)

        # Get top-k indices sorted by score descending
        ranked_indices = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True,
        )[:top_k]

        results: list[dict[str, Any]] = []
        for idx in ranked_indices:
            score = float(scores[idx])
            if score > 0:
                chunk = {**chunks[idx], "bm25_score": score}
                results.append(chunk)

        logger.debug(
            f"[BM25] Query '{query[:50]}' on {rfp_id}: "
            f"{len(results)} results (top_k={top_k})"
        )
        return results

    def has_index(self, rfp_id: str) -> bool:
        """Check if an RFP has a BM25 index."""
        return rfp_id in self._indices

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """
        Simple whitespace tokenizer with lowercasing.

        Strips punctuation from token edges for better matching.
        """
        import re
        # Lowercase, split on whitespace, strip trailing punctuation
        tokens = text.lower().split()
        return [re.sub(r"^[^\w]+|[^\w]+$", "", t) for t in tokens if t.strip()]
