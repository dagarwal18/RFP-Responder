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
    mock_mode: bool = True  # When True, all agents return mock data

    # ── LLM ──────────────────────────────────────────────
    llm_provider: str = "openai"  # "openai" | "anthropic"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    llm_model: str = "gpt-4o"
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

    # ── MCP / Vector Store ───────────────────────────────
    vector_db_backend: str = "chroma"  # "chroma" | "pinecone" | "weaviate"
    chroma_persist_dir: str = "./chroma_db"
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
