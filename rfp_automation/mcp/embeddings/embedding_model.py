"""
Embedding Model — generates vector embeddings for text.
Uses Sentence Transformers in real mode, random vectors in mock mode.
"""

from __future__ import annotations

import logging
import random

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """Generate embeddings for text chunks."""

    def __init__(self):
        self.settings = get_settings()
        self.mock_mode = self.settings.mock_mode
        self._model = None

    def _load_model(self):
        """Lazy-load the embedding model."""
        if self._model is None and not self.mock_mode:
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self.settings.embedding_model)
                logger.info(f"Loaded embedding model: {self.settings.embedding_model}")
            except ImportError:
                logger.error("sentence-transformers not installed")
                raise

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for a list of texts.
        Returns list of float vectors.
        """
        if self.mock_mode:
            dim = 384  # MiniLM dimension
            return [[random.random() for _ in range(dim)] for _ in texts]

        self._load_model()
        embeddings = self._model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()

    def embed_single(self, text: str) -> list[float]:
        """Embed a single text."""
        return self.embed([text])[0]
