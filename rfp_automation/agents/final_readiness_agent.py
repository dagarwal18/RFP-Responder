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
            pdf_generated = False
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
                pdf_generated = True
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
                archive_path=str(pdf_path if pdf_generated else output_path),
                file_hash=file_hash,
            )
            if pdf_generated:
                state.status = PipelineStatus.SUBMITTED
            else:
                state.error_message = "PDF generation failed during final readiness."
                state.status = PipelineStatus.FAILED
        else:
            state.status = PipelineStatus.REJECTED

        return state

    @staticmethod
    def _build_markdown(state: RFPGraphState, submitted_at: str) -> str:
        meta = state.rfp_metadata
        commercial = state.commercial_result
        legal = state.legal_result

        full_narr = state.assembled_proposal.full_narrative or "No proposal narrative available."
        import re

        def _stub_replacer(match):
            title = match.group(1).lower()
            if "commercial" in title or "pricing" in title:
                return f"\n{(commercial.commercial_narrative or '').strip()}\n"
            elif "legal" in title or "contract" in title:
                legal_content = (legal.legal_narrative or legal.risk_register_summary or '').strip()
                return f"\n{legal_content}\n"
            return match.group(0)

        full_narr = re.sub(r">\s*\*\*Note:\*\*\s*\[PIPELINE_STUB:\s*(.*?)\]", _stub_replacer, full_narr)

        # Fallback: replace raw C2 "[COMMERCIAL — content generated by dedicated agent]" stubs
        def _raw_stub_fallback(match):
            marker = match.group(0).lower()
            if "commercial" in marker or "pricing" in marker:
                return f"\n{(commercial.commercial_narrative or '').strip()}\n"
            elif "legal" in marker or "contract" in marker:
                legal_content = (legal.legal_narrative or legal.risk_register_summary or '').strip()
                return f"\n{legal_content}\n"
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

        # Proposal artifacts should contain only the proposal body.
        full_narr = FinalReadinessAgent._cleanup_full_narrative(full_narr)
        return full_narr.strip() + "\n"

    @staticmethod
    def _cleanup_full_narrative(full_narr: str) -> str:
        full_narr = FinalReadinessAgent._collapse_technical_parent_sections(full_narr)
        full_narr = FinalReadinessAgent._strip_invalid_mermaid_blocks(full_narr)
        full_narr = FinalReadinessAgent._canonicalize_known_table_sections(full_narr)
        full_narr = ReviewService._sanitize_response_text(full_narr)
        full_narr = FinalReadinessAgent._ensure_heading_spacing(full_narr)
        return full_narr

    @staticmethod
    def _ensure_heading_spacing(full_narr: str) -> str:
        """Insert blank lines before headings that follow tables or code fences."""
        lines = full_narr.splitlines()
        rewritten: list[str] = []

        for line in lines:
            stripped = line.strip()
            is_heading = stripped.startswith("#")
            prev_line = rewritten[-1].strip() if rewritten else ""
            prev_is_table = "|" in prev_line and prev_line.count("|") >= 2
            prev_is_fence = prev_line == "```"

            if is_heading and rewritten and rewritten[-1] != "" and (prev_is_table or prev_is_fence):
                rewritten.append("")

            rewritten.append(line)

        return "\n".join(rewritten).strip()

    @staticmethod
    def _collapse_technical_parent_sections(full_narr: str) -> str:
        import re

        framework_heading = "## Technical Implementation Framework"
        parent_heading = "## Technical Implementation"

        framework_idx = full_narr.find(framework_heading)
        if framework_idx < 0:
            return full_narr

        rewritten = full_narr.replace(
            framework_heading,
            "## Technical Implementation\n\n### Framework",
            1,
        )
        rewritten = re.sub(
            r"(?m)^(\d+\.\s+)Technical Implementation Framework$",
            r"\1Technical Implementation",
            rewritten,
        )

        heading_matches = list(re.finditer(r"(?m)^## Technical Implementation\s*$", rewritten))
        for match in reversed(heading_matches[1:]):
            line_end = rewritten.find("\n", match.start())
            if line_end < 0:
                line_end = len(rewritten)
            rewritten = rewritten[:match.start()].rstrip() + "\n\n" + rewritten[line_end:].lstrip()
        return rewritten

    @staticmethod
    def _strip_invalid_mermaid_blocks(full_narr: str) -> str:
        from rfp_automation.utils.mermaid_utils import (
            extract_mermaid_blocks,
            _validate_mermaid_syntax,
        )

        rewritten = full_narr
        for block in reversed(extract_mermaid_blocks(full_narr)):
            if _validate_mermaid_syntax(block.code) is None:
                continue
            rewritten = rewritten.replace(block.raw_match, "", 1)
        return rewritten

    @staticmethod
    def _canonicalize_known_table_sections(full_narr: str) -> str:
        rewritten = full_narr
        rewritten = FinalReadinessAgent._canonicalize_table_section(
            rewritten,
            heading="### Technical Compliance Matrix",
            row_id_re=r"\bTR-\d{3}\b",
        )
        rewritten = FinalReadinessAgent._canonicalize_table_section(
            rewritten,
            heading="## Pricing Schedule Matrix",
            row_id_re=r"\b\d+\.\d{2}\b",
        )
        appendix_idx = rewritten.find("## Appendix Forms & Declarations")
        if appendix_idx >= 0:
            appendix_block = rewritten[appendix_idx:]
            appendix_block = FinalReadinessAgent._canonicalize_table_section(
                appendix_block,
                heading="### Compliance Matrix",
                row_id_re=r"\bCM-\d{2}\b",
            )
            rewritten = rewritten[:appendix_idx] + appendix_block
        return rewritten

    @staticmethod
    def _canonicalize_table_section(
        full_narr: str,
        heading: str,
        row_id_re: str,
    ) -> str:
        import re

        heading_level = len(heading.split(" ", 1)[0])
        heading_text = heading.split(" ", 1)[1].strip()
        heading_match = re.search(
            rf"(?m)^#{{{heading_level}}}\s+(?:\d+(?:\.\d+)*\.?\s+)?{re.escape(heading_text)}\s*$",
            full_narr,
        )
        if not heading_match:
            return full_narr

        start = heading_match.start()
        heading_end = full_narr.find("\n", start)
        if heading_end < 0:
            return full_narr

        section_body_start = heading_end + 1
        next_heading_match = re.search(
            rf"(?m)^#{{1,{heading_level}}}\s+",
            full_narr[section_body_start:],
        )
        section_end = (
            section_body_start + next_heading_match.start()
            if next_heading_match
            else len(full_narr)
        )

        section_body = full_narr[section_body_start:section_end]
        normalized_body = FinalReadinessAgent._dedupe_markdown_table_rows(
            section_body,
            row_id_re,
        )
        if not normalized_body.strip():
            return full_narr

        return (
            full_narr[:section_body_start]
            + "\n"
            + normalized_body.strip()
            + "\n"
            + full_narr[section_end:]
        )

    @staticmethod
    def _split_table_cells(line: str) -> list[str]:
        stripped = line.strip().strip("|")
        if not stripped:
            return []
        return [cell.strip() for cell in stripped.split("|")]

    @staticmethod
    def _count_table_columns(line: str) -> int:
        stripped = line.strip()
        pipes = stripped.count("|")
        if stripped.startswith("|") and stripped.endswith("|"):
            return max(1, pipes - 1)
        if not stripped.startswith("|") and not stripped.endswith("|"):
            return max(1, pipes + 1)
        return max(1, pipes)

    @staticmethod
    def _trim_trailing_empty_cells(cells: list[str]) -> list[str]:
        trimmed = list(cells)
        while trimmed and not trimmed[-1].strip():
            trimmed.pop()
        return trimmed

    @staticmethod
    def _looks_like_priority(value: str) -> bool:
        normalized = " ".join((value or "").strip().lower().split())
        return normalized in {
            "mandatory",
            "optional",
            "preferred",
            "informational",
            "required",
        }

    @staticmethod
    def _looks_like_status(value: str) -> bool:
        normalized = " ".join((value or "").strip().lower().split())
        return normalized in {
            "c",
            "pc",
            "nc",
            "compliant",
            "partially compliant",
            "partial",
            "non-compliant",
            "non compliant",
            "yes",
            "no",
            "pass",
            "fail",
        }

    @classmethod
    def _resolve_vendor_cells(cls, cells: list[str]) -> tuple[str, str]:
        tail = cls._trim_trailing_empty_cells(cells)
        if not tail:
            return "", ""
        if len(tail) == 1:
            return tail[0], ""

        response = tail[0]
        remarks_parts = tail[1:]
        if cls._looks_like_status(remarks_parts[0]) and not cls._looks_like_status(response):
            return remarks_parts[0], " | ".join([response, *remarks_parts[1:]]).strip()

        return response, " | ".join(remarks_parts).strip()

    @classmethod
    def _coerce_table_row(cls, cells: list[str], expected_col_count: int) -> str:
        if not expected_col_count or not cells:
            return "| " + " | ".join(cells) + " |" if cells else ""

        if len(cells) > expected_col_count:
            cells = cells[: expected_col_count - 1] + [" | ".join(cells[expected_col_count - 1 :])]
        elif len(cells) < expected_col_count:
            cells = cells + [""] * (expected_col_count - len(cells))

        return f"| {' | '.join(cells)} |"

    @classmethod
    def _normalize_table_row(
        cls,
        row: str,
        row_id_re: str,
        header_line: str,
    ) -> str:
        cells = cls._trim_trailing_empty_cells(cls._split_table_cells(row))
        expected_cols = cls._count_table_columns(header_line)

        if row_id_re == r"\bTR-\d{3}\b" and expected_cols >= 6:
            priority_index = next(
                (
                    idx
                    for idx, cell in enumerate(cells[1:], start=1)
                    if cls._looks_like_priority(cell)
                ),
                None,
            )

            if priority_index == 2 and len(cells) >= 5:
                description = cells[1]
                priority = cells[2]
                vendor_response, vendor_remarks = cls._resolve_vendor_cells(cells[3:])
                cells = [
                    cells[0],
                    "",
                    description,
                    priority,
                    vendor_response,
                    vendor_remarks,
                ]
            elif priority_index == 3 and len(cells) >= 4:
                vendor_response, vendor_remarks = cls._resolve_vendor_cells(cells[4:])
                cells = [
                    cells[0],
                    cells[1],
                    cells[2] or cells[1],
                    cells[3],
                    vendor_response,
                    vendor_remarks,
                ]

            if len(cells) == 4:
                row_id, label, compliance_state, vendor_response = cells
                cells = [
                    row_id,
                    label,
                    label or row_id,
                    "Mandatory",
                    compliance_state,
                    vendor_response,
                ]
            elif len(cells) == 5:
                row_id, label, description, compliance_state, vendor_response = cells
                cells = [
                    row_id,
                    label,
                    description or label,
                    "Mandatory",
                    compliance_state,
                    vendor_response,
                ]
            elif len(cells) >= 6 and not cells[2].strip() and cells[1].strip():
                cells[2] = cells[1].strip()

        return cls._coerce_table_row(cells, expected_cols) if cells else row.strip()

    @staticmethod
    def _dedupe_markdown_table_rows(section_body: str, row_id_re: str) -> str:
        import re

        lines = section_body.splitlines()
        header_line = ""
        separator_line = ""
        row_order: list[str] = []
        best_rows: dict[str, tuple[tuple[int, int], str]] = {}
        prelude: list[str] = []

        placeholder_re = re.compile(r"\[[^\]]+\]|vendor to fill|tbd", re.IGNORECASE)

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("[Section:") or stripped.startswith("RFP Ref:"):
                continue
            if "|" not in stripped:
                if not header_line:
                    prelude.append(line)
                continue
            if not header_line:
                header_line = stripped
                continue
            if not separator_line and set(stripped.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
                separator_line = stripped
                continue

            match = re.search(row_id_re, stripped, re.IGNORECASE)
            if not match:
                continue
            normalized_row = FinalReadinessAgent._normalize_table_row(
                stripped,
                row_id_re,
                header_line,
            )
            row_id = match.group(0).upper()
            if row_id not in row_order:
                row_order.append(row_id)

            score = (
                -len(placeholder_re.findall(normalized_row)),
                len(normalized_row),
            )
            current = best_rows.get(row_id)
            if current is None or score > current[0]:
                best_rows[row_id] = (score, normalized_row)

        if not header_line or not row_order:
            return section_body

        if not separator_line:
            col_count = FinalReadinessAgent._count_table_columns(header_line)
            separator_line = "|" + "|".join(["---"] * col_count) + "|"

        rows = [best_rows[row_id][1] for row_id in row_order if row_id in best_rows]
        rebuilt = []
        if prelude:
            rebuilt.append("\n".join(prelude).strip())
        rebuilt.extend([header_line, separator_line, *rows])
        return "\n".join(part for part in rebuilt if part).strip()

