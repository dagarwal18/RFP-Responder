"""
LangGraph State Machine — 12-stage RFP response pipeline.

This module defines the full graph: nodes, edges, conditional routing,
and the parallel fan-out/fan-in for E1+E2.

All nodes delegate to agent.process(state), which returns an updated
state dict that LangGraph merges automatically.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from rfp_automation.persistence.checkpoint import save_checkpoint, start_log_capture, stop_log_capture

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
    HumanValidationAgent,
    FinalReadinessAgent,
)
from rfp_automation.orchestration.transitions import (
    route_after_structuring,
    route_after_go_no_go,
    route_after_validation,
    route_after_commercial_legal,
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
_h1 = HumanValidationAgent()
_f1 = FinalReadinessAgent()


def _with_checkpoint(node_name: str, fn: Callable) -> Callable:
    """Wrap an agent process function with checkpoint-after-completion.

    Also handles the 'skip before' logic for reruns: if the state
    contains '_rerun_start_from', agents before that point return
    the state unchanged (instant pass-through).

    Tracks per-agent LLM call count and timing via LLMCallTracker.
    """
    def wrapper(state: dict[str, Any]) -> dict[str, Any]:
        from rfp_automation.persistence.checkpoint import AGENT_ORDER
        from rfp_automation.services.llm_service import LLMCallTracker

        # ── Skip logic for reruns ─────────────────────
        start_from = state.get("_rerun_start_from")
        if start_from and node_name in AGENT_ORDER and start_from in AGENT_ORDER:
            my_idx = AGENT_ORDER.index(node_name)
            start_idx = AGENT_ORDER.index(start_from)
            if my_idx < start_idx:
                logger.info(f"⏭ [{node_name}] Skipped (rerun starts from {start_from})")
                return state  # pass through unchanged

        # ── Track LLM calls for this agent ────────────
        tracker = LLMCallTracker.get()
        tracker.set_context(node_name)

        # ── Normal execution ──────────────────────────
        result = fn(state)

        # ── Finish tracking ───────────────────────────
        tracker.finish_context(node_name)

        # Extract rfp_id from state for checkpoint filename
        rfp_id = (
            result.get("tracking_rfp_id", "")
            or (result.get("rfp_metadata", {}) or {}).get("rfp_id", "")
            or "unknown"
        )
        try:
            save_checkpoint(rfp_id, node_name, result)
        except Exception as exc:
            logger.warning(f"Checkpoint save failed for {node_name}: {exc}")
        return result
    wrapper.__name__ = fn.__name__  # preserve name for LangGraph
    return wrapper


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

    # Extract rfp_id for checkpoint saving
    rfp_id = (
        state.get("tracking_rfp_id", "")
        or (state.get("rfp_metadata", {}) or {}).get("rfp_id", "")
        or "unknown"
    )

    state = _e1.process(state)
    # Save E1 checkpoint individually
    try:
        save_checkpoint(rfp_id, "e1_commercial", state)
    except Exception as exc:
        logger.warning(f"Checkpoint save failed for e1_commercial: {exc}")

    state = _e2.process(state)
    # Save E2 checkpoint individually
    try:
        save_checkpoint(rfp_id, "e2_legal", state)
    except Exception as exc:
        logger.warning(f"Checkpoint save failed for e2_legal: {exc}")

    # ── Inject E1/E2 content into the assembled proposal narrative ──
    # This must happen BEFORE H1 so human reviewers see commercial/legal content
    import re as _re

    assembled = state.get("assembled_proposal", {})
    full_narr = (
        assembled.get("full_narrative", "")
        if isinstance(assembled, dict)
        else getattr(assembled, "full_narrative", "")
    )

    if full_narr:
        commercial_result = state.get("commercial_result", {})
        legal_result = state.get("legal_result", {})

        # -- Extract commercial fields --
        def _get(obj, key, default=""):
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        comm_narrative = _get(commercial_result, "commercial_narrative", "")
        line_items = _get(commercial_result, "line_items", [])
        currency = _get(commercial_result, "currency", "INR")
        total_price = _get(commercial_result, "total_price", 0)

        pricing_table = ""
        if line_items:
            pricing_table = (
                "\n\n### Pricing Line Items\n\n"
                "| Category | Label | Quantity | Unit Rate | Total |\n"
                "|---|---|---|---|---|\n"
            )
            for item in line_items:
                ur = f"{currency} {_get(item, 'unit_rate', 0):,.2f}"
                tot = f"{currency} {_get(item, 'total', 0):,.2f}"
                pricing_table += (
                    f"| {_get(item, 'category', '')} "
                    f"| {_get(item, 'label', '')} "
                    f"| {_get(item, 'quantity', '')} {_get(item, 'unit', '')} "
                    f"| {ur} | {tot} |\n"
                )
            pricing_table += f"**Total Expected Price:** {currency} {total_price:,.2f}\n"

        # -- Extract legal fields --
        legal_narrative = (
            _get(legal_result, "legal_narrative", "")
            or _get(legal_result, "risk_register_summary", "")
        )
        clause_risks = _get(legal_result, "clause_risks", [])
        legal_table = ""
        if clause_risks:
            legal_table = "\n\n### Legal & Compliance Exceptions\n\n"
            for risk in clause_risks:
                rl = _get(_get(risk, "risk_level", "low"), "name", None) or _get(risk, "risk_level", "LOW")
                legal_table += (
                    f"- **Clause {_get(risk, 'clause_id', '?')} ({rl})**: "
                    f"{_get(risk, 'concern', '')}\n"
                    f"   *Recommendation*: {_get(risk, 'recommendation', '')}\n"
                )

        def _stub_replacer(match):
            title = match.group(1).lower()
            if "commercial" in title or "pricing" in title:
                return f"\n{(comm_narrative or '').strip()}\n{pricing_table}\n"
            elif "legal" in title or "contract" in title:
                return f"\n{(legal_narrative or '').strip()}\n{legal_table}\n"
            return match.group(0)

        # Replace [PIPELINE_STUB: ...] markers
        updated_narr = _re.sub(
            r">\s*\*\*Note:\*\*\s*\[PIPELINE_STUB:\s*(.*?)\]",
            _stub_replacer, full_narr,
        )

        # Also replace the raw C2 stub text "[COMMERCIAL — content generated by ...]"
        def _raw_stub_replacer(match):
            marker = match.group(0).lower()
            if "commercial" in marker or "pricing" in marker:
                return f"\n{(comm_narrative or '').strip()}\n{pricing_table}\n"
            elif "legal" in marker or "contract" in marker:
                return f"\n{(legal_narrative or '').strip()}\n{legal_table}\n"
            return match.group(0)

        updated_narr = _re.sub(
            r"\[(?:COMMERCIAL|LEGAL|PRICING)\s*[—–\-]\s*content generated by dedicated agent\]",
            _raw_stub_replacer, updated_narr, flags=_re.IGNORECASE,
        )

        # Also replace raw C2 PIPELINE_STUB markers: *[PIPELINE_STUB: Title]*
        updated_narr = _re.sub(
            r"\*?\[PIPELINE_STUB:\s*(.*?)\]\*?",
            _stub_replacer, updated_narr,
        )

        # Update the assembled_proposal in state
        if isinstance(assembled, dict):
            assembled["full_narrative"] = updated_narr
            state["assembled_proposal"] = assembled
        else:
            assembled.full_narrative = updated_narr
            state["assembled_proposal"] = assembled

        logger.info("[E-GATE] Injected E1/E2 content into assembled proposal narrative")

    # ── Fan-in gate: combine E1 + E2 ────────────────────
    commercial = state.get("commercial_result", {})
    legal = state.get("legal_result", {})

    legal_decision = legal.get("decision", "APPROVED")
    commercial_decision = commercial.get("decision", "APPROVED")

    # E2 BLOCKED always overrides → pipeline ends
    if legal_decision == "BLOCKED":
        gate_decision = CommercialLegalGateDecision.BLOCK.value
        logger.warning(
            f"[GATE] E2 Legal BLOCKED — reasons: "
            f"{legal.get('block_reasons', [])}"
        )
    else:
        gate_decision = CommercialLegalGateDecision.CLEAR.value

    # Log E1 flags (informational, never blocks)
    if commercial_decision == "FLAGGED":
        logger.warning(
            f"[GATE] E1 Commercial FLAGGED — flags: "
            f"{commercial.get('validation_flags', [])}"
        )

    state["commercial_legal_gate"] = {
        "gate_decision": gate_decision,
        "commercial": commercial,
        "legal": legal,
    }

    return state



# ── Build the graph ──────────────────────────────────────

def build_graph(entry_point: str = "a1_intake") -> StateGraph:
    """
    Construct and compile the 12-stage LangGraph state machine.
    Returns a compiled graph ready to invoke.
    """

    graph = StateGraph(dict)

    # ── Add nodes ────────────────────────────────────────
    graph.add_node("a1_intake", _with_checkpoint("a1_intake", _a1.process))
    graph.add_node("a2_structuring", _with_checkpoint("a2_structuring", _a2.process))
    graph.add_node("a3_go_no_go", _with_checkpoint("a3_go_no_go", _a3.process))
    graph.add_node("b1_requirements_extraction", _with_checkpoint("b1_requirements_extraction", _b1.process))
    graph.add_node("b2_requirements_validation", _with_checkpoint("b2_requirements_validation", _b2.process))
    graph.add_node("c1_architecture_planning", _with_checkpoint("c1_architecture_planning", _c1.process))
    graph.add_node("c2_requirement_writing", _with_checkpoint("c2_requirement_writing", _c2.process))
    graph.add_node("c3_narrative_assembly", _with_checkpoint("c3_narrative_assembly", _c3.process))
    graph.add_node("d1_technical_validation", _with_checkpoint("d1_technical_validation", _d1.process))
    graph.add_node("commercial_legal_parallel", _with_checkpoint("commercial_legal_parallel", commercial_legal_parallel))
    graph.add_node("h1_human_validation_prepare", _with_checkpoint("h1_human_validation_prepare", _h1.process))
    graph.add_node("f1_final_readiness", _with_checkpoint("f1_final_readiness", _f1.process))


    # Terminal nodes
    graph.add_node("end_no_go", end_no_go)
    graph.add_node("end_legal_block", end_legal_block)

    graph.add_node("escalate_structuring", escalate_structuring)
    graph.add_node("escalate_validation", escalate_validation)

    # ── Set entry point ──────────────────────────────────
    graph.set_entry_point(entry_point)

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
            "c2_requirement_writing": "c2_requirement_writing",  # retry loop
            "commercial_legal_parallel": "commercial_legal_parallel",
            "escalate_validation": "escalate_validation",
        },
    )

    # E1+E2 combined → conditional (CLEAR / BLOCK)
    graph.add_conditional_edges(
        "commercial_legal_parallel",
        route_after_commercial_legal,
        {
            "h1_human_validation_prepare": "h1_human_validation_prepare",
            "end_legal_block": "end_legal_block",
        },
    )

    # H1 -> END (resume via API once a human decision is recorded)
    graph.add_edge("h1_human_validation_prepare", END)

    # F1 → END (F1 handles approval/rejection internally)
    graph.add_edge("f1_final_readiness", END)

    # Terminal edges → END

    graph.add_edge("end_no_go", END)
    graph.add_edge("end_legal_block", END)

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

    If an agent raises, the exception is re-raised with a
    ``partial_state`` attribute containing the last known-good
    state so callers can still inspect completed agent outputs.
    """
    compiled = build_graph()

    state = initial_state or {}
    state.setdefault("uploaded_file_path", uploaded_file_path)
    state.setdefault("status", PipelineStatus.RECEIVED.value)

    # ── Start error/warning log capture ───────────────────
    rfp_id = state.get("tracking_rfp_id") or "unknown"
    start_log_capture(rfp_id)

    logger.info("═" * 60)
    logger.info("  RFP PIPELINE STARTING")
    logger.info("═" * 60)

    # Stream node-by-node so we can capture partial state on error
    last_state: dict[str, Any] = state
    try:
        for step_output in compiled.stream(state):
            # Each step_output is {node_name: updated_state_dict}
            for _node_name, node_state in step_output.items():
                if isinstance(node_state, dict):
                    last_state = node_state
                    # Update rfp_id if discovered during pipeline
                    if rfp_id == "unknown":
                        discovered = (
                            node_state.get("tracking_rfp_id", "")
                            or (node_state.get("rfp_metadata", {}) or {}).get("rfp_id", "")
                        )
                        if discovered:
                            rfp_id = discovered
    except Exception as exc:
        logger.error(f"Pipeline failed at stream step: {exc}")
        # Attach partial state to the exception for the caller
        exc.partial_state = last_state  # type: ignore[attr-defined]
        stop_log_capture()
        raise

    logger.info("═" * 60)
    logger.info(f"  PIPELINE FINISHED — status: {last_state.get('status')}")
    logger.info("═" * 60)

    # ── Flush error/warning log to file ───────────────────
    stop_log_capture()

    return last_state


