"""
F1 - Final Readiness & Submission Agent.

Builds an approval package from the assembled proposal, commercial/legal
reviews, and the recorded human validation decision.  When approved,
generates the final proposal markdown, hashes it, and archives the
submission record.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import (
    AgentName,
    ApprovalDecision,
    HumanValidationDecision,
    PipelineStatus,
)
from rfp_automation.models.schemas import ApprovalPackage, SubmissionRecord
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

        # ── Submission (formerly F2) ─────────────────────────
        if approval_decision == ApprovalDecision.APPROVE:
            rfp_id = state.rfp_metadata.rfp_id or state.tracking_rfp_id or "unknown-rfp"
            out_dir = Path("storage") / "submissions" / rfp_id
            out_dir.mkdir(parents=True, exist_ok=True)

            submitted_at = datetime.now(timezone.utc)
            output_path = out_dir / "proposal.md"

            proposal_markdown = self._build_markdown(state, submitted_at.isoformat())
            output_path.write_text(proposal_markdown, encoding="utf-8")

            file_hash = hashlib.sha256(proposal_markdown.encode("utf-8")).hexdigest()
            state.submission_record = SubmissionRecord(
                submitted_at=submitted_at,
                output_file_path=str(output_path),
                archive_path=str(output_path),
                file_hash=file_hash,
            )
            state.status = PipelineStatus.SUBMITTED
        else:
            state.status = PipelineStatus.REJECTED

        return state

    @staticmethod
    def _build_markdown(state: RFPGraphState, submitted_at: str) -> str:
        meta = state.rfp_metadata
        commercial = state.commercial_result
        legal = state.legal_result
        approval = state.approval_package
        review = state.review_package

        sections = [
            f"# {meta.rfp_title or 'Proposal Submission'}",
            "",
            f"- RFP ID: {meta.rfp_id or 'N/A'}",
            f"- Client: {meta.client_name or 'N/A'}",
            f"- Submitted At: {submitted_at}",
            "",
            "## Executive Summary",
            "",
            state.assembled_proposal.executive_summary or "No executive summary available.",
            "",
            "## Full Narrative",
            "",
            state.assembled_proposal.full_narrative or "No proposal narrative available.",
            "",
            "## Commercial Summary",
            "",
            approval.pricing_summary
            or f"{commercial.currency} {commercial.total_price:,.2f}",
            "",
            "## Legal Summary",
            "",
            approval.risk_summary
            or legal.risk_register_summary
            or "No legal summary available.",
            "",
            "## Human Validation",
            "",
            approval.decision_brief or "No human validation brief available.",
        ]

        if review.comments:
            sections.extend(
                [
                    "",
                    "## Review Comments",
                    "",
                ]
            )
            for comment in review.comments:
                location = comment.anchor.section_title or comment.anchor.section_id or "General"
                if comment.anchor.paragraph_id:
                    location += f" / {comment.anchor.paragraph_id}"
                sections.append(f"- [{comment.anchor.domain}] {location}: {comment.comment}")

        if state.assembled_proposal.coverage_appendix:
            sections.extend(
                [
                    "",
                    "## Coverage Appendix",
                    "",
                    state.assembled_proposal.coverage_appendix,
                ]
            )

        return "\n".join(sections).strip() + "\n"
