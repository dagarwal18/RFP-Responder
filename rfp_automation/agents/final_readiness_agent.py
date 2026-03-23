"""
F1 - Final Readiness & Submission Agent.

Builds an approval package from the assembled proposal, commercial/legal
reviews, and the recorded human validation decision.  When approved,
generates the final proposal markdown, hashes it, and archives the
submission record.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

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

            proposal_markdown = self._build_markdown(state, submitted_at.isoformat())

            # Save pre-render artifact for debugging
            raw_path = out_dir / "proposal_raw.md"
            raw_path.write_text(proposal_markdown, encoding="utf-8")
            logger.info(f"[F1] Saved raw markdown: {raw_path}")

            # Process Mermaid diagrams (render to PNG, rewrite markdown)
            try:
                from rfp_automation.utils.mermaid_utils import process_mermaid_blocks
                diagrams_dir = out_dir / "diagrams"
                proposal_markdown = process_mermaid_blocks(proposal_markdown, diagrams_dir)
            except Exception as e:
                logger.warning(f"[F1] Mermaid processing failed (non-fatal): {e}")

            output_path = out_dir / "proposal.md"
            output_path.write_text(proposal_markdown, encoding="utf-8")

            # Automatically convert to PDF using the md_to_pdf script
            pdf_path = out_dir / "proposal.pdf"
            try:
                import subprocess
                import sys
                client_name = state.rfp_metadata.client_name or "Client"
                rfp_title = state.rfp_metadata.rfp_title or "RFP Response Proposal"
                # Sanitize rfp_title: remove newlines and cap length
                # (RFP titles from parsed docs may contain line breaks, and pipes break Windows subshells)
                rfp_title = " - ".join(
                    line.strip() for line in rfp_title.splitlines() if line.strip()
                )[:120]
                # Assuming the proposing company might be available or default to "Our Company"
                # (For now we'll use a generic "Proposing Company" default if not defined)
                subprocess.run(
                    [
                        sys.executable, "scripts/md_to_pdf.py", 
                        str(output_path), str(pdf_path),
                        "--rfp-title", rfp_title,
                        "--client-name", client_name
                    ],
                    check=True,
                    capture_output=True,
                    text=True
                )
                logger.info(f"[F1] Generated PDF: {pdf_path}")
            except subprocess.CalledProcessError as e:
                logger.warning(f"[F1] Failed to generate PDF. Exit code: {e.returncode}")
                logger.warning(f"[F1] PDF stdout: {e.stdout}")
                logger.warning(f"[F1] PDF stderr: {e.stderr}")
            except Exception as e:
                logger.warning(f"[F1] Failed to generate PDF: {e}")

            file_hash = hashlib.sha256(proposal_markdown.encode("utf-8")).hexdigest()
            state.submission_record = SubmissionRecord(
                submitted_at=submitted_at,
                output_file_path=str(output_path),
                archive_path=str(output_path),  # or pdf_path if we want to track that
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

        # Perform placeholder replacement on the narrative body itself
        full_narr = state.assembled_proposal.full_narrative or "No proposal narrative available."
        import re
        
        # Build HTML Table for Pricing to enforce proper PDF column widths
        pricing_table = "\n\n### Pricing Line Items\n\n<table style='width:100%;'>\n"
        pricing_table += "<thead><tr><th style='width:15%; text-align:left;'>Category</th><th style='width:35%; text-align:left;'>Label</th><th style='width:20%; text-align:left;'>Quantity</th><th style='width:15%; text-align:left;'>Unit Rate</th><th style='width:15%; text-align:left;'>Total</th></tr></thead>\n<tbody>\n"
        for item in commercial.line_items:
            unit_rate = f"{commercial.currency} {getattr(item, 'unit_rate', 0):,.2f}"
            total = f"{commercial.currency} {getattr(item, 'total', 0):,.2f}"
            pricing_table += f"<tr><td>{getattr(item, 'category', '')}</td><td>{getattr(item, 'label', '')}</td><td>{getattr(item, 'quantity', '')} {getattr(item, 'unit', '')}</td><td>{unit_rate}</td><td>{total}</td></tr>\n"
        pricing_table += "</tbody></table>\n\n"
        pricing_table += f"**Total Expected Price:** {commercial.currency} {commercial.total_price:,.2f}\n"

        # Build Markdown List for Legal Risks
        legal_table = "\n\n### Legal & Compliance Exceptions\n\n"
        for risk in legal.clause_risks:
            risk_level = getattr(getattr(risk, "risk_level", "low"), "name", "LOW")
            legal_table += f"- **Clause {getattr(risk, 'clause_id', '?')} ({risk_level})**: {getattr(risk, 'concern', '')}\n"
            legal_table += f"   *Recommendation*: {getattr(risk, 'recommendation', '')}\n"

        def _stub_replacer(match):
            title = match.group(1).lower()
            if "commercial" in title or "pricing" in title:
                return f"\n{(commercial.commercial_narrative or '').strip()}\n{pricing_table}\n"
            elif "legal" in title or "contract" in title:
                legal_content = (legal.legal_narrative or legal.risk_register_summary or '').strip()
                return f"\n{legal_content}\n{legal_table}\n"
            return match.group(0)

        full_narr = re.sub(r">\s*\*\*Note:\*\*\s*\[PIPELINE_STUB:\s*(.*?)\]", _stub_replacer, full_narr)

        # Fallback: replace raw C2 "[COMMERCIAL — content generated by dedicated agent]" stubs
        def _raw_stub_fallback(match):
            marker = match.group(0).lower()
            if "commercial" in marker or "pricing" in marker:
                return f"\n{(commercial.commercial_narrative or '').strip()}\n{pricing_table}\n"
            elif "legal" in marker or "contract" in marker:
                legal_content = (legal.legal_narrative or legal.risk_register_summary or '').strip()
                return f"\n{legal_content}\n{legal_table}\n"
            return match.group(0)

        full_narr = re.sub(
            r"\[(?:COMMERCIAL|LEGAL|PRICING)\s*[—–\-]\s*content generated by dedicated agent\]",
            _raw_stub_fallback, full_narr, flags=re.IGNORECASE,
        )

        # Also replace raw C2 PIPELINE_STUB markers: *[PIPELINE_STUB: Title]*
        full_narr = re.sub(
            r"\*?\[PIPELINE_STUB:\s*(.*?)\]\*?",
            _stub_replacer, full_narr,
        )

        # Commercial/Legal content is now part of full_narr (injected by
        # commercial_legal_parallel before H1). We keep only the proposal
        # body and human validation sections to avoid duplication.
        sections = [
            f"# {meta.rfp_title or 'Proposal Submission'}",
            "",
            f"- RFP ID: {meta.rfp_id or 'N/A'}",
            f"- Client: {meta.client_name or 'N/A'}",
            f"- Submitted At: {submitted_at}",
            "",
            full_narr,
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

        # Coverage appendix is already part of full_narrative from C3.
        # Not duplicated here.

        return "\n".join(sections).strip() + "\n"