def run_pipeline_from(
    start_from: str,
    checkpoint_state: dict[str, Any],
) -> dict[str, Any]:
    """
    Run the pipeline starting from a specific agent using cached state.

    Injects `_rerun_start_from` into the state so that the
    `_with_checkpoint` wrapper skips agents before `start_from`.
    """
    from rfp_automation.persistence.checkpoint import AGENT_ORDER

    if start_from not in AGENT_ORDER:
        raise ValueError(
            f"Unknown agent '{start_from}'. Valid: {AGENT_ORDER}"
        )

    compiled = build_graph(entry_point=start_from)

    # Mark which agent to start from (agents before this will be skipped)
    checkpoint_state["_rerun_start_from"] = start_from

    # Remove checkpoint metadata keys that aren't part of the graph state
    checkpoint_state.pop("_checkpoint", None)

    # ── Start error/warning log capture ───────────────────
    rfp_id = (
        checkpoint_state.get("tracking_rfp_id", "")
        or (checkpoint_state.get("rfp_metadata", {}) or {}).get("rfp_id", "")
        or "unknown"
    )
    start_log_capture(rfp_id)

    logger.info("═" * 60)
    logger.info(f"  RFP PIPELINE RE-RUNNING FROM: {start_from}")
    logger.info("═" * 60)

    # Stream from checkpoint state
    last_state: dict[str, Any] = checkpoint_state
    try:
        for step_output in compiled.stream(checkpoint_state):
            for _node_name, node_state in step_output.items():
                if isinstance(node_state, dict):
                    last_state = node_state
    except Exception as exc:
        logger.error(f"Pipeline failed at stream step: {exc}")
        exc.partial_state = last_state  # type: ignore[attr-defined]
        stop_log_capture()
        raise

    logger.info("═" * 60)
    logger.info(f"  PIPELINE FINISHED — status: {last_state.get('status')}")
    logger.info("═" * 60)

    # ── Flush error/warning log to file ───────────────────
    stop_log_capture()

    return last_state

