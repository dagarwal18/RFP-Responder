"""
Embedding Model — generates vector embeddings for text.
Uses HuggingFace Inference API with BAAI/bge-m3.
"""

from __future__ import annotations

import logging
import time
from huggingface_hub import InferenceClient

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """Generate embeddings for text chunks via HuggingFace InferenceClient."""

    def __init__(self):
        self.settings = get_settings()
        # BAAI/bge-m3 uses 1024 dimension vectors
        self._dimension = 1024
        
        # Setup multi-key support
        keys = []
        if self.settings.huggingface_api_keys:
            keys = [k.strip() for k in self.settings.huggingface_api_keys.split(",") if k.strip()]
        if not keys and self.settings.huggingface_api_key:
            keys = [self.settings.huggingface_api_key]
            
        if not keys:
            raise ValueError("HUGGINGFACE_API_KEY (or keys) is not set — required for embedding.")
            
        # Select a random key for this instance to distribute load
        import random
        selected_key = random.choice(keys)
            
        self._client = InferenceClient(
            provider="hf-inference",
            api_key=selected_key,
        )

    @property
    def dimension(self) -> int:
        """Return the embedding vector dimension."""
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        if not texts:
            return []
            
        all_embeddings = []
        # Process in batches to prevent payload size issues
        batch_size = 32
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            try:
                t0 = time.perf_counter()
                
                # BAAI/bge-m3 via HuggingFace uses the sentence_similarity or feature-extraction endpoint
                # The prompt structure requires a source_sentence and target sentences, but for generic
                # chunk embeddings, feature-extraction works best, or passing the batch directly.
                
                # HuggingFace `feature-extraction` API wrapper
                result = self._client.feature_extraction(
                    text=batch,
                    model=self.settings.embedding_model,
                )
                
                # Convert numpy arrays to standard lists
                emb_batch = result.tolist()
                
                # Inference API might return 3D arrays [batch][seq][dim] or 2D [batch][dim]
                # BGE-M3 often returns [batch, dim] 
                if len(emb_batch) > 0 and isinstance(emb_batch[0], list) and isinstance(emb_batch[0][0], list):
                    # Has sequence dimension (pooled output usually at index 0 or requires mean pooling)
                    # We'll take the first token (CLS) for simplicity if it's 3D
                    emb_batch = [seq[0] for seq in emb_batch]
                    
                all_embeddings.extend(emb_batch)
                logger.info(f"[Embedding] Batch size {len(batch)} embedded in {time.perf_counter() - t0:.2f}s")
            except Exception as e:
                logger.error(f"[Embedding] Failed to embed batch: {e}")
                raise

        return all_embeddings

    def embed_single(self, text: str) -> list[float]:
        """Embed a single text string."""
        return self.embed([text])[0]

    # Alias for backward compatibility
    embed_batch = embed
