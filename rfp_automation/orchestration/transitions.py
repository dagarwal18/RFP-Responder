"""
Routing functions for LangGraph conditional edges.

Each function inspects the current state dict and returns the name
of the next node to execute.  These are the governance checkpoints
described in the project spec.
"""

from __future__ import annotations

from typing import Any

from rfp_automation.config import get_settings


# ── After A2 Structuring ─────────────────────────────────

def route_after_structuring(state: dict[str, Any]) -> str:
    """
    If structuring confidence is too low after max retries → escalate.
    Otherwise → proceed to A3 Go/No-Go.
    """
    settings = get_settings()
    result = state.get("structuring_result", {})
    confidence = result.get("overall_confidence", 0)
    retries = result.get("retry_count", 0)

    if confidence < 0.6 and retries >= settings.max_structuring_retries:
        return "escalate_structuring"
    elif confidence < 0.6:
        return "a2_structuring"  # retry
    return "a3_go_no_go"


# ── After A3 Go / No-Go ──────────────────────────────────

def route_after_go_no_go(state: dict[str, Any]) -> str:
    """
    NO_GO → end.
    GO   → proceed to B1 Requirements Extraction.
    """
    result = state.get("go_no_go_result", {})
    decision = result.get("decision", "GO")

    if decision == "NO_GO":
        return "end_no_go"
    return "b1_requirements_extraction"


# ── After D1 Technical Validation ─────────────────────────

def route_after_validation(state: dict[str, Any]) -> str:
    """
    REJECT and retries < max → loop back to C3 Narrative Assembly.
    REJECT and retries >= max → escalate to human review.
    PASS → proceed to E1+E2 (commercial+legal parallel).
    """
    settings = get_settings()
    result = state.get("technical_validation", {})
    decision = result.get("decision", "PASS")
    retries = result.get("retry_count", 0)

    if decision == "REJECT":
        if retries >= settings.max_validation_retries:
            return "escalate_validation"
        return "c3_narrative_assembly"  # loop back
    return "commercial_legal_parallel"


# ── After E1+E2 Commercial & Legal Gate ───────────────────

def route_after_commercial_legal(state: dict[str, Any]) -> str:
    """
    BLOCK from E2 → end (legal veto).
    CLEAR → proceed to F1 Final Readiness.
    """
    gate = state.get("commercial_legal_gate", {})
    decision = gate.get("gate_decision", "CLEAR")

    if decision == "BLOCK":
        return "end_legal_block"
    return "f1_final_readiness"


# ── After F1 Human Approval ──────────────────────────────

def route_after_approval(state: dict[str, Any]) -> str:
    """
    APPROVE → F2 Submission.
    REJECT  → end.
    REQUEST_CHANGES → (could loop, for now end).
    """
    package = state.get("approval_package", {})
    decision = package.get("approval_decision", None)

    if decision == "APPROVE":
        return "f2_submission"
    return "end_rejected"
