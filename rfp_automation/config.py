"""
Application configuration using Pydantic Settings.
All environment-specific values are centralized here.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── App ──────────────────────────────────────────────
    app_name: str = "RFP Response Automation"
    debug: bool = True

    # ── LLM (Groq Cloud) ────────────────────────────────
    groq_api_key: str = ""
    llm_model: str = "llama-3.3-70b-versatile"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 4096

    # ── MongoDB ──────────────────────────────────────────
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "rfp_automation"

    # ── File Storage ─────────────────────────────────────
    storage_backend: str = "local"  # "local" | "s3"
    local_storage_path: str = "./storage"
    aws_s3_bucket: str = ""
    aws_access_key: str = ""
    aws_secret_key: str = ""
    aws_region: str = "us-east-1"

    # ── Pinecone Vector DB ───────────────────────────────
    pinecone_api_key: str = ""
    pinecone_index_name: str = "rfp-automation"
    pinecone_environment: str = "us-east-1"

    # ── Embeddings ───────────────────────────────────────
    embedding_model: str = "all-MiniLM-L6-v2"

    # ── Pipeline Limits ──────────────────────────────────
    max_validation_retries: int = 3
    max_structuring_retries: int = 3
    approval_timeout_hours: int = 48

    # ── Logging ──────────────────────────────────────────
    log_level: str = "INFO"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings (singleton)."""
    return Settings()
