"""
WebSocket support for real-time pipeline progress.

Provides:
  - PipelineProgress singleton that agents/routes use to broadcast events
  - WebSocket clients connect via /ws/{rfp_id} to get live updates
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class PipelineProgress:
    """
    In-process event bus.
    Every connected WebSocket client for a given rfp_id receives
    JSON messages like:
        { "event": "node_start", "agent": "A1_INTAKE", "ts": "..." }
        { "event": "node_end",   "agent": "A1_INTAKE", "status": "INTAKE_COMPLETE" }
        { "event": "pipeline_end", "status": "SUBMITTED" }
        { "event": "error", "agent": "A3_GO_NO_GO", "message": "..." }
    """

    _instance: PipelineProgress | None = None

    def __init__(self) -> None:
        self._clients: dict[str, list[WebSocket]] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def get(cls) -> PipelineProgress:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ── Client management ────────────────────────────────

    async def connect(self, rfp_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.setdefault(rfp_id, []).append(ws)
        for msg in self._history.get(rfp_id, []):
            try:
                await ws.send_json(msg)
            except Exception:
                break

    def disconnect(self, rfp_id: str, ws: WebSocket) -> None:
        clients = self._clients.get(rfp_id, [])
        if ws in clients:
            clients.remove(ws)

    # ── Broadcasting (thread-safe for sync pipeline) ─────

    def emit(self, rfp_id: str, event: dict[str, Any]) -> None:
        event.setdefault("ts", datetime.now(timezone.utc).isoformat())
        self._history.setdefault(rfp_id, []).append(event)

        clients = self._clients.get(rfp_id, [])
        if not clients:
            return

        loop = self._loop
        if loop is None or loop.is_closed():
            return

        asyncio.run_coroutine_threadsafe(self._broadcast(rfp_id, event), loop)

    async def _broadcast(self, rfp_id: str, event: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in self._clients.get(rfp_id, []):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(rfp_id, ws)

    # ── Convenience helpers ──────────────────────────────

    def on_node_start(self, rfp_id: str, agent: str) -> None:
        self.emit(rfp_id, {"event": "node_start", "agent": agent})
        logger.info(f"▶  [{rfp_id}] Starting node: {agent}")

    def on_node_end(self, rfp_id: str, agent: str, status: str) -> None:
        self.emit(rfp_id, {"event": "node_end", "agent": agent, "status": status})
        logger.info(f"✓  [{rfp_id}] Completed node: {agent} → {status}")

    def on_pipeline_end(self, rfp_id: str, status: str) -> None:
        self.emit(rfp_id, {"event": "pipeline_end", "status": status})
        logger.info(f"══ [{rfp_id}] Pipeline finished: {status}")

    def on_error(self, rfp_id: str, agent: str, message: str) -> None:
        self.emit(rfp_id, {"event": "error", "agent": agent, "message": message})
        logger.error(f"✗  [{rfp_id}] Error in {agent}: {message}")

    def clear(self, rfp_id: str) -> None:
        self._history.pop(rfp_id, None)
