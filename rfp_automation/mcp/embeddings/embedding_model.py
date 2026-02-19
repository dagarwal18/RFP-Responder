"""
Embedding Model — generates vector embeddings for text.
Uses Sentence Transformers (all-MiniLM-L6-v2 by default, 384 dimensions).
"""

from __future__ import annotations

import logging

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """Generate embeddings for text chunks. Singleton-friendly."""

    def __init__(self):
        self.settings = get_settings()
        self._model = None
        self._dimension: int | None = None

    def _load_model(self):
        """Lazy-load the embedding model on first use."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.settings.embedding_model)
            self._dimension = self._model.get_sentence_embedding_dimension()
            logger.info(
                f"Loaded embedding model: {self.settings.embedding_model} "
                f"(dim={self._dimension})"
            )

    @property
    def dimension(self) -> int:
        """Return the embedding vector dimension (e.g. 384 for all-MiniLM-L6-v2)."""
        self._load_model()
        return self._dimension  # type: ignore[return-value]

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        self._load_model()
        embeddings = self._model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()

    def embed_single(self, text: str) -> list[float]:
        """Embed a single text string."""
        return self.embed([text])[0]
