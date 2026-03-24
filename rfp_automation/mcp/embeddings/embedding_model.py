"""
Embedding Model — generates vector embeddings for text.
Uses HuggingFace Inference API with BAAI/bge-m3 and dynamic key rotation.
"""

from __future__ import annotations

import logging
import time
import random
from huggingface_hub import InferenceClient

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """Generate embeddings for text chunks via HuggingFace InferenceClient."""

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

    def _rotate_key(self):
        """Rotate to the next API key in the list."""
        if len(self.keys) > 1:
            self._current_key_idx = (self._current_key_idx + 1) % len(self.keys)
            self._client = self._create_client()
            logger.info(f"[Embedding-API] Rotated to HuggingFace API key index {self._current_key_idx + 1}/{len(self.keys)}")

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        if not texts:
            return []
            
        all_embeddings = []
        batch_size = 2
        # Max retries extended to cover the number of keys we have + a few standard retries
        max_retries = max(5, len(self.keys) + 2)
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            
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
                        
                    all_embeddings.extend(emb_batch)
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

        return all_embeddings

    def embed_single(self, text: str) -> list[float]:
        return self.embed([text])[0]

    # Alias for backward compatibility
    embed_batch = embed
