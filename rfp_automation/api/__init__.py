"""
FastAPI application factory and API package.

Run with:
    uvicorn rfp_automation.api:app --reload --port 8000

Or via main.py:
    python -m rfp_automation.main --serve
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rfp_automation.config import get_settings
from rfp_automation.api.routes import rfp_router, health_router
from rfp_automation.api.knowledge_routes import knowledge_router
from rfp_automation.api.websocket import PipelineProgress

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

    # CORS — allow the frontend (adjust origins in production)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register route groups (includes WebSocket at /api/rfp/ws/{rfp_id})
    application.include_router(health_router, tags=["Health"])
    application.include_router(rfp_router, prefix="/api/rfp", tags=["RFP"])
    application.include_router(knowledge_router, prefix="/api/knowledge", tags=["Knowledge"])

    # Serve frontend static files
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
    if frontend_dir.exists():
        application.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

        @application.get("/")
        async def serve_frontend():
            return FileResponse(str(frontend_dir / "index.html"))

    @application.on_event("startup")
    async def startup():
        # Give the PipelineProgress singleton the server's event loop
        # so background pipeline threads can push WebSocket messages.
        PipelineProgress.get().set_loop(asyncio.get_running_loop())
        logger.info(f"Starting {settings.app_name} API")
        logger.info(f"Dashboard: http://localhost:8000/")

    return application


# Module-level instance for `uvicorn rfp_automation.api:app`
app = create_app()
