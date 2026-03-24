"""
Embedding Model — generates vector embeddings for text.
Uses HuggingFace Inference API with BAAI/bge-m3 and dynamic key rotation.
"""

from __future__ import annotations

import logging
import time
import random
import threading
from huggingface_hub import InferenceClient

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """Generate embeddings for text chunks via HuggingFace InferenceClient."""

    _cache: dict[str, list[float]] = {}
    _cache_lock = threading.Lock()
    _max_cache_entries = 4096

    def __init__(self):
        self.settings = get_settings()
        self._dimension = 1024
        
        # Load all available keys
        self.keys = []
        if getattr(self.settings, "huggingface_api_keys", None):
            self.keys = [k.strip() for k in self.settings.huggingface_api_keys.split(",") if k.strip()]
        if not self.keys and getattr(self.settings, "huggingface_api_key", None):
            self.keys = [self.settings.huggingface_api_key]
            
        if not self.keys:
            raise ValueError("HUGGINGFACE_API_KEY (or keys) is not set — required for embedding.")
            
        self._current_key_idx = random.randint(0, len(self.keys) - 1)
        self._client = self._create_client()

    def _create_client(self) -> InferenceClient:
        """Create a new InferenceClient using the currently selected key."""
        selected_key = self.keys[self._current_key_idx]
        return InferenceClient(
            provider="hf-inference",
            api_key=selected_key,
        )

    def _rotate_key(self, verbose: bool = True):
        """Rotate to the next API key in the list."""
        if len(self.keys) > 1:
            self._current_key_idx = (self._current_key_idx + 1) % len(self.keys)
            self._client = self._create_client()
            if verbose:
                logger.info(f"[Embedding-API] Rotated to HuggingFace API key index {self._current_key_idx + 1}/{len(self.keys)}")

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        if not texts:
            return []

        all_embeddings: list[list[float] | None] = [None] * len(texts)
        uncached_positions: dict[str, list[int]] = {}

        with self._cache_lock:
            for idx, text in enumerate(texts):
                cached = self._cache.get(text)
                if cached is not None:
                    all_embeddings[idx] = cached
                else:
                    uncached_positions.setdefault(text, []).append(idx)

        uncached_texts = list(uncached_positions.keys())
        if not uncached_texts:
            return [emb for emb in all_embeddings if emb is not None]

        batch_size = 16
        # Max retries extended to cover the number of keys we have + a few standard retries
        max_retries = max(5, len(self.keys) + 2)
        
        for i in range(0, len(uncached_texts), batch_size):
            batch = uncached_texts[i:i + batch_size]
            
            # Rotate key on every batch using round-robin to avoid rate limits
            self._rotate_key(verbose=False)
            
            for attempt in range(max_retries):
                try:
                    t0 = time.perf_counter()
                    result = self._client.feature_extraction(
                        text=batch,
                        model=self.settings.embedding_model,
                    )
                    
                    # Convert numpy arrays to standard lists
                    emb_batch = result.tolist()
                    
                    if len(emb_batch) > 0 and isinstance(emb_batch[0], list) and isinstance(emb_batch[0][0], list):
                        emb_batch = [seq[0] for seq in emb_batch]

                    with self._cache_lock:
                        for text, emb in zip(batch, emb_batch):
                            self._cache[text] = emb
                            while len(self._cache) > self._max_cache_entries:
                                self._cache.pop(next(iter(self._cache)))
                            for pos in uncached_positions.get(text, []):
                                all_embeddings[pos] = emb

                    logger.info(f"[Embedding] Batch size {len(batch)} embedded in {time.perf_counter() - t0:.2f}s")
                    break  # Success, exit retry loop
                    
                except Exception as e:
                    # If we hit a 504 Timeout or 429 Too Many Requests, instantly rotate the key
                    error_msg = str(e).lower()
                    if "504" in error_msg or "429" in error_msg or "timeout" in error_msg:
                        logger.warning(f"[Embedding] Throttled/Timeout ({e}). Rotating API key...")
                        self._rotate_key()
                        
                        # Only sleep briefly before trying the new key
                        time.sleep(1.0)
                        continue
                        
                    if attempt < max_retries - 1:
                        delay = 2 ** attempt
                        logger.warning(f"[Embedding] Batch failed: {e}. Retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(delay)
                    else:
                        logger.error(f"[Embedding] Failed to embed batch after {max_retries} attempts: {e}")
                        raise

        return [emb for emb in all_embeddings if emb is not None]

    def embed_single(self, text: str) -> list[float]:
        return self.embed([text])[0]

    # Alias for backward compatibility
    embed_batch = embed
