"""
Application configuration using Pydantic Settings.
All environment-specific values are centralized here.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── App / API Server ───────────────────────────────
    app_name: str = "RFP Response Automation"
    debug: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 8000

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
    pinecone_cloud: str = "aws"  # serverless cloud provider
    pinecone_region: str = "us-east-1"  # serverless region

    # ── Embeddings ───────────────────────────────────────
    embedding_model: str = "all-MiniLM-L6-v2"

    # ── Knowledge Data ───────────────────────────────────
    knowledge_data_path: str = ""  # override path to seed JSON files

    # ── Pipeline Limits ──────────────────────────────────
    max_validation_retries: int = 3
    max_structuring_retries: int = 3
    min_validation_confidence: float = 0.7
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
