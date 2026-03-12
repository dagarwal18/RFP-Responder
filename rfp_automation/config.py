"""
Application configuration using Pydantic Settings.

Secrets & connection strings → .env file
Model names, thresholds, behavior → hardcoded defaults below
"""

from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings.

    Only API keys and connection URIs should be set via .env.
    All model names, temperatures, thresholds, and behavior params
    are hardcoded defaults here so they stay in version control.
    """

    # ═══════════════════════════════════════════════════════
    #  SECRETS — these MUST come from .env
    # ═══════════════════════════════════════════════════════
    groq_api_key: str = ""
    groq_api_keys: str = ""  # comma-separated keys for round-robin
    pinecone_api_key: str = ""
    mongodb_uri: str = "mongodb://localhost:27017"
    huggingface_api_key: str = ""
    aws_access_key: str = ""
    aws_secret_key: str = ""

    # ═══════════════════════════════════════════════════════
    #  APP / API SERVER — defaults, overridable via .env
    # ═══════════════════════════════════════════════════════
    app_name: str = "RFP Response Automation"
    debug: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    # ═══════════════════════════════════════════════════════
    #  MODEL & INFERENCE CONFIG — hardcoded, NOT in .env
    # ═══════════════════════════════════════════════════════

    # ── LLM (Groq Cloud) ────────────────────────────────
    llm_model: str = "qwen/qwen3-32b"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 8192

    # ── Large-context model (for validation, writing) ───
    llm_large_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    llm_large_max_tokens: int = 8192

    # ── VLM (HuggingFace Inference API) ─────────────────
    vlm_provider: str = "huggingface"  # "huggingface" or "groq"
    vlm_model: str = "Qwen/Qwen3-VL-8B-Instruct:novita"
    vlm_max_tokens: int = 4096
    vlm_enabled: bool = True  # Feature flag to disable VLM processing

    # -- Deterministic LLM overrides (B1, C1, etc.)
    extraction_llm_temperature: float = 0.0
    extraction_llm_top_p: float = 1.0

    # -- Embeddings
    embedding_model: str = "all-MiniLM-L6-v2"

    # ═══════════════════════════════════════════════════════
    #  INFRASTRUCTURE — connection params
    # ═══════════════════════════════════════════════════════
    mongodb_database: str = "rfp_automation"

    storage_backend: str = "local"        # "local" | "s3"
    local_storage_path: str = "./storage"
    aws_s3_bucket: str = ""
    aws_region: str = "us-east-1"

    pinecone_index_name: str = "rfp-automation"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"

    # ═══════════════════════════════════════════════════════
    #  PIPELINE BEHAVIOR — thresholds & limits
    # ═══════════════════════════════════════════════════════
    max_validation_retries: int = 3
    max_structuring_retries: int = 3
    min_validation_confidence: float = 0.7
    approval_timeout_hours: int = 48

    # -- B1 extraction tuning
    extraction_dedup_similarity_threshold: float = 0.99
    extraction_coverage_warn_ratio: float = 0.6
    extraction_max_chunk_size: int = 2000
    extraction_min_output_headroom_ratio: float = 0.40
    extraction_min_candidate_density: float = 0.15

    # -- Knowledge data seed path (optional)
    knowledge_data_path: str = ""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings (singleton)."""
    return Settings()

