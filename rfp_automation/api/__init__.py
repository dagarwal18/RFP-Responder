"""
FastAPI application factory and API package.

Run with:
    uvicorn rfp_automation.api:app --reload --port 8000

Or via main.py:
    python -m rfp_automation.main --serve
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rfp_automation.config import get_settings
from rfp_automation.api.routes import rfp_router, health_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Application factory — create and configure the FastAPI instance."""
    settings = get_settings()

    application = FastAPI(
        title="RFP Response Automation API",
        description="Backend API for the multi-agent RFP response system",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — allow the Next.js frontend (adjust origins in production)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register route groups
    application.include_router(health_router, tags=["Health"])
    application.include_router(rfp_router, prefix="/api/rfp", tags=["RFP"])

    @application.on_event("startup")
    async def startup():
        logger.info(f"Starting {settings.app_name} API")

    return application


# Module-level instance for `uvicorn rfp_automation.api:app`
app = create_app()
