"""
C3 — Narrative Assembly Agent

Responsibility: Combine C2's per-section prose responses into a cohesive,
               submission-ready proposal document with executive summary,
               section transitions, and coverage appendix.

Inputs:
  - writing_result.section_responses (from C2) — per-section prose
  - writing_result.coverage_matrix (from C2) — requirement coverage data
  - architecture_plan.sections (from C1) — section ordering and structure
  - rfp_metadata — client name, RFP title/number for document headers
  - technical_validation.feedback_for_revision — D1 feedback on retry

Outputs:
  - assembled_proposal: AssembledProposal with full narrative document
  - status → TECHNICAL_VALIDATION
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.config import get_settings
from rfp_automation.models.enums import AgentName, PipelineStatus
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import (
    AssembledProposal,
    SectionResponse,
    CoverageEntry,
    ResponseSection,
)
from rfp_automation.services.llm_service import llm_text_call
from rfp_automation.utils.diagram_planner import DiagramRegistry, build_diagram_block

logger = logging.getLogger(__name__)

_EXEC_SUMMARY_PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "narrative_assembly_prompt.txt"
_TRANSITIONS_PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "narrative_transitions_prompt.txt"

# Patterns for detecting C1-split sections
_CATEGORY_SPLIT_DELIM = " — "                   # "Title — Sub-category"
_CATEGORY_SPLIT_RE = re.compile(r"\s+[â€”-]\s+")
_PART_SPLIT_PATTERN = re.compile(r"\s*\(Part\s+\d+\)\s*$")  # "Title (Part N)"
_CATEGORY_SPLIT_RE = re.compile(r"\s+[\u2013\u2014-]\s+")

# Section titles that C3 generates itself — suppress C2 duplicates
_META_SECTION_TITLES_LOWER = {
    "table of contents",
    "executive summary",
    "cover letter",
}

# Placeholder patterns to detect in final output
_PLACEHOLDER_PATTERNS = [
    re.compile(r"\[\.{2,}\]"),          # [...]
    re.compile(r"\{\{.*?\}\}"),         # {{...}}
    re.compile(r"\[Company\s+Name\]", re.IGNORECASE),
    re.compile(r"\[Client\s+Name\]", re.IGNORECASE),
    re.compile(r"\[Vendor\s+Name\]", re.IGNORECASE),
    re.compile(r"\[Date\]", re.IGNORECASE),
    re.compile(r"\[RFP\s+.*?\]", re.IGNORECASE),
    re.compile(r"\[INSERT\s+.*?\]", re.IGNORECASE),
    re.compile(r"\[TBD\]", re.IGNORECASE),
    re.compile(r"\[TODO\]", re.IGNORECASE),
    re.compile(r"\[Authorized\s+.*?\]", re.IGNORECASE),
]

# Content patterns from stub/unimplemented agents
_STUB_CONTENT_RE = re.compile(
    r"^\*?\[(?:COMMERCIAL|LEGAL|PRICING|SUBMISSION|PLACEHOLDER)\s*[—–\-]",
    re.IGNORECASE,
)


@dataclass
class SectionGroup:
    """A group of related sections — may be a single standalone section
    or multiple split siblings under a parent heading."""
    parent_title: str
    children: list[SectionResponse] = field(default_factory=list)
    is_split: bool = False  # True if this group has C1-split siblings


class NarrativeAssemblyAgent(BaseAgent):
    name = AgentName.C3_NARRATIVE_ASSEMBLY

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # ── 1. Validate prerequisites ───────────────────
        rfp_id = state.rfp_metadata.rfp_id
        if not rfp_id:
            raise ValueError("No rfp_id in state — A1 Intake must run first")

        section_responses = state.writing_result.section_responses
        if not section_responses:
            logger.warning("[C3] No section responses from C2 — producing minimal output")
            state.assembled_proposal = AssembledProposal(
                executive_summary="",
                full_narrative="",
                word_count=0,
                sections_included=0,
                has_placeholders=False,
                section_order=[],
                coverage_appendix="",
            )
            state.status = PipelineStatus.TECHNICAL_VALIDATION
            return state

        logger.info(
            f"[C3] Starting narrative assembly for {rfp_id} — "
            f"{len(section_responses)} section responses from C2"
        )

        # ── 2. Sort sections by C1 priority ─────────────
        architecture_sections = state.architecture_plan.sections
        ordered_sections = self._sort_sections_by_priority(
            section_responses, architecture_sections
        )

        # ── 2b. Filter meta sections C3 handles itself ──
        #     Extract cover letter content before filtering it out
        cover_letter_content = ""
        for s in ordered_sections:
            if getattr(s, "title", "").strip().lower() == "cover letter":
                cover_letter_content = getattr(s, "content", "") or ""
                break

        pre_filter_count = len(ordered_sections)
        ordered_sections = self._filter_meta_sections(ordered_sections)
        if len(ordered_sections) < pre_filter_count:
            logger.info(
                f"[C3] Filtered {pre_filter_count - len(ordered_sections)} "
                f"meta sections (TOC, Executive Summary, Cover Letter)"
            )

        section_order = [s.section_id for s in ordered_sections]
        logger.info(f"[C3] Section order ({len(section_order)}): {section_order}")

        # ── 3. Detect and group split sections ──────────
        groups = self._group_split_sections(ordered_sections, architecture_sections)
        logger.info(
            f"[C3] Grouped into {len(groups)} top-level entries "
            f"({sum(1 for g in groups if g.is_split)} split groups)"
        )

        # ── 4. Build coverage appendix ──────────────────
        coverage_matrix = state.writing_result.coverage_matrix
        section_title_map = {
            self._get_attr(s, "section_id", ""): self._get_attr(s, "title", "")
            for s in ordered_sections
        }
        coverage_appendix = self._build_coverage_appendix(
            coverage_matrix, section_title_map
        )

        # ── 5. Compute coverage stats for exec summary ──
        coverage_stats = self._compute_coverage_stats(coverage_matrix)

        # ── 6. Check for D1 revision feedback ───────────
        revision_feedback = ""
        if state.technical_validation and state.technical_validation.feedback_for_revision:
            revision_feedback = state.technical_validation.feedback_for_revision
            logger.info(f"[C3] D1 revision feedback present ({len(revision_feedback)} chars)")

        # ── 7. Generate executive summary ───────────────
        executive_summary = self._generate_executive_summary(
            state.rfp_metadata,
            ordered_sections,
            coverage_stats,
            revision_feedback,
        )
        logger.info(f"[C3] Executive summary: {len(executive_summary.split())} words")

        # ── 8. Generate section transitions ─────────────
        transitions = self._generate_transitions(groups)
        logger.info(f"[C3] Generated {len(transitions)} section transitions")

        # ── 9. Assemble full document ───────────────────
        full_narrative = self._assemble_document(
            cover_letter=cover_letter_content,
            executive_summary=executive_summary,
            groups=groups,
            transitions=transitions,
            coverage_appendix=coverage_appendix,
            rfp_metadata=state.rfp_metadata,
            architecture_sections=architecture_sections,
        )

        # ── 9b. Clean resolvable placeholders ───────────
        full_narrative = self._clean_known_placeholders(
            full_narrative, state.rfp_metadata
        )
        executive_summary = self._clean_known_placeholders(
            executive_summary, state.rfp_metadata
        )

        # ── 10. Quality checks ──────────────────────────
        has_placeholders = self._check_placeholders(full_narrative)
        word_count = len(full_narrative.split())
        sections_included = sum(
            1 for s in ordered_sections
            if s.content and not self._is_stub_content(s.content)
        )

        if has_placeholders:
            logger.warning("[C3] ⚠ Placeholder text detected in assembled proposal")

        # ── 11. Update state ────────────────────────────
        state.assembled_proposal = AssembledProposal(
            executive_summary=executive_summary,
            full_narrative=full_narrative,
            word_count=word_count,
            sections_included=sections_included,
            has_placeholders=has_placeholders,
            section_order=section_order,
            coverage_appendix=coverage_appendix,
        )
        state.status = PipelineStatus.TECHNICAL_VALIDATION

        logger.info(
            f"[C3] Assembly complete — {word_count} words, "
            f"{sections_included} sections included, "
            f"placeholders={'YES' if has_placeholders else 'NO'}"
        )

        return state

    # ── Helpers ──────────────────────────────────────────

    @staticmethod
    def _get_attr(obj: Any, attr: str, default: Any) -> Any:
        """Get attribute from either a Pydantic model or a dict."""
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    def _sort_sections_by_priority(
        self,
        section_responses: list[SectionResponse],
        architecture_sections: list[ResponseSection],
    ) -> list[SectionResponse]:
        """Sort C2 section responses by C1 architecture plan priority."""
        priority_map: dict[str, int] = {}
        for sec in architecture_sections:
            sid = self._get_attr(sec, "section_id", "")
            priority = self._get_attr(sec, "priority", 99)
            if sid:
                priority_map[sid] = priority

        return sorted(
            section_responses,
            key=lambda s: priority_map.get(
                self._get_attr(s, "section_id", ""), 99
            ),
        )

    @staticmethod
    def _filter_meta_sections(
        sections: list[SectionResponse],
    ) -> list[SectionResponse]:
        """Remove C2 sections whose titles duplicate what C3 generates
        (Table of Contents, Executive Summary)."""
        return [
            s for s in sections
            if getattr(s, "title", "").strip().lower() not in _META_SECTION_TITLES_LOWER
        ]

    def _group_split_sections(
        self,
        ordered_sections: list[SectionResponse],
        architecture_sections: list[ResponseSection],
    ) -> list[SectionGroup]:
        """Detect C1-split siblings and group them under parent headings.

        C1 splits sections using two patterns:
          1. Category: "Technical Solution — Security & Data Protection"
          2. Parts:    "Technical Solution (Part 2)"

        Siblings share the same priority and source_rfp_section.
        """
        groups: list[SectionGroup] = []
        current_parent: str | None = None
        current_group: SectionGroup | None = None

        for section in ordered_sections:
            title = self._get_attr(section, "title", "Untitled")

            parent_title = self._extract_parent_title(title)

            if parent_title and parent_title == current_parent and current_group:
                current_group.children.append(section)
                current_group.is_split = True
            else:
                if parent_title:
                    current_parent = parent_title
                    current_group = SectionGroup(
                        parent_title=parent_title,
                        children=[section],
                        is_split=False,
                    )
                else:
                    current_parent = title
                    current_group = SectionGroup(
                        parent_title=title,
                        children=[section],
                        is_split=False,
                    )
                groups.append(current_group)

        return groups

    @staticmethod
    def _extract_parent_title(title: str) -> str | None:
        """Extract the parent title from a C1-split section title."""
        split = _CATEGORY_SPLIT_RE.split(title, maxsplit=1)
        if len(split) == 2:
            return split[0].strip()
        match = _PART_SPLIT_PATTERN.search(title)
        if match:
            return title[:match.start()].strip()
        return None

    @staticmethod
    def _is_stub_content(content: str) -> bool:
        """Check if content is from a stub/unimplemented agent."""
        if not content:
            return True
        stripped = content.strip().strip("*")
        return bool(_STUB_CONTENT_RE.match(stripped))

    @staticmethod
    def _strip_content_heading(content: str, title: str) -> str:
        """Strip a leading markdown heading from content if it matches the
        section title — prevents duplicate headings like:
           ## Technical Solution
           ### Technical Solution   ← this was inside C2 content
        """
        if not content:
            return content
        lines = content.split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            heading_match = re.match(r"^#{1,6}\s+(.+)$", stripped)
            if heading_match:
                heading_text = heading_match.group(1).strip()
                if heading_text.lower() == title.strip().lower():
                    return "\n".join(lines[i + 1:]).lstrip("\n")
            break  # first non-empty line isn't a matching heading
        return content

    @staticmethod
    def _strip_terminal_conclusion(content: str) -> str:
        """Remove generic per-section conclusion headings/paragraphs."""
        if not content:
            return content

        content = re.sub(
            r"\n+#{2,6}\s+Conclusion\s*\n[\s\S]*$",
            "",
            content,
            flags=re.IGNORECASE,
        )

        paragraphs = re.split(r"\n\s*\n", content.strip())
        if not paragraphs:
            return content.strip()

        last = paragraphs[-1].strip()
        if re.match(r"^(?:In conclusion|In summary|To conclude|Overall,)\b", last, re.IGNORECASE):
            paragraphs = paragraphs[:-1]

        return "\n\n".join(p for p in paragraphs if p.strip()).strip()

    @staticmethod
    def _strip_internal_refs_outside_structured_blocks(text: str) -> str:
        """Remove internal workflow citations while preserving tables and diagrams."""
        if not text:
            return text

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

        orphan_phrases = (
            r"\bTo address,\s*",
            r"\bRegarding,\s*",
            r"\bIncluding,\s*",
            r"\bpowered by,\s*",
        )
        for pattern in orphan_phrases:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)

        text = re.sub(r"\(\s*\)", "", text)
        text = re.sub(r"[ \t]+([,.;:])", r"\1", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ ]{2,}", " ", text)
        return text.strip()

    @staticmethod
    def _renumber_embedded_headings(
        content: str,
        prefix: str,
        level: int,
    ) -> str:
        """Flatten embedded headings under a numbered section prefix."""
        if not content:
            return content

        counter = 0
        rewritten: list[str] = []
        for line in content.splitlines():
            match = re.match(r"^\s*#{2,6}\s+(.+?)\s*$", line)
            if not match:
                rewritten.append(line)
                continue
            counter += 1
            rewritten.append(f"{'#' * level} {prefix}.{counter} {match.group(1).strip()}")
        return "\n".join(rewritten).strip()

    def _clean_known_placeholders(self, text: str, rfp_metadata: Any) -> str:
        """Replace resolvable placeholder patterns with actual data from
        rfp_metadata and company profile so they don't get flagged as unresolved."""
        client = self._get_attr(rfp_metadata, "client_name", "")
        rfp_num = self._get_attr(rfp_metadata, "rfp_number", "")
        rfp_title = self._get_attr(rfp_metadata, "rfp_title", "")
        issue_date = self._get_attr(rfp_metadata, "issue_date", "")

        replacements: list[tuple[re.Pattern, str]] = []
        if client:
            replacements.append(
                (re.compile(r"\[Client\s+Name\]", re.IGNORECASE), client)
            )
        if rfp_num:
            replacements.append(
                (re.compile(r"\[RFP\s+Number\]", re.IGNORECASE), rfp_num)
            )
        if rfp_title:
            replacements.append(
                (re.compile(r"\[RFP\s+Title\]", re.IGNORECASE), rfp_title)
            )
        if issue_date:
            replacements.append(
                (re.compile(r"\[Date\]", re.IGNORECASE), issue_date)
            )

        # ── Resolve vendor/company name (MongoDB company profile) ──
        company_name = ""
        try:
            from rfp_automation.mcp.vector_store.knowledge_store import KnowledgeStore
            kb_profile = KnowledgeStore().query_company_profile()
            company_name = kb_profile.get("company_name", "")
            if company_name:
                logger.info(f"[C3] Company profile loaded from MongoDB: {company_name}")
            else:
                logger.warning("[C3] Company profile exists in MongoDB but has no company_name")
        except Exception as e:
            logger.warning(f"[C3] KB company profile fetch failed: {e}", exc_info=True)
        if not company_name:
            company_name = get_settings().company_name or ""
        if not company_name:
            logger.warning(
                "[C3] Company name not found in MongoDB KB profile or config. "
                "Placeholders like [Proposing Company] will not be resolved. "
                "Set company_name in .env or upload a company profile via the UI."
            )

        if company_name:
            replacements.extend([
                (re.compile(r"\[Vendor\s+Name\]", re.IGNORECASE), company_name),
                (re.compile(r"\[Your\s+Company\s+Name\]", re.IGNORECASE), company_name),
                (re.compile(r"\[Company\s+Name\]", re.IGNORECASE), company_name),
                (re.compile(r"\[Proposing\s+Company\s+Name\]", re.IGNORECASE), company_name),
                (re.compile(r"\[Proposing\s+Company\]", re.IGNORECASE), company_name),
                (re.compile(r"\[Proposing\s+Company\s+Address\]", re.IGNORECASE), company_name),
                (re.compile(r"\[Proposing\s+Company\s+Contact\s+Person\]", re.IGNORECASE), f"Authorized Representative, {company_name}"),
                (re.compile(r"\[Proposing\s+Company\s+Contact\s+Information\]", re.IGNORECASE), company_name),
                (re.compile(r"\[Your\s+Name\]", re.IGNORECASE), f"Authorized Representative, {company_name}"),
                (re.compile(r"\[Your\s+Title\]", re.IGNORECASE), "Authorized Signatory"),
                (re.compile(r"\[Contact\s+Information\]", re.IGNORECASE), company_name),
                (re.compile(r"\[Your\s+Company\]", re.IGNORECASE), company_name),
                (re.compile(r"\[Hiring\s+Manager\]", re.IGNORECASE), f"Evaluation Committee, {client}"),
                (re.compile(r"\[Name\]", re.IGNORECASE), f"Authorized Representative, {company_name}"),
            ])

        # Remove remaining [Insert ...] / [TBD] / [TODO] / [Current ...] patterns
        # that can't be resolved — mark them for human review instead of
        # silently stripping them.
        submitted_at = self._get_attr(rfp_metadata, "submission_deadline", "")
        cleanup_patterns = [
            (re.compile(r"\[Insert\s+[^\]]*\]", re.IGNORECASE), "**⚠ [TBD — Requires Manual Input]**"),
            (re.compile(r"\[TBD\]", re.IGNORECASE), "**⚠ [TBD — Requires Manual Input]**"),
            (re.compile(r"\[TODO\]", re.IGNORECASE), "**⚠ [TBD — Requires Manual Input]**"),
            (re.compile(r"\[Current\s+Date\]", re.IGNORECASE), submitted_at or "the date of submission"),
        ]

        # Add explicit Insert patterns for company name BEFORE generic cleanup
        if company_name:
            replacements.extend([
                (re.compile(r"\[Insert\s+(?:Proposing\s+)?Company\s+Name\]", re.IGNORECASE), company_name),
                (re.compile(r"\[Insert\s+Vendor\s+(?:Company\s+)?Name\]", re.IGNORECASE), company_name),
                (re.compile(r"\[Insert\s+Organization\s+Name\]", re.IGNORECASE), company_name),
            ])

        # ── Protect mermaid code blocks from ALL replacements below ──
        # Mermaid uses [text] syntax for node labels which any bracket-
        # matching regex would corrupt (e.g. [SD-WAN Controller] → TBD).
        mermaid_blocks: list[str] = []
        def _preserve_mermaid(match: re.Match) -> str:
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

        # ── Run specific replacements FIRST, then cleanup patterns ──
        # This ensures [Insert Proposing Company Name] → "Vodafone Business"
        # instead of the cleanup stripping it to "" first.
        for pattern, value in replacements:
            text = pattern.sub(value, text)

        for pattern, value in cleanup_patterns:
            text = pattern.sub(value, text)

        # ── Strip leaked KB block references ──
        text = self._strip_internal_refs_outside_structured_blocks(text)

        # ── Catch-all: mark remaining generic LLM placeholders for review ──
        # Matches [number], [amount], [benchmark], [case study 1], etc.
        # Excludes [EVIDENCE NEEDED: ...] and [METRIC NEEDED: ...] which are intentional
        # Excludes [PIPELINE_STUB: ...] which is an internal marker
        # Excludes [COMMERCIAL/LEGAL/PRICING ...] which are E1/E2 stub markers
        _generic_placeholder_re = re.compile(
            r"\[(?!EVIDENCE NEEDED|METRIC NEEDED|PIPELINE_STUB|COMMERCIAL|LEGAL|PRICING|TBD)[a-z][a-z0-9 ]*\]",
            re.IGNORECASE,
        )
        text = _generic_placeholder_re.sub("**⚠ [TBD — Requires Manual Input]**", text)

        # ── Restore mermaid blocks ──
        for i, block in enumerate(table_blocks):
            text = text.replace(f"__TABLE_BLOCK_{i}__", block)
        for i, block in enumerate(mermaid_blocks):
            text = text.replace(f"__MERMAID_BLOCK_{i}__", block)

        return text

    def _generate_executive_summary(
        self,
        rfp_metadata: Any,
        sections: list[SectionResponse],
        coverage_stats: str,
        revision_feedback: str,
    ) -> str:
        """Generate executive summary via LLM."""
        template = _EXEC_SUMMARY_PROMPT.read_text(encoding="utf-8")

        rfp_metadata_block = (
            f"Client: {self._get_attr(rfp_metadata, 'client_name', 'N/A')}\n"
            f"RFP Title: {self._get_attr(rfp_metadata, 'rfp_title', 'N/A')}\n"
            f"RFP Number: {self._get_attr(rfp_metadata, 'rfp_number', 'N/A')}\n"
            f"Issue Date: {self._get_attr(rfp_metadata, 'issue_date', 'Not specified')}\n"
            f"Deadline: {self._get_attr(rfp_metadata, 'deadline_text', 'Not specified')}\n"
        )

        section_lines = []
        for i, s in enumerate(sections, 1):
            title = self._get_attr(s, "title", "Untitled")
            word_count = self._get_attr(s, "word_count", 0)
            section_lines.append(f"{i}. {title} ({word_count} words)")
        section_titles = "\n".join(section_lines)

        key_strengths = self._extract_key_strengths(sections)

        prompt = (
            template
            .replace("{rfp_metadata}", rfp_metadata_block)
            .replace("{section_titles}", section_titles[:3000])
            .replace("{coverage_stats}", coverage_stats)
            .replace("{key_strengths}", key_strengths[:2000])
            .replace("{revision_feedback}", revision_feedback or "No revision feedback — this is the initial assembly.")
        )

        response = llm_text_call(prompt, deterministic=True)
        return response.strip()

    def _generate_transitions(
        self,
        groups: list[SectionGroup],
    ) -> dict[int, str]:
        """Generate transition text between top-level groups."""
        if len(groups) <= 1:
            return {}

        template = _TRANSITIONS_PROMPT.read_text(encoding="utf-8")
        transitions: dict[int, str] = {}

        for i in range(1, len(groups)):
            prev_group = groups[i - 1]
            curr_group = groups[i]

            prev_content = self._get_attr(prev_group.children[-1], "content", "")
            prev_summary = " ".join(prev_content.split()[-100:]) if prev_content else ""

            curr_content = self._get_attr(curr_group.children[0], "content", "")
            curr_summary = " ".join(curr_content.split()[:100]) if curr_content else ""

            prompt = (
                template
                .replace("{current_section_title}", prev_group.parent_title)
                .replace("{current_section_summary}", prev_summary[:500])
                .replace("{next_section_title}", curr_group.parent_title)
                .replace("{next_section_summary}", curr_summary[:500])
            )

            try:
                transition = llm_text_call(prompt, deterministic=True)
                transitions[i] = transition.strip()
            except Exception as exc:
                logger.warning(f"[C3] Transition generation failed for group {i}: {exc}")
                transitions[i] = ""

        return transitions

    def _assemble_document(
        self,
        cover_letter: str,
        executive_summary: str,
        groups: list[SectionGroup],
        transitions: dict[int, str],
        coverage_appendix: str,
        rfp_metadata: Any,
        architecture_sections: list[ResponseSection],
    ) -> str:
        """Assemble the complete proposal document."""
        parts: list[str] = []
        section_meta = {
            self._get_attr(section, "section_id", ""): section
            for section in architecture_sections
        }
        diagram_registry = DiagramRegistry()

        # ── Title page ──────────────────────────────────
        client = self._get_attr(rfp_metadata, "client_name", "")
        rfp_title = self._get_attr(rfp_metadata, "rfp_title", "Proposal Response")
        rfp_number = self._get_attr(rfp_metadata, "rfp_number", "")

        title_line = f"# {rfp_title}"
        if rfp_number:
            title_line += f" ({rfp_number})"
        if client:
            title_line += f"\n\nPrepared for: {client}"

        # "Prepared by:" from MongoDB company profile → placeholder
        company_name = ""
        try:
            from rfp_automation.mcp.vector_store.knowledge_store import KnowledgeStore
            kb_profile = KnowledgeStore().query_company_profile()
            company_name = kb_profile.get("company_name", "")
            if company_name:
                logger.info(f"[C3] Title page company from MongoDB: {company_name}")
        except Exception as e:
            logger.warning(f"[C3] KB company profile fetch failed for title page: {e}", exc_info=True)
        if not company_name:
            company_name = get_settings().company_name or ""
        prepared_by = company_name if company_name else "[Vendor Name]"
        title_line += f"\n\nPrepared by: {prepared_by}"

        parts.append(title_line)

        # ── Cover Letter (C2 content) ────────────────────
        if cover_letter and cover_letter.strip():
            parts.append("---\n\n## Cover Letter\n")
            parts.append(cover_letter.strip())

        # ── Executive Summary ───────────────────────────
        parts.append("---\n\n## Executive Summary\n")
        parts.append(executive_summary)

        # ── Table of Contents ───────────────────────────
        toc = self._build_table_of_contents(groups)
        parts.append("---\n\n## Table of Contents\n")
        parts.append(toc)

        # ── Sections ────────────────────────────────────
        parts.append("---\n")
        for i, group in enumerate(groups, start=1):
            # Transition before non-first groups
            transition = transitions.get(i - 1, "")
            if transition:
                parts.append(f"\n{transition}\n")

            if group.is_split and len(group.children) > 1:
                # Grouped parent heading with sub-sections
                parts.append(f"\n## {i}. {group.parent_title}\n")

                # ── Merge children sharing the same base category ──
                # E.g., "Commercial Terms (Part 1)" + "Commercial Terms (Part 2)"
                # → single "### Commercial Terms" with combined content.
                merged_children = self._merge_split_child_sections(
                    group.children, group.parent_title
                )

                for sub_idx, (sub_title, child_bundle) in enumerate(merged_children, start=1):
                    parts.append(f"\n### {i}.{sub_idx} {sub_title}\n")
                    rendered_contents: list[str] = []
                    has_stub = False
                    for child in child_bundle:
                        child_title = self._get_attr(child, "title", sub_title)
                        content = self._get_attr(child, "content", "")
                        content = self._strip_content_heading(content, child_title)
                        content = self._strip_content_heading(content, sub_title)
                        content = self._strip_terminal_conclusion(content)
                        if self._is_stub_content(content):
                            has_stub = True
                            continue
                        if content:
                            rendered_contents.append(content)

                    diagram_block = self._build_section_diagram(
                        child_bundle,
                        display_title=sub_title,
                        parent_title=group.parent_title,
                        section_meta=section_meta,
                        registry=diagram_registry,
                    )
                    if diagram_block:
                        parts.append(diagram_block)

                    if not rendered_contents and has_stub:
                        parts.append(f"\n> **Note:** [PIPELINE_STUB: {sub_title}]\n")
                    else:
                        for content in rendered_contents:
                            parts.append(content)
            else:
                # Standalone section
                child = group.children[0]
                title = self._get_attr(child, "title", "Untitled")
                content = self._get_attr(child, "content", "")

                parts.append(f"\n## {i}. {title}\n")

                # Strip duplicate heading from C2 content
                content = self._strip_content_heading(content, title)
                content = self._strip_terminal_conclusion(content)

                if self._is_stub_content(content):
                    parts.append(f"\n> **Note:** [PIPELINE_STUB: {title}]\n")
                elif content:
                    diagram_block = self._build_section_diagram(
                        [child],
                        display_title=title,
                        parent_title="",
                        section_meta=section_meta,
                        registry=diagram_registry,
                    )
                    if diagram_block:
                        parts.append(diagram_block)
                    parts.append(content)

        # ── Coverage Appendix ───────────────────────────
        return "\n\n".join(parts)

    @staticmethod
    def _get_sub_title(child_title: str, parent_title: str) -> str:
        """Derive the sub-heading from a split section title.

        e.g., "Technical Solution — Security" → "Security"
              "Technical Solution (Part 2)" → "Part 2"
        If the derived title equals the parent, return "Overview".
        """
        normalized_title = (
            (child_title or "")
            .replace("â€”", " - ")
            .replace("â€“", " - ")
            .replace("—", " - ")
            .replace("–", " - ")
        )
        split = _CATEGORY_SPLIT_RE.split(normalized_title, maxsplit=1)
        if len(split) == 2:
            sub = split[1].strip()
            return sub if sub.lower() != parent_title.lower() else "Overview"

        parent_prefix = (parent_title or "").strip()
        if parent_prefix and normalized_title.lower().startswith(parent_prefix.lower()):
            suffix = normalized_title[len(parent_prefix):]
            suffix = re.sub(r"^[^A-Za-z0-9]+", "", suffix).strip()
            if suffix:
                return suffix

        match = _PART_SPLIT_PATTERN.search(normalized_title)
        if match:
            return match.group(0).strip().strip("()")

        # Fallback: avoid duplicate of parent title
        if normalized_title.strip().lower() == parent_title.strip().lower():
            return "Overview"
        return normalized_title.strip()

    def _merge_split_children(
        self,
        children: list[SectionResponse],
        parent_title: str,
    ) -> list[tuple[str, list[str]]]:
        """Merge children that share the same base category into single entries.

        E.g., "Commercial Terms (Part 1)" and "Commercial Terms (Part 2)"
        both produce sub_title "Commercial Terms" → their content is merged
        under one heading.

        Returns:
            List of (sub_title, [content_strings]) tuples, ordered by first
            occurrence.
        """
        from collections import OrderedDict

        merged: OrderedDict[str, list[str]] = OrderedDict()

        for child in children:
            child_title = self._get_attr(child, "title", "Untitled")
            content = self._get_attr(child, "content", "")
            raw_sub = self._get_sub_title(child_title, parent_title)

            # Strip "(Part N)" from the sub-title to get the base category
            base = _PART_SPLIT_PATTERN.sub("", raw_sub).strip()
            if not base:
                base = raw_sub  # keep original if stripping left nothing

            # Strip duplicate headings from content
            content = self._strip_content_heading(content, child_title)
            content = self._strip_content_heading(content, raw_sub)
            content = self._strip_content_heading(content, base)

            merged.setdefault(base, [])
            if content and content.strip():
                merged[base].append(content)

        return list(merged.items())

    def _merge_split_child_sections(
        self,
        children: list[SectionResponse],
        parent_title: str,
    ) -> list[tuple[str, list[SectionResponse]]]:
        """Group split children by base sub-title while preserving section metadata."""
        from collections import OrderedDict

        merged: OrderedDict[str, list[SectionResponse]] = OrderedDict()
        for child in children:
            child_title = self._get_attr(child, "title", "Untitled")
            raw_sub = self._get_sub_title(child_title, parent_title)
            base = _PART_SPLIT_PATTERN.sub("", raw_sub).strip() or raw_sub
            merged.setdefault(base, [])
            merged[base].append(child)
        return list(merged.items())

    def _build_section_diagram(
        self,
        children: list[SectionResponse],
        display_title: str,
        parent_title: str,
        section_meta: dict[str, ResponseSection],
        registry: DiagramRegistry,
    ) -> str:
        """Build one section-aware Mermaid block for the given assembled section."""
        contents: list[str] = []
        descriptions: list[str] = []
        guidances: list[str] = []
        notes: list[str] = []
        source_terms: list[str] = []
        visual_relevance = "auto"
        visual_type_hint = ""

        for child in children:
            content = self._get_attr(child, "content", "")
            child_title = self._get_attr(child, "title", display_title)
            content = self._strip_content_heading(content, child_title)
            content = self._strip_content_heading(content, display_title)
            content = self._strip_terminal_conclusion(content)
            if content and not self._is_stub_content(content):
                contents.append(content)

            section_id = self._get_attr(child, "section_id", "")
            meta = section_meta.get(section_id)
            if not meta:
                continue
            descriptions.append(self._get_attr(meta, "description", ""))
            guidances.append(self._get_attr(meta, "content_guidance", ""))
            notes.append(self._get_attr(meta, "visual_notes", ""))
            for term in self._get_attr(meta, "visual_source_terms", []):
                if term and term not in source_terms:
                    source_terms.append(term)
            meta_relevance = self._get_attr(meta, "visual_relevance", "auto") or "auto"
            if meta_relevance == "required":
                visual_relevance = "required"
            elif meta_relevance == "none" and visual_relevance == "auto":
                visual_relevance = "none"
            elif meta_relevance == "optional" and visual_relevance == "auto":
                visual_relevance = "optional"
            if not visual_type_hint:
                visual_type_hint = self._get_attr(meta, "visual_type_hint", "") or ""

        combined_content = "\n\n".join(contents).strip()
        if not combined_content:
            return ""

        return build_diagram_block(
            section_title=display_title,
            parent_title=parent_title,
            section_description=" ".join(filter(None, descriptions)),
            content_guidance=" ".join(filter(None, guidances)),
            content=combined_content,
            visual_relevance=visual_relevance,
            visual_type_hint=visual_type_hint,
            visual_notes=" ".join(filter(None, notes)),
            visual_source_terms=source_terms,
            registry=registry,
        )

    def _build_table_of_contents(self, groups: list[SectionGroup]) -> str:
        """Generate a numbered table of contents."""
        toc_lines: list[str] = []
        num = 1
        for group in groups:
            toc_lines.append(f"{num}. {group.parent_title}")
            if group.is_split and len(group.children) > 1:
                # Use merged sub-titles (strip Part N duplicates)
                merged = self._merge_split_children(
                    group.children, group.parent_title
                )
                for sub_num, (sub_title, _) in enumerate(merged, start=1):
                    toc_lines.append(f"    {num}.{sub_num} {sub_title}")
            num += 1
        return "\n".join(toc_lines)

    @staticmethod
    def _build_coverage_appendix(
        coverage_matrix: list[CoverageEntry],
        section_title_map: dict[str, str] | None = None,
    ) -> str:
        """Format the coverage matrix as a markdown table with section
        titles (not SEC-XX codes) and a coverage summary."""
        if not coverage_matrix:
            return "No coverage data available."

        # Compute stats for summary
        total = len(coverage_matrix)
        full = partial = 0
        for entry in coverage_matrix:
            quality = str(entry.coverage_quality if hasattr(entry, "coverage_quality") else entry.get("coverage_quality", "")).lower().strip()
            if quality == "full":
                full += 1
            elif quality == "partial":
                partial += 1
        missing = total - full - partial
        full_pct = (full / total * 100) if total else 0
        partial_pct = (partial / total * 100) if total else 0
        missing_pct = (missing / total * 100) if total else 0

        summary = (
            f"**Coverage Summary:** {full} of {total} requirements fully "
            f"addressed ({full_pct:.1f}%), {partial} partial ({partial_pct:.1f}%), "
            f"{missing} missing ({missing_pct:.1f}%)\n"
        )

        lines = [
            summary,
            "| Requirement ID | Addressed In | Coverage |",
            "|---|---|---|",
        ]
        for entry in coverage_matrix:
            req_id = entry.requirement_id if hasattr(entry, "requirement_id") else entry.get("requirement_id", "")
            section_id = entry.addressed_in_section if hasattr(entry, "addressed_in_section") else entry.get("addressed_in_section", "")
            quality = str(entry.coverage_quality if hasattr(entry, "coverage_quality") else entry.get("coverage_quality", "")).lower().strip()

            # Resolve SEC-XX to human-readable title
            if section_title_map and section_id:
                section_display = section_title_map.get(section_id, section_id)
            else:
                section_display = section_id or "—"

            indicator = {
                "full": "Full",
                "partial": "Partial",
                "missing": "Missing",
            }.get(quality, quality.title() if quality else "Unknown")

            lines.append(f"| {req_id} | {section_display} | {indicator} |")

        return "\n".join(lines)

    @staticmethod
    def _compute_coverage_stats(coverage_matrix: list[CoverageEntry]) -> str:
        """Compute coverage statistics for the executive summary prompt."""
        if not coverage_matrix:
            return "No requirements to report on."

        total = len(coverage_matrix)
        full = sum(1 for e in coverage_matrix
                   if str(e.coverage_quality if hasattr(e, "coverage_quality") else e.get("coverage_quality", "")).lower().strip() == "full")
        partial = sum(1 for e in coverage_matrix
                      if str(e.coverage_quality if hasattr(e, "coverage_quality") else e.get("coverage_quality", "")).lower().strip() == "partial")
        missing = total - full - partial

        full_pct = (full / total * 100) if total else 0
        partial_pct = (partial / total * 100) if total else 0
        missing_pct = (missing / total * 100) if total else 0

        return (
            f"Total requirements: {total}\n"
            f"Fully addressed: {full} ({full_pct:.1f}%)\n"
            f"Partially addressed: {partial} ({partial_pct:.1f}%)\n"
            f"Missing: {missing} ({missing_pct:.1f}%)"
        )

    @staticmethod
    def _extract_key_strengths(sections: list[SectionResponse]) -> str:
        """Extract key capability mentions from section content."""
        strength_patterns = [
            re.compile(r"(?:ISO|SOC|PCI|HIPAA|GDPR|FedRAMP)\s*[\d\-]*", re.IGNORECASE),
            re.compile(r"\d+[\+]?\s*(?:years?|clients?|deployments?|countries?)", re.IGNORECASE),
            re.compile(r"(?:99\.?\d*%)\s*(?:uptime|availability|SLA)", re.IGNORECASE),
            re.compile(r"(?:AES|RSA|TLS)\s*[\d\-]*\s*(?:encryption|bit)?", re.IGNORECASE),
            re.compile(r"24/7\s*(?:support|monitoring|operations?)", re.IGNORECASE),
        ]

        strengths: list[str] = []
        seen: set[str] = set()

        for section in sections:
            content = section.content if hasattr(section, "content") else section.get("content", "")
            if not content:
                continue
            for pattern in strength_patterns:
                for match in pattern.finditer(content):
                    start = max(0, match.start() - 50)
                    end = min(len(content), match.end() + 50)
                    snippet = content[start:end].strip()
                    key = match.group(0).lower().strip()
                    if key not in seen:
                        seen.add(key)
                        strengths.append(f"- {snippet}")

        if not strengths:
            return "Key strengths will be derived from the section content provided above."

        return "\n".join(strengths[:15])

    @staticmethod
    def _check_placeholders(text: str) -> bool:
        """Check if the assembled text contains placeholder patterns."""
        for pattern in _PLACEHOLDER_PATTERNS:
            if pattern.search(text):
                return True
        return False
