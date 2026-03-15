"""
F1 - Final Readiness Agent.

Builds an approval package from the assembled proposal, commercial/legal
reviews, and the recorded human validation decision.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import (
    AgentName,
    ApprovalDecision,
    HumanValidationDecision,
    PipelineStatus,
)
from rfp_automation.models.schemas import ApprovalPackage
from rfp_automation.models.state import RFPGraphState
from rfp_automation.services.review_service import ReviewService


class FinalReadinessAgent(BaseAgent):
    name = AgentName.F1_FINAL_READINESS

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        review_package = ReviewService.normalize_package(state.review_package)
        human_decision = review_package.decision.decision

        if human_decision is None:
            raise ValueError("Human validation decision is required before final readiness")
        if human_decision == HumanValidationDecision.REQUEST_CHANGES:
            raise ValueError("Cannot enter final readiness while changes are still requested")

        approval_decision = (
            ApprovalDecision.APPROVE
            if human_decision == HumanValidationDecision.APPROVE
            else ApprovalDecision.REJECT
        )

        proposal_summary = (
            state.assembled_proposal.executive_summary
            or (state.assembled_proposal.full_narrative or "")[:2000]
        ).strip()

        pricing_summary = (
            f"{state.commercial_result.currency} {state.commercial_result.total_price:,.2f} "
            f"across {len(state.commercial_result.line_items)} line items."
        )
        if state.commercial_result.validation_flags:
            pricing_summary += (
                " Flags: "
                + ", ".join(state.commercial_result.validation_flags[:6])
            )

        risk_parts = []
        if state.technical_validation.feedback_for_revision:
            risk_parts.append(
                "Technical validation feedback remains on record for traceability."
            )
        if state.legal_result.block_reasons:
            risk_parts.append(
                "Legal blockers: " + ", ".join(state.legal_result.block_reasons[:6])
            )
        elif state.legal_result.risk_register_summary:
            risk_parts.append(state.legal_result.risk_register_summary[:1200])
        risk_summary = " ".join(part.strip() for part in risk_parts if part.strip())

        coverage_summary = (
            state.assembled_proposal.coverage_appendix[:2000]
            if state.assembled_proposal.coverage_appendix
            else "Coverage appendix not available."
        )

        reviewer = (review_package.decision.reviewer or "Unknown reviewer").strip()
        reviewer_summary = (review_package.decision.summary or "").strip()
        decision_brief = (
            f"Human validation decision: {human_decision.value}. "
            f"Reviewer: {reviewer}. "
            f"Open comments at decision time: {review_package.open_comment_count}."
        )
        if reviewer_summary:
            decision_brief += f" Summary: {reviewer_summary}"

        state.approval_package = ApprovalPackage(
            decision_brief=decision_brief.strip(),
            proposal_summary=proposal_summary,
            pricing_summary=pricing_summary.strip(),
            risk_summary=risk_summary.strip(),
            coverage_summary=coverage_summary.strip(),
            approval_decision=approval_decision,
            approver_notes=reviewer_summary,
        )

        state.status = (
            PipelineStatus.SUBMITTING
            if approval_decision == ApprovalDecision.APPROVE
            else PipelineStatus.REJECTED
        )
        return state
