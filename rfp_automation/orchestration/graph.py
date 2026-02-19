"""
LangGraph State Machine — 12-stage RFP response pipeline.

This module defines the full graph: nodes, edges, conditional routing,
and the parallel fan-out/fan-in for E1+E2.

All nodes delegate to agent.process(state), which returns an updated
state dict that LangGraph merges automatically.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import StateGraph, END

from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.enums import PipelineStatus, CommercialLegalGateDecision
from rfp_automation.agents import (
    IntakeAgent,
    StructuringAgent,
    GoNoGoAgent,
    RequirementsExtractionAgent,
    RequirementsValidationAgent,
    ArchitecturePlanningAgent,
    RequirementWritingAgent,
    NarrativeAssemblyAgent,
    TechnicalValidationAgent,
    CommercialAgent,
    LegalAgent,
    FinalReadinessAgent,
    SubmissionAgent,
)
from rfp_automation.orchestration.transitions import (
    route_after_structuring,
    route_after_go_no_go,
    route_after_validation,
    route_after_commercial_legal,
    route_after_approval,
)

logger = logging.getLogger(__name__)

# ── Instantiate agents (singletons for the graph) ────────

_a1 = IntakeAgent()
_a2 = StructuringAgent()
_a3 = GoNoGoAgent()
_b1 = RequirementsExtractionAgent()
_b2 = RequirementsValidationAgent()
_c1 = ArchitecturePlanningAgent()
_c2 = RequirementWritingAgent()
_c3 = NarrativeAssemblyAgent()
_d1 = TechnicalValidationAgent()
_e1 = CommercialAgent()
_e2 = LegalAgent()
_f1 = FinalReadinessAgent()
_f2 = SubmissionAgent()


# ── Terminal nodes (set final status and stop) ───────────

def end_no_go(state: dict[str, Any]) -> dict[str, Any]:
    """Pipeline terminated — A3 said NO_GO."""
    state["status"] = PipelineStatus.NO_GO.value
    logger.info("Pipeline terminated: NO_GO")
    return state


def end_legal_block(state: dict[str, Any]) -> dict[str, Any]:
    """Pipeline terminated — E2 Legal issued a BLOCK."""
    state["status"] = PipelineStatus.LEGAL_BLOCK.value
    logger.info("Pipeline terminated: LEGAL_BLOCK")
    return state


def end_rejected(state: dict[str, Any]) -> dict[str, Any]:
    """Pipeline terminated — human approval REJECTED."""
    state["status"] = PipelineStatus.REJECTED.value
    logger.info("Pipeline terminated: REJECTED")
    return state


def escalate_structuring(state: dict[str, Any]) -> dict[str, Any]:
    """A2 failed to reach acceptable confidence — needs human review."""
    state["status"] = PipelineStatus.ESCALATED.value
    state["error_message"] = "Structuring confidence too low after max retries"
    logger.warning("Escalated: Structuring confidence too low")
    return state


def escalate_validation(state: dict[str, Any]) -> dict[str, Any]:
    """D1 rejected too many times — needs human review."""
    state["status"] = PipelineStatus.ESCALATED.value
    state["error_message"] = "Technical validation failed after max retries"
    logger.warning("Escalated: Validation retries exhausted")
    return state


# ── Commercial + Legal parallel fan-out / fan-in ─────────

def commercial_legal_parallel(state: dict[str, Any]) -> dict[str, Any]:
    """
    Run E1 (Commercial) and E2 (Legal) and combine results.
    
    NOTE: True LangGraph fan-out requires specific graph patterns.
    For the mock scaffold we run them sequentially and combine.
    When moving to production, refactor using LangGraph's 
    Send() / fan-out API.
    """
    logger.info("Running E1 Commercial + E2 Legal (sequential mock of parallel)")

    state = _e1.process(state)
    state = _e2.process(state)

    # ── Fan-in gate: combine E1 + E2 ────────────────────
    legal_decision = state.get("legal_result", {}).get("decision", "APPROVED")
    legal_blocks = state.get("legal_result", {}).get("block_reasons", [])

    if legal_decision == "BLOCKED":
        gate_decision = CommercialLegalGateDecision.BLOCK.value
    else:
        gate_decision = CommercialLegalGateDecision.CLEAR.value

    state["commercial_legal_gate"] = {
        "gate_decision": gate_decision,
        "commercial": state.get("commercial_result", {}),
        "legal": state.get("legal_result", {}),
    }

    return state


# ── Build the graph ──────────────────────────────────────

def build_graph() -> StateGraph:
    """
    Construct and compile the 12-stage LangGraph state machine.
    Returns a compiled graph ready to invoke.
    """

    graph = StateGraph(dict)

    # ── Add nodes ────────────────────────────────────────
    graph.add_node("a1_intake", _a1.process)
    graph.add_node("a2_structuring", _a2.process)
    graph.add_node("a3_go_no_go", _a3.process)
    graph.add_node("b1_requirements_extraction", _b1.process)
    graph.add_node("b2_requirements_validation", _b2.process)
    graph.add_node("c1_architecture_planning", _c1.process)
    graph.add_node("c2_requirement_writing", _c2.process)
    graph.add_node("c3_narrative_assembly", _c3.process)
    graph.add_node("d1_technical_validation", _d1.process)
    graph.add_node("commercial_legal_parallel", commercial_legal_parallel)
    graph.add_node("f1_final_readiness", _f1.process)
    graph.add_node("f2_submission", _f2.process)

    # Terminal nodes
    graph.add_node("end_no_go", end_no_go)
    graph.add_node("end_legal_block", end_legal_block)
    graph.add_node("end_rejected", end_rejected)
    graph.add_node("escalate_structuring", escalate_structuring)
    graph.add_node("escalate_validation", escalate_validation)

    # ── Set entry point ──────────────────────────────────
    graph.set_entry_point("a1_intake")

    # ── Add edges ────────────────────────────────────────

    # A1 → A2 (always)
    graph.add_edge("a1_intake", "a2_structuring")

    # A2 → conditional (confidence check)
    graph.add_conditional_edges(
        "a2_structuring",
        route_after_structuring,
        {
            "a2_structuring": "a2_structuring",     # retry
            "a3_go_no_go": "a3_go_no_go",           # proceed
            "escalate_structuring": "escalate_structuring",
        },
    )

    # A3 → conditional (GO / NO_GO)
    graph.add_conditional_edges(
        "a3_go_no_go",
        route_after_go_no_go,
        {
            "b1_requirements_extraction": "b1_requirements_extraction",
            "end_no_go": "end_no_go",
        },
    )

    # B1 → B2 → C1 → C2 → C3 (linear)
    graph.add_edge("b1_requirements_extraction", "b2_requirements_validation")
    graph.add_edge("b2_requirements_validation", "c1_architecture_planning")
    graph.add_edge("c1_architecture_planning", "c2_requirement_writing")
    graph.add_edge("c2_requirement_writing", "c3_narrative_assembly")

    # C3 → D1 (always)
    graph.add_edge("c3_narrative_assembly", "d1_technical_validation")

    # D1 → conditional (PASS / REJECT / escalate)
    graph.add_conditional_edges(
        "d1_technical_validation",
        route_after_validation,
        {
            "c3_narrative_assembly": "c3_narrative_assembly",  # retry loop
            "commercial_legal_parallel": "commercial_legal_parallel",
            "escalate_validation": "escalate_validation",
        },
    )

    # E1+E2 combined → conditional (CLEAR / BLOCK)
    graph.add_conditional_edges(
        "commercial_legal_parallel",
        route_after_commercial_legal,
        {
            "f1_final_readiness": "f1_final_readiness",
            "end_legal_block": "end_legal_block",
        },
    )

    # F1 → conditional (APPROVE / REJECT)
    graph.add_conditional_edges(
        "f1_final_readiness",
        route_after_approval,
        {
            "f2_submission": "f2_submission",
            "end_rejected": "end_rejected",
        },
    )

    # Terminal edges → END
    graph.add_edge("f2_submission", END)
    graph.add_edge("end_no_go", END)
    graph.add_edge("end_legal_block", END)
    graph.add_edge("end_rejected", END)
    graph.add_edge("escalate_structuring", END)
    graph.add_edge("escalate_validation", END)

    return graph.compile()


# ── Convenience runner ───────────────────────────────────

def run_pipeline(
    uploaded_file_path: str = "",
    initial_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build the graph and run it end-to-end.
    Returns the final state dict.
    """
    compiled = build_graph()

    state = initial_state or {}
    state.setdefault("uploaded_file_path", uploaded_file_path)
    state.setdefault("status", PipelineStatus.RECEIVED.value)

    logger.info("═" * 60)
    logger.info("  RFP PIPELINE STARTING")
    logger.info("═" * 60)

    final_state = compiled.invoke(state)

    logger.info("═" * 60)
    logger.info(f"  PIPELINE FINISHED — status: {final_state.get('status')}")
    logger.info("═" * 60)

    return final_state
