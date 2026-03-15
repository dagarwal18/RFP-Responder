"""
F2 - Submission and archive agent.

Packages the final proposal into a markdown artifact and records a simple
submission archive for auditability.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, ApprovalDecision, PipelineStatus
from rfp_automation.models.schemas import SubmissionRecord
from rfp_automation.models.state import RFPGraphState


class SubmissionAgent(BaseAgent):
    name = AgentName.F2_SUBMISSION

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        if state.approval_package.approval_decision != ApprovalDecision.APPROVE:
            raise ValueError("Submission requires an approved final readiness package")

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
