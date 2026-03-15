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
from rfp_automation.models.enums import HumanValidationDecision, PipelineStatus
from rfp_automation.models.schemas import ReviewComment, ReviewPackage
from rfp_automation.services.review_service import ReviewService

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
    llm_stats: dict[str, Any] = {}


class ApprovalRequest(BaseModel):
    decision: str  # "APPROVE" | "REJECT"
    reviewer: str = ""
    comments: str = ""


class ApprovalResponse(BaseModel):
    rfp_id: str
    decision: str
    message: str


class ReviewCommentsRequest(BaseModel):
    comments: list[ReviewComment] = []


class ReviewPackageResponse(BaseModel):
    rfp_id: str
    status: str
    review_package: ReviewPackage


class ReviewDecisionRequest(BaseModel):
    decision: HumanValidationDecision
    reviewer: str = ""
    summary: str = ""
    rerun_from: str = "auto"
    comments: list[ReviewComment] = []


class ReviewDecisionResponse(BaseModel):
    rfp_id: str
    decision: str
    status: str
    rerun_from: str = ""
    message: str


def _build_pipeline_log(audit: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "agent": a.get("agent", ""),
            "status": a.get("action", ""),
            "timestamp": (
                a["timestamp"].isoformat()
                if hasattr(a.get("timestamp"), "isoformat")
                else str(a.get("timestamp", ""))
            ),
        }
        for a in audit
    ] if audit else []


def _get_run_or_404(rfp_id: str) -> dict[str, Any]:
    run = _runs.get(rfp_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"RFP {rfp_id} not found")
    return run


def _ensure_result_dict(run: dict[str, Any]) -> dict[str, Any]:
    result = run.get("result")
    if not isinstance(result, dict):
        result = {}
        run["result"] = result
    return result


def _get_review_package(run: dict[str, Any]) -> ReviewPackage:
    result = run.get("result")
    package_data = result.get("review_package") if isinstance(result, dict) else None
    return ReviewService.normalize_package(package_data)


def _store_review_package(run: dict[str, Any], review_package: ReviewPackage) -> None:
    package = ReviewService.normalize_package(review_package)
    result = _ensure_result_dict(run)
    result["review_package"] = package.model_dump(mode="json")
    run["result"] = result


def _inject_review_package(
    checkpoint_state: dict[str, Any],
    review_package: ReviewPackage,
) -> dict[str, Any]:
    updated = deepcopy(checkpoint_state)
    updated["review_package"] = review_package.model_dump(mode="json")
    return updated


def _start_rerun_job(rfp_id: str, start_from: str, checkpoint_state: dict[str, Any]) -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    existing = _runs.get(rfp_id, {})
    _runs[rfp_id] = {
        "rfp_id": rfp_id,
        "filename": existing.get("filename", "(rerun)"),
        "status": "RUNNING",
        "current_agent": start_from,
        "started_at": started_at,
        "pipeline_log": [],
        "result": deepcopy(existing.get("result")),
    }

    thread = threading.Thread(
        target=_rerun_pipeline_thread,
        args=(rfp_id, start_from, checkpoint_state),
        daemon=True,
    )
    thread.start()


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
        pipeline_log = _build_pipeline_log(audit)

        _runs[rfp_id].update({
            "status": status,
            "current_agent": result.get("current_agent", ""),
            "pipeline_log": pipeline_log,
            "result": result,
            "real_rfp_id": real_rfp_id,
        })
        
        # Cache stable runs only. Human-validation states should remain unique
        # to preserve reviewer comments and decisions per run.
        cache_exclusions = {
            "FAILED",
            "ESCALATED",
            PipelineStatus.AWAITING_HUMAN_VALIDATION.value,
            PipelineStatus.REJECTED.value,
        }
        if status not in cache_exclusions:
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
        if cached_run["status"] not in (
            "FAILED",
            "ESCALATED",
            "UNKNOWN",
            PipelineStatus.AWAITING_HUMAN_VALIDATION.value,
            PipelineStatus.REJECTED.value,
        ):
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
    run = _get_run_or_404(rfp_id)

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
        # D1 Technical Validation
        tech_val = result_data.get("technical_validation")
        if isinstance(tech_val, dict) and tech_val.get("decision"):
            agent_outputs["D1_TECHNICAL_VALIDATION"] = tech_val
        # E1 Commercial
        comm = result_data.get("commercial_result")
        if isinstance(comm, dict) and comm.get("decision"):
            agent_outputs["E1_COMMERCIAL"] = comm
        # E2 Legal
        legal = result_data.get("legal_result")
        if isinstance(legal, dict) and legal.get("decision"):
            agent_outputs["E2_LEGAL"] = legal
        # H1 Human Validation
        review = result_data.get("review_package")
        if isinstance(review, dict) and review.get("review_id"):
            agent_outputs["H1_HUMAN_VALIDATION"] = review
        # F1 Final Readiness
        approval = result_data.get("approval_package")
        if isinstance(approval, dict) and (
            approval.get("decision_brief") or approval.get("approval_decision")
        ):
            agent_outputs["F1_FINAL_READINESS"] = approval
        # F2 Submission
        submission = result_data.get("submission_record")
        if isinstance(submission, dict) and (
            submission.get("output_file_path") or submission.get("submitted_at")
        ):
            agent_outputs["F2_SUBMISSION"] = submission

    # ── LLM call stats per agent ─────────────────────────
    from rfp_automation.services.llm_service import LLMCallTracker
    llm_stats = LLMCallTracker.get().get_all_stats()

    return StatusResponse(
        rfp_id=run["rfp_id"],
        status=run["status"],
        current_agent=run.get("current_agent", ""),
        started_at=run["started_at"],
        filename=run.get("filename", ""),
        pipeline_log=run.get("pipeline_log", []),
        result=run.get("result"),
        agent_outputs=agent_outputs,
        llm_stats=llm_stats,
    )


