"""
API routes — thin HTTP layer that delegates to the orchestration.

Routes:
  GET  /health                  → API health check
  POST /api/rfp/upload          → Upload an RFP file and start the pipeline (background)
  GET  /api/rfp/{rfp_id}/status → Poll current pipeline status
  POST /api/rfp/{rfp_id}/approve → Human approval gate action
  GET  /api/rfp/list            → List all RFP runs
  WS   /ws/{rfp_id}             → Real-time pipeline progress
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from rfp_automation.config import get_settings
from rfp_automation.api.websocket import PipelineProgress

logger = logging.getLogger(__name__)

# ── Routers ──────────────────────────────────────────────
health_router = APIRouter()
rfp_router = APIRouter()

# ── In-memory store (replaced by MongoDB/Redis later) ────
_runs: dict[str, dict[str, Any]] = {}


# ── Response schemas ─────────────────────────────────────
class UploadResponse(BaseModel):
    rfp_id: str
    status: str
    message: str


class StatusResponse(BaseModel):
    rfp_id: str
    status: str
    current_agent: str
    started_at: str
    filename: str = ""
    pipeline_log: list[dict[str, str]] = []
    result: dict[str, Any] | None = None


class ApprovalRequest(BaseModel):
    decision: str  # "APPROVE" | "REJECT"
    reviewer: str = ""
    comments: str = ""


class ApprovalResponse(BaseModel):
    rfp_id: str
    decision: str
    message: str


# ── Health ───────────────────────────────────────────────

@health_router.get("/health")
async def health_check():
    settings = get_settings()
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Upload & Start Pipeline (background thread) ─────────

def _run_pipeline_thread(rfp_id: str, local_path: str) -> None:
    """Run the pipeline in a background thread so the HTTP response returns immediately."""
    from rfp_automation.orchestration.graph import run_pipeline

    progress = PipelineProgress.get()

    try:
        result = run_pipeline(
            uploaded_file_path=local_path,
            initial_state={"_tracking_rfp_id": rfp_id},
        )
        status = str(result.get("status", "UNKNOWN"))

        # Use the real rfp_id extracted by intake if available
        real_rfp_id = ""
        meta = result.get("rfp_metadata")
        if isinstance(meta, dict):
            real_rfp_id = meta.get("rfp_id", "")

        audit = result.get("audit_trail", [])
        pipeline_log = [
            {"agent": a.get("agent", ""), "status": a.get("action", ""),
             "timestamp": a.get("timestamp", "")}
            for a in audit
        ] if audit else []

        _runs[rfp_id].update({
            "status": status,
            "current_agent": result.get("current_agent", ""),
            "pipeline_log": pipeline_log,
            "result": result,
            "real_rfp_id": real_rfp_id,
        })

        progress.on_pipeline_end(rfp_id, status)

    except Exception as e:
        logger.error(f"Pipeline failed for {rfp_id}: {e}")
        status = "FAILED"
        _runs[rfp_id].update({
            "status": "FAILED",
            "current_agent": "",
            "pipeline_log": [{"agent": "SYSTEM", "status": f"FAILED: {e}",
                              "timestamp": datetime.now(timezone.utc).isoformat()}],
            "result": {"error": str(e)},
        })
        progress.on_error(rfp_id, "SYSTEM", str(e))
        progress.on_pipeline_end(rfp_id, "FAILED")
    finally:
        # Clean up the temporary uploaded file
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
                logger.info(f"Cleaned up temp file: {local_path}")
        except OSError as cleanup_err:
            logger.warning(f"Failed to clean up {local_path}: {cleanup_err}")


@rfp_router.post("/upload", response_model=UploadResponse)
async def upload_rfp(file: UploadFile = File(...)):
    """
    Upload an RFP document and start the processing pipeline
    in a background thread.  Returns immediately with the rfp_id
    so the frontend can connect via WebSocket for live progress.
    """
    rfp_id = f"RFP-{uuid.uuid4().hex[:8].upper()}"
    filename = file.filename or "unknown.pdf"

    logger.info(f"Received upload: {filename} → {rfp_id}")

    # Save file temporarily
    file_bytes = await file.read()
    local_path = f"./storage/uploads/{rfp_id}_{filename}"
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(file_bytes)

    started_at = datetime.now(timezone.utc).isoformat()
    _runs[rfp_id] = {
        "rfp_id": rfp_id,
        "filename": filename,
        "status": "RUNNING",
        "current_agent": "A1_INTAKE",
        "started_at": started_at,
        "pipeline_log": [],
        "result": None,
    }

    # Launch pipeline in background thread
    thread = threading.Thread(
        target=_run_pipeline_thread,
        args=(rfp_id, local_path),
        daemon=True,
    )
    thread.start()

    return UploadResponse(
        rfp_id=rfp_id,
        status="RUNNING",
        message=f"Pipeline started for {filename}. Connect to /ws/{rfp_id} for live progress.",
    )


# ── Status Polling ───────────────────────────────────────

@rfp_router.get("/{rfp_id}/status", response_model=StatusResponse)
async def get_rfp_status(rfp_id: str):
    run = _runs.get(rfp_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"RFP {rfp_id} not found")

    return StatusResponse(
        rfp_id=run["rfp_id"],
        status=run["status"],
        current_agent=run.get("current_agent", ""),
        started_at=run["started_at"],
        filename=run.get("filename", ""),
        pipeline_log=run.get("pipeline_log", []),
        result=run.get("result"),
    )


# ── Human Approval Gate ─────────────────────────────────

@rfp_router.post("/{rfp_id}/approve", response_model=ApprovalResponse)
async def approve_rfp(rfp_id: str, body: ApprovalRequest):
    run = _runs.get(rfp_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"RFP {rfp_id} not found")

    if body.decision not in ("APPROVE", "REJECT"):
        raise HTTPException(status_code=400, detail="Decision must be APPROVE or REJECT")

    logger.info(f"[{rfp_id}] Human gate: {body.decision} by {body.reviewer}")
    run["status"] = "SUBMITTED" if body.decision == "APPROVE" else "REJECTED"

    return ApprovalResponse(
        rfp_id=rfp_id,
        decision=body.decision,
        message=f"RFP {rfp_id} {body.decision.lower()}d",
    )


# ── List All Runs ────────────────────────────────────────

@rfp_router.get("/list")
async def list_rfps():
    return [
        {
            "rfp_id": r["rfp_id"],
            "filename": r.get("filename", ""),
            "status": r["status"],
            "started_at": r["started_at"],
        }
        for r in _runs.values()
    ]


# ── WebSocket endpoint for real-time pipeline progress ───

@rfp_router.websocket("/ws/{rfp_id}")
async def ws_pipeline_progress(websocket: WebSocket, rfp_id: str):
    """
    WebSocket endpoint — client connects here after POSTing /upload.
    Receives JSON events: node_start, node_end, pipeline_end, error.
    """
    progress = PipelineProgress.get()
    await progress.connect(rfp_id, websocket)
    try:
        while True:
            # Keep the connection alive; client can send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        progress.disconnect(rfp_id, websocket)
    except Exception:
        progress.disconnect(rfp_id, websocket)
