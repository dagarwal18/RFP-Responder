"""
API routes — thin HTTP layer that delegates to the orchestration.

Routes:
  GET  /health                  → API health check
  POST /api/rfp/upload          → Upload an RFP file and start the pipeline
  GET  /api/rfp/{rfp_id}/status → Poll current pipeline status
  POST /api/rfp/{rfp_id}/approve → Human approval gate action
  GET  /api/rfp/list            → List all RFP runs
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from rfp_automation.config import get_settings

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
    """Basic health check — confirms the API is running."""
    settings = get_settings()
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Upload & Start Pipeline ─────────────────────────────

@rfp_router.post("/upload", response_model=UploadResponse)
async def upload_rfp(file: UploadFile = File(...)):
    """
    Upload an RFP document and start the processing pipeline.

    In Phase 3+ this will:
    1. Save the file to storage (local/S3)
    2. Kick off the LangGraph pipeline as a background job (Redis queue)
    3. Return the RFP ID for status polling

    For now (mock mode) it runs the pipeline synchronously.
    """
    rfp_id = f"RFP-{uuid.uuid4().hex[:8].upper()}"

    logger.info(f"Received upload: {file.filename} → {rfp_id}")

    # Save file temporarily
    file_bytes = await file.read()
    local_path = f"./storage/uploads/{rfp_id}_{file.filename}"

    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(file_bytes)

    # Run pipeline (synchronous for now — will become a background job)
    from rfp_automation.orchestration.graph import run_pipeline

    try:
        result = run_pipeline(uploaded_file_path=local_path)
        status = str(result.get("status", "UNKNOWN"))
    except Exception as e:
        logger.error(f"Pipeline failed for {rfp_id}: {e}")
        status = "FAILED"
        result = {"error": str(e)}

    _runs[rfp_id] = {
        "rfp_id": rfp_id,
        "filename": file.filename,
        "status": status,
        "current_agent": result.get("current_agent", ""),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "result": result,
    }

    return UploadResponse(
        rfp_id=rfp_id,
        status=status,
        message=f"Pipeline completed with status: {status}",
    )


# ── Status Polling ───────────────────────────────────────

@rfp_router.get("/{rfp_id}/status", response_model=StatusResponse)
async def get_rfp_status(rfp_id: str):
    """Get the current status of an RFP pipeline run."""
    run = _runs.get(rfp_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"RFP {rfp_id} not found")

    return StatusResponse(
        rfp_id=run["rfp_id"],
        status=run["status"],
        current_agent=run.get("current_agent", ""),
        started_at=run["started_at"],
        result=run.get("result"),
    )


# ── Human Approval Gate ─────────────────────────────────

@rfp_router.post("/{rfp_id}/approve", response_model=ApprovalResponse)
async def approve_rfp(rfp_id: str, body: ApprovalRequest):
    """
    Submit approval / rejection decision at the F1 human gate.

    In the real implementation this will resume the paused LangGraph
    execution. For now it just updates the stored status.
    """
    run = _runs.get(rfp_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"RFP {rfp_id} not found")

    if body.decision not in ("APPROVE", "REJECT"):
        raise HTTPException(status_code=400, detail="Decision must be APPROVE or REJECT")

    logger.info(f"[{rfp_id}] Human gate: {body.decision} by {body.reviewer}")

    # TODO: Actually resume the paused graph execution
    run["status"] = "SUBMITTED" if body.decision == "APPROVE" else "REJECTED"

    return ApprovalResponse(
        rfp_id=rfp_id,
        decision=body.decision,
        message=f"RFP {rfp_id} {body.decision.lower()}d",
    )


# ── List All Runs ────────────────────────────────────────

@rfp_router.get("/list")
async def list_rfps():
    """List all RFP pipeline runs (summary only)."""
    return [
        {
            "rfp_id": r["rfp_id"],
            "filename": r.get("filename", ""),
            "status": r["status"],
            "started_at": r["started_at"],
        }
        for r in _runs.values()
    ]