# ── Human Approval Gate ─────────────────────────────────
def _append_review_log(run: dict[str, Any], decision: str, reviewer: str = "") -> None:
    run.setdefault("pipeline_log", []).append(
        {
            "agent": "H1_HUMAN_VALIDATION",
            "status": decision,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reviewer": reviewer,
        }
    )


def _handle_review_decision(rfp_id: str, body: ReviewDecisionRequest) -> ReviewDecisionResponse:
    run = _get_run_or_404(rfp_id)
    review_package = _get_review_package(run)
    if not review_package.review_id:
        raise HTTPException(status_code=400, detail="No human validation package is available for this run")

    if body.comments:
        review_package.comments = body.comments
    review_package = ReviewService.normalize_package(review_package)

    if (
        body.decision == HumanValidationDecision.REQUEST_CHANGES
        and review_package.open_comment_count == 0
    ):
        raise HTTPException(
            status_code=400,
            detail="At least one open comment is required when requesting changes",
        )

    review_package.decision.decision = body.decision
    review_package.decision.reviewer = body.reviewer.strip()
    review_package.decision.summary = body.summary.strip()
    review_package.decision.submitted_at = datetime.now(timezone.utc)

    if body.decision == HumanValidationDecision.REJECT:
        review_package.status = "REJECTED"
        review_package.decision.rerun_from = ""
        _store_review_package(run, review_package)
        run["status"] = PipelineStatus.REJECTED.value
        run["current_agent"] = "H1_HUMAN_VALIDATION"
        _append_review_log(run, body.decision.value, body.reviewer)
        PipelineProgress.get().on_pipeline_end(rfp_id, PipelineStatus.REJECTED.value)
        return ReviewDecisionResponse(
            rfp_id=rfp_id,
            decision=body.decision.value,
            status=PipelineStatus.REJECTED.value,
            message=f"Run {rfp_id} was rejected during human validation.",
        )

    start_from = (
        "f1_final_readiness"
        if body.decision == HumanValidationDecision.APPROVE
        else ReviewService.compute_rerun_target(review_package, body.rerun_from)
    )
    review_package.status = (
        "APPROVED"
        if body.decision == HumanValidationDecision.APPROVE
        else "CHANGES_REQUESTED"
    )
    review_package.decision.rerun_from = start_from
    _store_review_package(run, review_package)

    from rfp_automation.persistence.checkpoint import load_checkpoint_up_to

    checkpoint = load_checkpoint_up_to(rfp_id, start_from)
    if checkpoint is None:
        raise HTTPException(
            status_code=404,
            detail=f"No checkpoint found to resume from '{start_from}'",
        )

    checkpoint = _inject_review_package(checkpoint, review_package)
    _append_review_log(run, body.decision.value, body.reviewer)
    _start_rerun_job(rfp_id, start_from, checkpoint)

    action_text = "submission" if body.decision == HumanValidationDecision.APPROVE else "revision"
    return ReviewDecisionResponse(
        rfp_id=rfp_id,
        decision=body.decision.value,
        status="RUNNING",
        rerun_from=start_from,
        message=f"Human validation sent the run to {action_text} from {start_from}.",
    )


@rfp_router.get("/{rfp_id}/review", response_model=ReviewPackageResponse)
async def get_review_package(rfp_id: str):
    run = _get_run_or_404(rfp_id)
    review_package = _get_review_package(run)
    if not review_package.review_id:
        raise HTTPException(status_code=404, detail=f"Run {rfp_id} has no human validation package yet")

    return ReviewPackageResponse(
        rfp_id=rfp_id,
        status=run["status"],
        review_package=review_package,
    )


@rfp_router.put("/{rfp_id}/review/comments", response_model=ReviewPackageResponse)
async def save_review_comments(rfp_id: str, body: ReviewCommentsRequest):
    run = _get_run_or_404(rfp_id)
    review_package = _get_review_package(run)
    if not review_package.review_id:
        raise HTTPException(status_code=404, detail=f"Run {rfp_id} has no human validation package yet")

    review_package.comments = body.comments
    review_package.status = "PENDING"
    review_package.decision = review_package.decision.__class__()
    _store_review_package(run, review_package)

    return ReviewPackageResponse(
        rfp_id=rfp_id,
        status=run["status"],
        review_package=_get_review_package(run),
    )


@rfp_router.post("/{rfp_id}/review/decision", response_model=ReviewDecisionResponse)
async def submit_review_decision(rfp_id: str, body: ReviewDecisionRequest):
    return _handle_review_decision(rfp_id, body)


@rfp_router.post("/{rfp_id}/approve", response_model=ApprovalResponse)
async def approve_rfp(rfp_id: str, body: ApprovalRequest):
    if body.decision not in ("APPROVE", "REJECT"):
        raise HTTPException(status_code=400, detail="Decision must be APPROVE or REJECT")

    result = _handle_review_decision(
        rfp_id,
        ReviewDecisionRequest(
            decision=HumanValidationDecision(body.decision),
            reviewer=body.reviewer,
            summary=body.comments,
        ),
    )
    return ApprovalResponse(
        rfp_id=result.rfp_id,
        decision=result.decision,
        message=result.message,
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
        pipeline_log = _build_pipeline_log(audit)

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

    existing_run = _runs.get(rfp_id)
    if existing_run:
        existing_review = _get_review_package(existing_run)
        if existing_review.review_id:
            checkpoint = _inject_review_package(checkpoint, existing_review)

    _start_rerun_job(rfp_id, start_from, checkpoint)

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
