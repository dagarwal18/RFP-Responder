"""
Review service helpers for the human-validation phase.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from rfp_automation.models.schemas import (
    HumanValidationDecisionRecord,
    ReviewComment,
    ReviewPackage,
    ReviewParagraph,
    ReviewSection,
)
from rfp_automation.models.state import RFPGraphState
from rfp_automation.mcp import MCPService

_SECTION_PREFIX_RE = re.compile(r"^\[Section:\s*[^\]]+\]\s*", re.IGNORECASE)
_BLANK_SPLIT_RE = re.compile(r"\n\s*\n+")

_RERUN_PRIORITY = [
    "b1_requirements_extraction",
    "b2_requirements_validation",
    "c1_architecture_planning",
    "c2_requirement_writing",
    "c3_narrative_assembly",
    "d1_technical_validation",
    "commercial_legal_parallel",
]

_AUTO_RERUN_BY_DOMAIN = {
    "source": "c1_architecture_planning",
    "response": "c2_requirement_writing",
    "narrative": "c3_narrative_assembly",
    "validation": "d1_technical_validation",
    "commercial": "commercial_legal_parallel",
    "legal": "commercial_legal_parallel",
}


class ReviewService:
    """Builds review packages and routes human review feedback."""

    @staticmethod
    def as_package(data: ReviewPackage | dict[str, Any] | None) -> ReviewPackage:
        if isinstance(data, ReviewPackage):
            return data
        if isinstance(data, dict) and data:
            return ReviewPackage.model_validate(data)
        return ReviewPackage()

    @staticmethod
    def normalize_package(
        package: ReviewPackage | dict[str, Any] | None,
    ) -> ReviewPackage:
        review_package = ReviewService.as_package(package)
        review_package.total_comments = len(review_package.comments)
        review_package.open_comment_count = sum(
            1 for comment in review_package.comments
            if (comment.status or "open").lower() == "open"
        )
        return review_package

    @staticmethod
    def build_review_package(state: RFPGraphState) -> ReviewPackage:
        previous = ReviewService.as_package(state.review_package)

        package = ReviewPackage(
            review_id=previous.review_id or f"REV-{uuid.uuid4().hex[:8].upper()}",
            status="PENDING",
            source_sections=ReviewService._build_source_sections(state),
            response_sections=ReviewService._build_response_sections(state),
            comments=previous.comments,
            decision=HumanValidationDecisionRecord(),
            validation_summary=ReviewService._build_validation_summary(state),
            commercial_summary=ReviewService._build_commercial_summary(state),
            legal_summary=ReviewService._build_legal_summary(state),
        )
        return ReviewService.normalize_package(package)

    @staticmethod
    def build_global_feedback(
        package: ReviewPackage | dict[str, Any] | None,
        max_comments: int = 12,
    ) -> str:
        review_package = ReviewService.normalize_package(package)
        comments = [
            comment for comment in review_package.comments
            if (comment.status or "open").lower() == "open"
        ][:max_comments]
        if not comments:
            return ""

        lines = [
            "Human reviewer change requests to address in this revision:",
        ]
        for comment in comments:
            location = comment.anchor.section_title or comment.anchor.section_id or "General"
            if comment.anchor.paragraph_id:
                location += f" / {comment.anchor.paragraph_id}"
            lines.append(f"- [{comment.anchor.domain}] {location}: {comment.comment}")
        return "\n".join(lines)

    @staticmethod
    def build_section_feedback(
        package: ReviewPackage | dict[str, Any] | None,
        section_id: str = "",
        source_section_title: str = "",
        max_comments: int = 6,
    ) -> str:
        review_package = ReviewService.normalize_package(package)
        matches: list[ReviewComment] = []

        normalized_source = (source_section_title or "").strip().lower()
        for comment in review_package.comments:
            if (comment.status or "open").lower() != "open":
                continue

            anchor = comment.anchor
            anchor_section = (anchor.section_title or "").strip().lower()
            if section_id and anchor.section_id == section_id:
                matches.append(comment)
                continue
            if normalized_source and anchor.domain == "source" and anchor_section == normalized_source:
                matches.append(comment)

        if not matches:
            return ""

        lines = [
            "Human reviewer feedback specific to this section:",
        ]
        for comment in matches[:max_comments]:
            label = comment.anchor.paragraph_id or "section"
            lines.append(f"- ({label}) {comment.comment}")
        return "\n".join(lines)

    @staticmethod
    def compute_rerun_target(
        package: ReviewPackage | dict[str, Any] | None,
        explicit: str = "",
    ) -> str:
        explicit = (explicit or "").strip()
        if explicit and explicit.lower() != "auto":
            return explicit

        review_package = ReviewService.normalize_package(package)
        targets: list[str] = []

        for comment in review_package.comments:
            if (comment.status or "open").lower() != "open":
                continue

            hint = (comment.rerun_hint or "auto").strip()
            if hint and hint.lower() != "auto":
                targets.append(hint)
                continue

            domain = (comment.anchor.domain or "response").strip().lower()
            targets.append(_AUTO_RERUN_BY_DOMAIN.get(domain, "c2_requirement_writing"))

        if not targets:
            return "c2_requirement_writing"

        def priority_key(agent_name: str) -> int:
            try:
                return _RERUN_PRIORITY.index(agent_name)
            except ValueError:
                return len(_RERUN_PRIORITY) + 1

        return min(targets, key=priority_key)

    @staticmethod
    def _build_source_sections(state: RFPGraphState) -> list[ReviewSection]:
        rfp_id = state.rfp_metadata.rfp_id
        if not rfp_id:
            return []

        section_store = MCPService().load_rfp_sections(rfp_id)
        chunks = sorted(
            section_store.values(),
            key=lambda chunk: chunk.get("chunk_index", 0),
        )
        grouped: list[tuple[str, list[dict[str, Any]]]] = []

        for chunk in chunks:
            title = (chunk.get("section_hint") or "Untitled Section").strip()
            if not grouped or grouped[-1][0] != title:
                grouped.append((title, [chunk]))
            else:
                grouped[-1][1].append(chunk)

        sections: list[ReviewSection] = []
        for index, (title, group_chunks) in enumerate(grouped, start=1):
            paragraphs: list[ReviewParagraph] = []
            full_text_parts: list[str] = []
            paragraph_counter = 1

            for chunk in group_chunks:
                raw_text = ReviewService._clean_chunk_text(chunk.get("text", ""), title)
                if not raw_text:
                    continue

                for paragraph_text in ReviewService._split_paragraphs(raw_text):
                    paragraph = ReviewParagraph(
                        paragraph_id=f"SRC-{index:02d}:P{paragraph_counter}",
                        text=paragraph_text,
                        page_start=int(chunk.get("page_start") or 0),
                        page_end=int(chunk.get("page_end") or 0),
                    )
                    paragraphs.append(paragraph)
                    full_text_parts.append(paragraph_text)
                    paragraph_counter += 1

            sections.append(
                ReviewSection(
                    section_id=f"SRC-{index:02d}",
                    title=title,
                    domain="source",
                    page_start=min(
                        (int(chunk.get("page_start") or 0) for chunk in group_chunks),
                        default=0,
                    ),
                    page_end=max(
                        (int(chunk.get("page_end") or 0) for chunk in group_chunks),
                        default=0,
                    ),
                    full_text="\n\n".join(full_text_parts),
                    paragraphs=paragraphs,
                )
            )

        return sections

    @staticmethod
    def _build_response_sections(state: RFPGraphState) -> list[ReviewSection]:
        architecture_map = {}
        for section in state.architecture_plan.sections:
            architecture_map[section.section_id] = section

        def _get(obj: Any, key: str, default: Any = "") -> Any:
            if obj is None:
                return default
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        # ── Pre-resolve E1/E2 content for stub injection ─────────────
        commercial_result = getattr(state, "commercial_result", None)
        legal_result = getattr(state, "legal_result", None)

        # Commercial: narrative + pricing table
        commercial_text = _get(commercial_result, "commercial_narrative", "") or ""
        line_items = _get(commercial_result, "line_items", []) or []
        if line_items:
            currency = _get(commercial_result, "currency", "USD") or "USD"
            total_price = _get(commercial_result, "total_price", 0) or 0
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
            pricing_table += f"\n**Total Expected Price:** {currency} {total_price:,.2f}\n"
            commercial_text = (commercial_text.strip() + "\n" + pricing_table) if commercial_text.strip() else pricing_table

        # Legal: narrative → risk_register_summary → formatted clause risks
        legal_text = _get(legal_result, "legal_narrative", "") or ""
        if not legal_text.strip():
            legal_text = _get(legal_result, "risk_register_summary", "") or ""
        if not legal_text.strip():
            # Last resort: build text from clause_risks
            clause_risks = _get(legal_result, "clause_risks", []) or []
            if clause_risks:
                parts = ["### Legal & Compliance Risk Summary\n"]
                for risk in clause_risks:
                    rl = _get(risk, "risk_level", "LOW")
                    if hasattr(rl, "name"):
                        rl = rl.name
                    parts.append(
                        f"- **Clause {_get(risk, 'clause_id', '?')} ({rl})**: "
                        f"{_get(risk, 'concern', '')}\n"
                        f"   *Recommendation*: {_get(risk, 'recommendation', '')}"
                    )
                legal_text = "\n".join(parts)

        # Map section_type → resolved content
        _resolved_content = {
            "commercial": commercial_text.strip(),
            "legal": legal_text.strip(),
        }

        # ── Build response sections ──────────────────────────────────
        sections: list[ReviewSection] = []
        sorted_responses = sorted(
            state.writing_result.section_responses,
            key=lambda section: getattr(
                architecture_map.get(section.section_id), "priority", 999
            ),
        )

        seen_types: set[str] = set()  # track which E1/E2 types were injected

        for response in sorted_responses:
            source_title = ""
            section_type = ""
            requirement_ids = list(response.requirements_addressed or [])
            arch_section = architecture_map.get(response.section_id)
            if arch_section is not None:
                source_title = getattr(arch_section, "source_rfp_section", "") or ""
                section_type = getattr(arch_section, "section_type", "") or ""
                if not requirement_ids:
                    requirement_ids = list(getattr(arch_section, "requirement_ids", []) or [])

            content = response.content or ""
            is_stub = (
                "content generated by dedicated agent" in content.lower()
                or "PIPELINE_STUB" in content
            )

            if is_stub:
                # Resolve E1/E2 content for this stub section
                resolved = _resolved_content.get(section_type, "")
                if resolved:
                    content = resolved
                    seen_types.add(section_type)
                else:
                    # No E1/E2 content available — show placeholder
                    content = f"*Content pending from {section_type} agent.*"
                    seen_types.add(section_type)

            content = ReviewService._sanitize_response_text(content)

            paragraphs: list[ReviewParagraph] = []
            for paragraph_index, paragraph_text in enumerate(
                ReviewService._split_paragraphs(content),
                start=1,
            ):
                paragraphs.append(
                    ReviewParagraph(
                        paragraph_id=f"{response.section_id}:P{paragraph_index}",
                        text=paragraph_text,
                    )
                )

            sections.append(
                ReviewSection(
                    section_id=response.section_id,
                    title=response.title,
                    domain="response",
                    full_text=content,
                    section_type=section_type,
                    source_section_title=source_title,
                    requirement_ids=requirement_ids,
                    paragraphs=paragraphs,
                )
            )

        # ── Append any unseen E1/E2 content as fallback sections ─────
        # Only if C2 didn't produce a stub entry for them (shouldn't
        # happen normally, but covers edge cases)
        if "commercial" not in seen_types and commercial_text.strip():
            comm_paragraphs = [
                ReviewParagraph(paragraph_id=f"COMMERCIAL:P{i}", text=p)
                for i, p in enumerate(ReviewService._split_paragraphs(commercial_text.strip()), 1)
            ]
            sections.append(
                ReviewSection(
                    section_id="COMMERCIAL",
                    title="Commercial Summary",
                    domain="response",
                    full_text=commercial_text.strip(),
                    section_type="commercial",
                    paragraphs=comm_paragraphs,
                )
            )

        if "legal" not in seen_types and legal_text.strip():
            legal_paragraphs = [
                ReviewParagraph(paragraph_id=f"LEGAL:P{i}", text=p)
                for i, p in enumerate(ReviewService._split_paragraphs(legal_text.strip()), 1)
            ]
            sections.append(
                ReviewSection(
                    section_id="LEGAL",
                    title="Legal Risk Assessment",
                    domain="response",
                    full_text=legal_text.strip(),
                    section_type="legal",
                    paragraphs=legal_paragraphs,
                )
            )

        return sections

    @staticmethod
    def _build_validation_summary(state: RFPGraphState) -> str:
        result = state.technical_validation
        decision = getattr(result.decision, "value", result.decision)
        if not decision:
            return ""
        return (
            f"Decision: {decision}. "
            f"Critical failures: {result.critical_failures}. "
            f"Warnings: {result.warnings}. "
            f"Feedback: {result.feedback_for_revision or 'None'}"
        )

    @staticmethod
    def _build_commercial_summary(state: RFPGraphState) -> str:
        result = state.commercial_result
        if not result or not result.decision:
            return ""
        return (
            f"Decision: {result.decision}. "
            f"Total price: {result.currency} {result.total_price:,.2f}. "
            f"Flags: {', '.join(result.validation_flags) if result.validation_flags else 'None'}"
        )

    @staticmethod
    def _build_legal_summary(state: RFPGraphState) -> str:
        result = state.legal_result
        decision = getattr(result.decision, "value", result.decision)
        if not decision:
            return ""
        return (
            f"Decision: {decision}. "
            f"Block reasons: {', '.join(result.block_reasons) if result.block_reasons else 'None'}"
        )

    @staticmethod
    def _clean_chunk_text(text: str, section_title: str) -> str:
        cleaned = text.strip()
        cleaned = _SECTION_PREFIX_RE.sub("", cleaned)
        if cleaned.lower().startswith(section_title.lower()):
            remainder = cleaned[len(section_title):].lstrip(" \n:-")
            if remainder:
                return remainder
        return cleaned

    @staticmethod
    def _sanitize_response_text(text: str) -> str:
        """Remove internal workflow references while preserving tables and Mermaid blocks."""
        text = (text or "").strip()
        if not text:
            return ""

        mermaid_blocks: list[str] = []

        def _preserve_mermaid(match: re.Match[str]) -> str:
            mermaid_blocks.append(match.group(0))
            return f"__MERMAID_BLOCK_{len(mermaid_blocks) - 1}__"

        text = re.sub(
            r"```mermaid\s*\n.*?```",
            _preserve_mermaid,
            text,
            flags=re.DOTALL,
        )

        table_blocks: list[str] = []
        lines = text.splitlines()
        rewritten_lines: list[str] = []
        idx = 0
        while idx < len(lines):
            if lines[idx].count("|") >= 1:
                block: list[str] = []
                while idx < len(lines) and lines[idx].count("|") >= 1:
                    block.append(lines[idx])
                    idx += 1
                if len(block) >= 2:
                    table_blocks.append("\n".join(block))
                    rewritten_lines.append(f"__TABLE_BLOCK_{len(table_blocks) - 1}__")
                    continue
                rewritten_lines.extend(block)
                continue

            rewritten_lines.append(lines[idx])
            idx += 1
        text = "\n".join(rewritten_lines)

        text = re.sub(r"(?m)^\[Section:[^\n]*$", "", text)
        text = re.sub(r"\[KB-[A-F0-9_]+(?:_block_\d+)?\]", "", text)
        text = re.sub(r"\bKB-[A-F0-9_]+(?:_block_\d+)?\b", "", text)
        text = re.sub(r"\bREQ-\d{4}\b", "", text)
        text = re.sub(r"\(\s*,\s*", "(", text)
        text = re.sub(r",\s*\)", ")", text)
        text = re.sub(r"\[\s*,\s*", "[", text)
        text = re.sub(r",\s*\]", "]", text)
        text = re.sub(r"\(\s*\)", "", text)
        text = re.sub(r"\[\s*\]", "", text)

        for pattern in (
            r"\bTo address,\s*",
            r"\bRegarding,\s*",
            r"\bIncluding,\s*",
            r"\bpowered by,\s*",
        ):
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)

        text = re.sub(r"\(\s*\)", "", text)
        text = re.sub(r"[ \t]+([,.;:])", r"\1", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ ]{2,}", " ", text).strip()

        for i, block in enumerate(table_blocks):
            text = text.replace(f"__TABLE_BLOCK_{i}__", block)
        for i, block in enumerate(mermaid_blocks):
            text = text.replace(f"__MERMAID_BLOCK_{i}__", block)

        return text.strip()

    @staticmethod
    def _split_paragraphs(text: str) -> list[str]:
        text = (text or "").strip()
        if not text:
            return []
        if "```mermaid" in text or re.search(r"(?m)^\|.+\|\s*$", text):
            return [text]
        parts = [part.strip() for part in _BLANK_SPLIT_RE.split(text) if part.strip()]
        return parts or [text]
