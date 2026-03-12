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

logger = logging.getLogger(__name__)

_EXEC_SUMMARY_PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "narrative_assembly_prompt.txt"
_TRANSITIONS_PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "narrative_transitions_prompt.txt"

# Patterns for detecting C1-split sections
_CATEGORY_SPLIT_DELIM = " — "                   # "Title — Sub-category"
_PART_SPLIT_PATTERN = re.compile(r"\s*\(Part\s+\d+\)\s*$")  # "Title (Part N)"

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
        if _CATEGORY_SPLIT_DELIM in title:
            return title.split(_CATEGORY_SPLIT_DELIM, 1)[0].strip()
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
        except Exception:
            pass  # KB unavailable

        if company_name:
            replacements.extend([
                (re.compile(r"\[Vendor\s+Name\]", re.IGNORECASE), company_name),
                (re.compile(r"\[Your\s+Company\s+Name\]", re.IGNORECASE), company_name),
                (re.compile(r"\[Company\s+Name\]", re.IGNORECASE), company_name),
            ])

        for pattern, value in replacements:
            text = pattern.sub(value, text)
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
    ) -> str:
        """Assemble the complete proposal document."""
        parts: list[str] = []

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
        except Exception:
            pass  # KB unavailable
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
        for i, group in enumerate(groups):
            # Transition before non-first groups
            transition = transitions.get(i, "")
            if transition:
                parts.append(f"\n{transition}\n")

            if group.is_split and len(group.children) > 1:
                # Grouped parent heading with sub-sections
                parts.append(f"\n## {group.parent_title}\n")
                for child in group.children:
                    child_title = self._get_attr(child, "title", "Untitled")
                    content = self._get_attr(child, "content", "")

                    sub_title = self._get_sub_title(child_title, group.parent_title)
                    parts.append(f"\n### {sub_title}\n")

                    content = self._strip_content_heading(content, child_title)
                    content = self._strip_content_heading(content, sub_title)

                    if self._is_stub_content(content):
                        parts.append(
                            "> **Note:** This section will be completed by "
                            "the dedicated pipeline agent.\n"
                        )
                    elif content:
                        parts.append(content)
            else:
                # Standalone section
                child = group.children[0]
                title = self._get_attr(child, "title", "Untitled")
                content = self._get_attr(child, "content", "")

                parts.append(f"\n## {title}\n")

                # Strip duplicate heading from C2 content
                content = self._strip_content_heading(content, title)

                if self._is_stub_content(content):
                    parts.append(
                        "> **Note:** This section will be completed by "
                        "the dedicated pipeline agent.\n"
                    )
                elif content:
                    parts.append(content)

        # ── Coverage Appendix ───────────────────────────
        if coverage_appendix:
            parts.append("\n---\n\n## Appendix: Requirement Coverage Matrix\n")
            parts.append(coverage_appendix)

        return "\n\n".join(parts)

    @staticmethod
    def _get_sub_title(child_title: str, parent_title: str) -> str:
        """Derive the sub-heading from a split section title.

        e.g., "Technical Solution — Security" → "Security"
              "Technical Solution (Part 2)" → "Part 2"
        If the derived title equals the parent, return "Overview".
        """
        if _CATEGORY_SPLIT_DELIM in child_title:
            sub = child_title.split(_CATEGORY_SPLIT_DELIM, 1)[1].strip()
            return sub if sub.lower() != parent_title.lower() else "Overview"

        match = _PART_SPLIT_PATTERN.search(child_title)
        if match:
            return match.group(0).strip().strip("()")

        # Fallback: avoid duplicate of parent title
        if child_title.strip().lower() == parent_title.strip().lower():
            return "Overview"
        return child_title

    def _build_table_of_contents(self, groups: list[SectionGroup]) -> str:
        """Generate a numbered table of contents."""
        toc_lines: list[str] = []
        num = 1
        for group in groups:
            toc_lines.append(f"{num}. {group.parent_title}")
            if group.is_split and len(group.children) > 1:
                for child in group.children:
                    child_title = self._get_attr(child, "title", "")
                    sub_title = self._get_sub_title(child_title, group.parent_title)
                    toc_lines.append(f"   - {sub_title}")
            num += 1
        toc_lines.append(f"{num}. Appendix: Requirement Coverage Matrix")
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
                "full": "✅ Full",
                "partial": "⚠️ Partial",
                "missing": "❌ Missing",
            }.get(quality, quality)

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
