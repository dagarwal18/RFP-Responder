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

import hashlib
from copy import deepcopy

logger = logging.getLogger(__name__)

# ── Routers ──────────────────────────────────────────────
health_router = APIRouter()
rfp_router = APIRouter()

# ── In-memory store (replaced by MongoDB/Redis later) ────
_runs: dict[str, dict[str, Any]] = {}

# ── Document Cache (Memory only for now) ─────────────────
# Maps file SHA256 -> previous rfp_id
_document_cache: dict[str, str] = {}


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
    agent_outputs: dict[str, Any] = {}


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

def _run_pipeline_thread(rfp_id: str, local_path: str, file_hash: str) -> None:
    """Run the pipeline in a background thread so the HTTP response returns immediately."""
    from rfp_automation.orchestration.graph import run_pipeline

    progress = PipelineProgress.get()

    try:
        result = run_pipeline(
            uploaded_file_path=local_path,
            initial_state={"tracking_rfp_id": rfp_id},
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
             "timestamp": (
                 a["timestamp"].isoformat()
                 if hasattr(a.get("timestamp"), "isoformat")
                 else str(a.get("timestamp", ""))
             )}
            for a in audit
        ] if audit else []

        _runs[rfp_id].update({
            "status": status,
            "current_agent": result.get("current_agent", ""),
            "pipeline_log": pipeline_log,
            "result": result,
            "real_rfp_id": real_rfp_id,
        })
        
        # Cache successful runs based on the file hash
        if status not in ("FAILED", "ESCALATED"):
            _document_cache[file_hash] = rfp_id
            logger.info(f"Cached document hash {file_hash[:8]}... to run {rfp_id}")

        progress.on_pipeline_end(rfp_id, status)

    except Exception as e:
        logger.error(f"Pipeline failed for {rfp_id}: {e}")

        # Extract partial state from the exception if available
        # (run_pipeline attaches it via compiled.stream() checkpointing)
        partial = getattr(e, "partial_state", None)
        error_result: dict[str, Any] = {"error": str(e)}
        if isinstance(partial, dict):
            # Merge partial state so completed agent outputs are visible
            error_result.update(partial)
            error_result["error"] = str(e)  # ensure error is not overwritten
            logger.info(
                f"Preserved partial state with keys: "
                f"{[k for k in partial if partial[k] is not None and partial[k] != [] and partial[k] != dict()]}"
            )

        _runs[rfp_id].update({
            "status": "FAILED",
            "current_agent": "",
            "pipeline_log": [{"agent": "SYSTEM", "status": f"FAILED: {e}",
                              "timestamp": datetime.now(timezone.utc).isoformat()}],
            "result": error_result,
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
    in a background thread. Returns immediately with the rfp_id.
    Uses SHA-256 fingerprinting to skip processing for duplicate files.
    """
    rfp_id = f"RFP-{uuid.uuid4().hex[:8].upper()}"
    filename = file.filename or "unknown.pdf"

    logger.info(f"Received upload: {filename} → {rfp_id}")

    # Save file temporarily and compute hash
    file_bytes = await file.read()
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    logger.debug(f"Computed file hash: {file_hash}")

    local_path = f"./storage/uploads/{rfp_id}_{filename}"
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(file_bytes)

    started_at = datetime.now(timezone.utc).isoformat()
    
    # ── Check Cache ──────────────────────────────────────────
    cached_run_id = _document_cache.get(file_hash)
    if cached_run_id and cached_run_id in _runs:
        cached_run = _runs[cached_run_id]
        if cached_run["status"] not in ("FAILED", "ESCALATED", "UNKNOWN"):
            logger.info(f"Cache hit! Reusing results from {cached_run_id} for new upload {rfp_id}")
            
            # Deep clone the cached result to our new ID
            _runs[rfp_id] = deepcopy(cached_run)
            _runs[rfp_id].update({
                "rfp_id": rfp_id,
                "filename": filename,
                "started_at": started_at,
            })
            
            # Clean up temp file immediately since we don't need to process it
            try:
                os.remove(local_path)
            except OSError:
                pass
                
            return UploadResponse(
                rfp_id=rfp_id,
                status=_runs[rfp_id]["status"],
                message=f"Cache hit. Pipeline instantly loaded results for {filename}. Connect to /ws/{rfp_id} or poll /status.",
            )

    # ── Cache Miss → Run normal pipeline ──────────────────────
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
        args=(rfp_id, local_path, file_hash),
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

    # Build agent_outputs from the stored pipeline result
    agent_outputs: dict[str, Any] = {}
    result_data = run.get("result")
    if isinstance(result_data, dict):
        # A1 Intake
        meta = result_data.get("rfp_metadata")
        if isinstance(meta, dict) and meta.get("rfp_id"):
            agent_outputs["A1_INTAKE"] = meta
        # A2 Structuring
        struct = result_data.get("structuring_result")
        if isinstance(struct, dict) and struct.get("sections"):
            agent_outputs["A2_STRUCTURING"] = struct
        # A3 Go/No-Go
        gng = result_data.get("go_no_go_result")
        if isinstance(gng, dict) and gng.get("decision"):
            agent_outputs["A3_GO_NO_GO"] = gng
        # B1 Requirements Extraction — include even when empty (shows the agent ran)
        reqs = result_data.get("requirements")
        if isinstance(reqs, list):  # include regardless of empty
            agent_outputs["B1_REQUIREMENTS_EXTRACTION"] = reqs
        # B2 Requirements Validation — include whenever key is present
        req_val = result_data.get("requirements_validation")
        if isinstance(req_val, dict):
            agent_outputs["B2_REQUIREMENTS_VALIDATION"] = req_val
        # C1 Architecture Planning
        arch = result_data.get("architecture_plan")
        if isinstance(arch, dict) and arch.get("sections"):
            agent_outputs["C1_ARCHITECTURE_PLANNING"] = arch
        # C2 Requirement Writing
        writing = result_data.get("writing_result")
        if isinstance(writing, dict) and writing.get("section_responses"):
            agent_outputs["C2_REQUIREMENT_WRITING"] = writing
        # C3 Narrative Assembly
        proposal = result_data.get("assembled_proposal")
        if isinstance(proposal, dict) and proposal.get("full_narrative"):
            agent_outputs["C3_NARRATIVE_ASSEMBLY"] = proposal

    return StatusResponse(
        rfp_id=run["rfp_id"],
        status=run["status"],
        current_agent=run.get("current_agent", ""),
        started_at=run["started_at"],
        filename=run.get("filename", ""),
        pipeline_log=run.get("pipeline_log", []),
        result=run.get("result"),
        agent_outputs=agent_outputs,
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
    # Also check for runs persisted as checkpoints on disk
    from rfp_automation.persistence.checkpoint import (
        list_checkpoints as _list_cp,
    )
    import os

    # Merge in-memory runs
    runs_list = [
        {
            "rfp_id": r["rfp_id"],
            "filename": r.get("filename", ""),
            "status": r["status"],
            "started_at": r["started_at"],
        }
        for r in _runs.values()
    ]

    # Also discover checkpoint-only runs (survived reload)
    cp_root = Path("./storage/checkpoints")
    if cp_root.exists():
        for rfp_dir in cp_root.iterdir():
            if rfp_dir.is_dir() and rfp_dir.name not in _runs:
                checkpoints = _list_cp(rfp_dir.name)
                if checkpoints:
                    runs_list.append({
                        "rfp_id": rfp_dir.name,
                        "filename": "(checkpointed)",
                        "status": "CHECKPOINTED",
                        "started_at": checkpoints[0].get("saved_at", ""),
                    })

    return runs_list


# ── Checkpoints ──────────────────────────────────────────

@rfp_router.get("/{rfp_id}/checkpoints")
async def get_checkpoints(rfp_id: str):
    """List available agent checkpoints for an RFP."""
    from rfp_automation.persistence.checkpoint import (
        list_checkpoints,
        AGENT_ORDER,
    )

    checkpoints = list_checkpoints(rfp_id)
    available_agents = [cp["agent"] for cp in checkpoints]

    # Determine which agents can be re-run (those whose predecessor has a checkpoint)
    rerunnable = []
    for agent in AGENT_ORDER:
        if agent == AGENT_ORDER[0]:
            rerunnable.append(agent)  # A1 can always be re-run (from scratch)
        else:
            prev_idx = AGENT_ORDER.index(agent) - 1
            if AGENT_ORDER[prev_idx] in available_agents:
                rerunnable.append(agent)

    return {
        "rfp_id": rfp_id,
        "checkpoints": checkpoints,
        "rerunnable_from": rerunnable,
    }


@rfp_router.delete("/{rfp_id}/checkpoints")
async def clear_rfp_checkpoints(rfp_id: str):
    """Clear all cached checkpoints for an RFP to force a full re-run."""
    from rfp_automation.persistence.checkpoint import clear_checkpoints

    count = clear_checkpoints(rfp_id)
    return {
        "rfp_id": rfp_id,
        "cleared": count,
        "message": f"Cleared {count} checkpoint files. Next run will execute all agents.",
    }


# ── Re-run from Agent ────────────────────────────────────

def _rerun_pipeline_thread(rfp_id: str, start_from: str, checkpoint_state: dict) -> None:
    """Background thread for re-running the pipeline from a specific agent."""
    from rfp_automation.orchestration.graph import run_pipeline_from

    progress = PipelineProgress.get()

    try:
        result = run_pipeline_from(start_from, checkpoint_state)
        status = str(result.get("status", "UNKNOWN"))

        audit = result.get("audit_trail", [])
        pipeline_log = [
            {"agent": a.get("agent", ""), "status": a.get("action", ""),
             "timestamp": (
                 a["timestamp"].isoformat()
                 if hasattr(a.get("timestamp"), "isoformat")
                 else str(a.get("timestamp", ""))
             )}
            for a in audit
        ] if audit else []

        _runs[rfp_id].update({
            "status": status,
            "current_agent": result.get("current_agent", ""),
            "pipeline_log": pipeline_log,
            "result": result,
        })
        progress.on_pipeline_end(rfp_id, status)

    except Exception as e:
        logger.error(f"Rerun failed for {rfp_id} from {start_from}: {e}")

        partial = getattr(e, "partial_state", None)
        error_result: dict[str, Any] = {"error": str(e)}
        if isinstance(partial, dict):
            error_result.update(partial)
            error_result["error"] = str(e)

        _runs[rfp_id].update({
            "status": "FAILED",
            "current_agent": "",
            "pipeline_log": [{"agent": "SYSTEM", "status": f"RERUN FAILED from {start_from}: {e}",
                              "timestamp": datetime.now(timezone.utc).isoformat()}],
            "result": error_result,
        })
        progress.on_error(rfp_id, "SYSTEM", str(e))
        progress.on_pipeline_end(rfp_id, "FAILED")


@rfp_router.post("/{rfp_id}/rerun")
async def rerun_from_agent(rfp_id: str, start_from: str):
    """
    Re-run the pipeline from a specific agent using cached checkpoint state.

    Example: POST /api/rfp/RFP-ABC123/rerun?start_from=c1_architecture_planning
    This loads b2_requirements_validation's checkpoint and runs C1 onwards.
    """
    from rfp_automation.persistence.checkpoint import (
        load_checkpoint_up_to,
        AGENT_ORDER,
    )

    if start_from not in AGENT_ORDER:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown agent '{start_from}'. Valid: {AGENT_ORDER}",
        )

    # For a1_intake, there's no predecessor — must do full run
    if start_from == "a1_intake":
        raise HTTPException(
            status_code=400,
            detail="Cannot rerun from a1_intake — use /upload for a fresh run.",
        )

    checkpoint = load_checkpoint_up_to(rfp_id, start_from)
    if checkpoint is None:
        raise HTTPException(
            status_code=404,
            detail=f"No checkpoint found for the agent before '{start_from}'. "
                   f"The previous agents must have completed at least once.",
        )

    started_at = datetime.now(timezone.utc).isoformat()

    _runs[rfp_id] = {
        "rfp_id": rfp_id,
        "filename": _runs.get(rfp_id, {}).get("filename", "(rerun)"),
        "status": "RUNNING",
        "current_agent": start_from,
        "started_at": started_at,
        "pipeline_log": [],
        "result": None,
    }

    thread = threading.Thread(
        target=_rerun_pipeline_thread,
        args=(rfp_id, start_from, checkpoint),
        daemon=True,
    )
    thread.start()

    return {
        "rfp_id": rfp_id,
        "status": "RUNNING",
        "start_from": start_from,
        "message": f"Pipeline re-running from {start_from}. Connect to /ws/{rfp_id} for progress.",
    }

# ── Requirements (B1 output) ────────────────────────────

@rfp_router.get("/{rfp_id}/requirements")
async def get_requirements(rfp_id: str):
    """
    Return extracted requirements (B1) and validation result (B2) for a run.
    """
    run = _runs.get(rfp_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"RFP {rfp_id} not found")

    result_data = run.get("result")
    if not isinstance(result_data, dict):
        return {"rfp_id": rfp_id, "available": False, "message": "Pipeline has not completed yet"}

    reqs = result_data.get("requirements") or []
    req_val = result_data.get("requirements_validation") or {}

    functional = [r for r in reqs if (r.get("classification") or "").upper() == "FUNCTIONAL"]
    non_functional = [r for r in reqs if (r.get("classification") or "").upper() == "NON_FUNCTIONAL"]

    return {
        "rfp_id": rfp_id,
        "available": True,
        "total": len(reqs),
        "functional_count": len(functional),
        "non_functional_count": len(non_functional),
        "requirements": reqs,
        "validation": req_val,
    }


# ── Debug: raw pipeline result ───────────────────────────

@rfp_router.get("/{rfp_id}/debug")
async def debug_rfp(rfp_id: str):
    """Return the raw pipeline result dict for debugging."""
    run = _runs.get(rfp_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"RFP {rfp_id} not found")
    result = run.get("result") or {}
    return {
        "rfp_id": rfp_id,
        "status": run.get("status"),
        "has_requirements": bool(result.get("requirements")),
        "requirements_count": len(result.get("requirements") or []),
        "has_validation": bool(result.get("requirements_validation")),
        "keys_in_result": list(result.keys()) if result else [],
    }


# ── Requirement Mappings ─────────────────────────────────

@rfp_router.get("/{rfp_id}/mappings")
async def get_requirement_mappings(rfp_id: str):
    """
    Return the requirement-mapping table for a given RFP run.
    Provides scores, summary counts, and individual mappings.
    """
    run = _runs.get(rfp_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"RFP {rfp_id} not found")

    result_data = run.get("result")
    if not isinstance(result_data, dict):
        return {
            "rfp_id": rfp_id,
            "available": False,
            "message": "Pipeline has not completed yet",
        }

    gng = result_data.get("go_no_go_result")
    if not isinstance(gng, dict) or not gng.get("requirement_mappings"):
        return {
            "rfp_id": rfp_id,
            "available": False,
            "message": "No requirement mapping data available for this run",
        }

    return {
        "rfp_id": rfp_id,
        "available": True,
        "decision": gng.get("decision", "UNKNOWN"),
        "justification": gng.get("justification", ""),
        "scores": {
            "strategic_fit": gng.get("strategic_fit_score", 0),
            "technical_feasibility": gng.get("technical_feasibility_score", 0),
            "regulatory_risk": gng.get("regulatory_risk_score", 0),
        },
        "summary": {
            "total": gng.get("total_requirements", 0),
            "aligned": gng.get("aligned_count", 0),
            "violated": gng.get("violated_count", 0),
            "risk": gng.get("risk_count", 0),
            "no_match": gng.get("no_match_count", 0),
        },
        "red_flags": gng.get("red_flags", []),
        "policy_violations": gng.get("policy_violations", []),
        "mappings": gng.get("requirement_mappings", []),
    }


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
