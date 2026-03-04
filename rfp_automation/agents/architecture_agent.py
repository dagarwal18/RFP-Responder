"""
C1 — Architecture Planning Agent  (Redesigned)

Responsibility: Produce the COMPLETE response document blueprint by:
  1. Reading the RFP structure (from A2) to discover ALL required sections
  2. Reading submission/format instructions from MCP RFP store
  3. Grouping extracted requirements into requirement-driven sections
  4. Identifying knowledge-driven, commercial, legal, and boilerplate sections
  5. Mapping company capabilities to each section (via Knowledge Store)

Inputs:
  - structuring_result.sections (from A2) — RFP document structure
  - requirements_validation.validated_requirements (from B2)
  - Falls back to requirements (raw B1 output) if B2 returned empty
  - Company capabilities from MCP Knowledge Store
  - RFP submission instructions from MCP RFP Store

Outputs:
  - architecture_plan: ArchitecturePlan with full ResponseSection list
  - status → WRITING_RESPONSES
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.config import get_settings
from rfp_automation.models.enums import AgentName, PipelineStatus
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import ArchitecturePlan, ResponseSection
from rfp_automation.mcp import MCPService
from rfp_automation.services.llm_service import llm_text_call

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "architecture_prompt.txt"


class ArchitecturePlanningAgent(BaseAgent):
    name = AgentName.C1_ARCHITECTURE_PLANNING

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # ── 1. Validate rfp_id ──────────────────────────
        rfp_id = state.rfp_metadata.rfp_id
        if not rfp_id:
            raise ValueError("No rfp_id in state — A1 Intake must run first")

        logger.info(f"[C1] Starting architecture planning for {rfp_id}")

        # ── 2. Gather requirements ──────────────────────
        requirements = state.requirements_validation.validated_requirements
        if not requirements:
            requirements = state.requirements
            logger.debug("[C1] Using raw B1 requirements (B2 validated list empty)")
        else:
            logger.debug(f"[C1] Using {len(requirements)} validated requirements from B2")

        # Serialize requirements for prompt — compact format to fit token budget
        # Full objects would be ~70K chars for 70 reqs; compact is ~7K
        requirements_data = []
        compact_req_lines = []
        for req in requirements:
            if hasattr(req, "model_dump"):
                d = req.model_dump()
            elif isinstance(req, dict):
                d = req
            else:
                d = {"text": str(req)}
            requirements_data.append(d)
            # One line per requirement: ID | TYPE | CLASS | text
            req_id = d.get("requirement_id", "?")
            req_type = d.get("type", "?")
            req_class = d.get("classification", "?")
            req_text = d.get("text", str(d))[:200]  # cap text at 200 chars
            compact_req_lines.append(f"{req_id} | {req_type} | {req_class} | {req_text}")

        requirements_compact = "\n".join(compact_req_lines)
        logger.debug(
            f"[C1] Serialized {len(requirements_data)} requirements "
            f"({len(requirements_compact)} chars, compact format)"
        )

        # ── 3. Gather RFP structure from A2 ─────────────
        rfp_sections_text = self._format_a2_sections(state.structuring_result.sections)
        logger.debug(f"[C1] A2 structuring result: {len(state.structuring_result.sections)} sections")

        # ── 4. Query MCP for submission/format instructions ──
        mcp = MCPService()
        submission_instructions = self._fetch_submission_instructions(mcp, rfp_id)
        logger.debug(f"[C1] Submission instructions: {len(submission_instructions)} chars")

        # ── 5. Query MCP Knowledge Store for capabilities ─
        capabilities = self._fetch_capabilities(mcp, requirements_data, state.structuring_result.sections)
        capabilities_json = (
            json.dumps(capabilities, indent=2, default=str)
            if capabilities
            else "No company capabilities available."
        )
        logger.debug(f"[C1] Fetched {len(capabilities)} capability entries")

        # ── 6. Build prompt ─────────────────────────────
        prompt = self._build_prompt(
            rfp_sections=rfp_sections_text,
            requirements=requirements_compact,
            capabilities=capabilities_json,
            submission_instructions=submission_instructions,
        )
        logger.debug(f"[C1] Prompt built — {len(prompt)} chars")

        # ── 7. Call LLM ─────────────────────────────────
        logger.info(
            f"[C1] Calling LLM with {len(requirements_data)} requirements, "
            f"{len(capabilities)} capabilities, "
            f"{len(state.structuring_result.sections)} RFP sections"
        )
        raw_response = llm_text_call(prompt, deterministic=True)
        logger.debug(f"[C1] Raw LLM response ({len(raw_response)} chars):\n{raw_response[:2000]}")

        # ── 8. Parse response ───────────────────────────
        sections, rfp_instructions = self._parse_response(raw_response)
        logger.info(f"[C1] Parsed {len(sections)} response sections")
        for s in sections:
            logger.debug(
                f"[C1]   Section: {s.section_id} | {s.title} | "
                f"type={s.section_type} | {len(s.requirement_ids)} reqs | "
                f"{len(s.mapped_capabilities)} caps | priority={s.priority}"
            )

        # ── 9. Coverage gap detection (requirement-driven only) ──
        coverage_gaps = self._detect_coverage_gaps(requirements_data, sections)
        if coverage_gaps:
            logger.warning(
                f"[C1] Coverage gaps — {len(coverage_gaps)} mandatory "
                f"requirements unassigned: {coverage_gaps}"
            )
        else:
            logger.info("[C1] Full coverage — all mandatory requirements assigned to sections")

        # ── 10. Build result and update state ───────────
        plan = ArchitecturePlan(
            sections=sections,
            coverage_gaps=coverage_gaps,
            total_sections=len(sections),
            rfp_response_instructions=rfp_instructions,
        )
        state.architecture_plan = plan
        state.status = PipelineStatus.WRITING_RESPONSES

        # Log section type breakdown
        type_counts: dict[str, int] = {}
        for s in sections:
            type_counts[s.section_type] = type_counts.get(s.section_type, 0) + 1

        logger.info(
            f"[C1] Architecture plan complete — {plan.total_sections} sections, "
            f"{len(coverage_gaps)} coverage gaps, "
            f"types: {type_counts}"
        )

        return state

    # ── Helpers ──────────────────────────────────────────

    def _format_a2_sections(self, sections: list) -> str:
        """Format A2 structuring result sections into text for the prompt."""
        if not sections:
            return "No RFP structure available."

        parts = []
        for s in sections:
            title = (
                getattr(s, "title", str(s))
                if not isinstance(s, dict)
                else s.get("title", "")
            )
            category = (
                getattr(s, "category", "")
                if not isinstance(s, dict)
                else s.get("category", "")
            )
            summary = (
                getattr(s, "content_summary", "")
                if not isinstance(s, dict)
                else s.get("content_summary", "")
            )
            section_id = (
                getattr(s, "section_id", "")
                if not isinstance(s, dict)
                else s.get("section_id", "")
            )
            parts.append(
                f"### {section_id}: {title} [Category: {category}]\n{summary}"
            )
        return "\n\n".join(parts)

    def _fetch_submission_instructions(
        self, mcp: MCPService, rfp_id: str
    ) -> str:
        """
        Query the RFP store for submission/format instructions.
        These tell us HOW the RFP expects the response to be structured.
        """
        queries = [
            "submission instructions proposal format response structure",
            "proposal should include following sections",
            "evaluation criteria scoring methodology",
            "vendor qualification requirements eligibility",
        ]

        all_texts: list[str] = []
        seen: set[str] = set()

        for query in queries:
            try:
                results = mcp.query_rfp(query, rfp_id, top_k=5)
                for r in results:
                    text = r.get("text", "").strip()
                    if text and text not in seen:
                        seen.add(text)
                        all_texts.append(text)
            except Exception as exc:
                logger.warning(f"[C1] RFP query failed for '{query}': {exc}")

        return "\n\n".join(all_texts) if all_texts else "No explicit submission instructions found."

    def _fetch_capabilities(
        self,
        mcp: MCPService,
        requirements: list[dict[str, Any]],
        rfp_sections: list,
    ) -> list[dict[str, Any]]:
        """
        Query the Knowledge Store for company capabilities.
        Uses both requirement categories AND RFP section topics
        to get broad coverage including non-requirement sections.
        """
        # Collect unique categories from requirements
        categories = set()
        for req in requirements:
            cat = req.get("category", "")
            if cat:
                categories.add(cat.lower())

        # Collect section topics from A2 structuring result
        section_topics = set()
        for s in rfp_sections:
            title = (
                getattr(s, "title", "")
                if not isinstance(s, dict)
                else s.get("title", "")
            )
            category = (
                getattr(s, "category", "")
                if not isinstance(s, dict)
                else s.get("category", "")
            )
            if title:
                section_topics.add(title.lower())
            if category:
                section_topics.add(category.lower())

        # Build query list: general + requirement categories + section topics
        queries = [
            "company capabilities services products solutions",
            "company profile about overview experience",
            "case studies past projects references",
            "certifications compliance standards",
        ]
        for cat in categories:
            queries.append(f"{cat} capabilities solutions experience")
        for topic in section_topics:
            queries.append(f"{topic} capabilities solutions")

        seen_texts: set[str] = set()
        all_capabilities: list[dict[str, Any]] = []

        for query in queries:
            try:
                results = mcp.query_knowledge(query, top_k=5)
                for r in results:
                    text = r.get("text", "")
                    if text and text not in seen_texts:
                        seen_texts.add(text)
                        all_capabilities.append({
                            "text": text,
                            "metadata": r.get("metadata", {}),
                        })
            except Exception as exc:
                logger.warning(f"[C1] Knowledge query failed for '{query}': {exc}")

        return all_capabilities

    def _build_prompt(
        self,
        rfp_sections: str,
        requirements: str,
        capabilities: str,
        submission_instructions: str,
    ) -> str:
        """Load the prompt template and inject all four data sources with token-aware truncation."""
        template = _PROMPT_PATH.read_text(encoding="utf-8")

        # ── Token-aware budget ───────────────────────────
        chars_per_token = 4  # conservative estimate
        settings = get_settings()
        max_tokens = settings.llm_max_tokens
        reserved_output = 2000  # tokens for LLM response
        template_overhead = len(template) // chars_per_token + 200
        available_chars = max(
            (max_tokens - reserved_output - template_overhead) * chars_per_token,
            4000,
        )

        # Proportional allocation: requirements 55% (most critical), sections 20%, capabilities 15%, submission 10%
        budget_reqs = int(available_chars * 0.55)
        budget_sections = int(available_chars * 0.20)
        budget_caps = int(available_chars * 0.15)
        budget_sub = int(available_chars * 0.10)

        total_input = len(rfp_sections) + len(requirements) + len(capabilities) + len(submission_instructions)
        if total_input > available_chars:
            logger.info(
                f"[C1] Prompt inputs too large ({total_input} chars, ~{total_input // chars_per_token} tokens). "
                f"Truncating to fit budget ({available_chars} chars)"
            )

        return (
            template
            .replace("{rfp_sections}", rfp_sections[:budget_sections])
            .replace("{requirements}", requirements[:budget_reqs])
            .replace("{capabilities}", capabilities[:budget_caps])
            .replace("{submission_instructions}", submission_instructions[:budget_sub])
        )

    def _parse_response(
        self, raw_response: str
    ) -> tuple[list[ResponseSection], str]:
        """
        Parse the LLM JSON response into a list of ResponseSection
        and an rfp_response_instructions string.
        """
        text = raw_response.strip()

        # Debug: log what the LLM actually returned
        logger.debug(
            f"[C1] Raw LLM response ({len(text)} chars):\n"
            f"--- START (first 500 chars) ---\n{text[:500]}\n--- END ---"
        )

        # Strip markdown code fences from ANYWHERE in the response
        # Handles: ```json\n{...}\n``` or ```\n{...}\n``` even with preamble
        fence_match = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?\s*```",
            text,
            re.DOTALL,
        )
        if fence_match:
            text = fence_match.group(1).strip()
            logger.debug("[C1] Extracted content from markdown fence")

        # Try to parse as JSON object with "sections" key
        data = self._extract_json(text)

        if isinstance(data, dict):
            rfp_instructions = data.get("rfp_response_instructions", "")
            sections_data = data.get("sections", [])
            if isinstance(sections_data, list):
                return self._build_sections(sections_data), rfp_instructions
            # No "sections" key — try the whole object as a fallback
            logger.warning("[C1] JSON object has no 'sections' key")
            return [], rfp_instructions

        if isinstance(data, list):
            # LLM returned a bare array (legacy format)
            return self._build_sections(data), ""

        logger.warning(
            f"[C1] No valid JSON found in LLM response. "
            f"Response starts with: {raw_response[:200]!r}"
        )
        return [], ""

    def _extract_json(self, text: str) -> dict | list | None:
        """Extract JSON object or array from text, handling extra content."""
        # Find first occurrence of each delimiter
        obj_start = text.find("{")
        arr_start = text.find("[")

        # Determine which to try first (outermost delimiter)
        try_object_first = True
        if obj_start == -1 and arr_start == -1:
            return None
        elif obj_start == -1:
            try_object_first = False
        elif arr_start == -1:
            try_object_first = True
        else:
            # Both present — try whichever appears first (outermost)
            try_object_first = obj_start < arr_start

        attempts = (
            ("{", "}") if try_object_first else ("[", "]"),
            ("[", "]") if try_object_first else ("{", "}"),
        )

        for open_char, close_char in attempts:
            try:
                start = text.index(open_char)
                end = text.rindex(close_char) + 1
                candidate = text[start:end]
                return json.loads(candidate)
            except (ValueError, json.JSONDecodeError) as exc:
                # Try repairing common JSON issues
                try:
                    start = text.index(open_char)
                    end = text.rindex(close_char) + 1
                    candidate = text[start:end]
                    # Fix trailing commas before } or ]
                    repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
                    result = json.loads(repaired)
                    logger.info("[C1] JSON parsed after repairing trailing commas")
                    return result
                except (ValueError, json.JSONDecodeError):
                    logger.debug(
                        f"[C1] JSON parse failed for {open_char}...{close_char}: {exc}"
                    )
                    continue

        return None

    def _build_sections(self, items: list[dict[str, Any]]) -> list[ResponseSection]:
        """Build ResponseSection objects from parsed JSON items."""
        sections: list[ResponseSection] = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                logger.warning(f"[C1] Skipping non-dict section item {i}")
                continue
            try:
                # Normalize section_type
                section_type = item.get("section_type", "requirement_driven")
                valid_types = {
                    "requirement_driven", "knowledge_driven",
                    "commercial", "legal", "boilerplate",
                }
                if section_type not in valid_types:
                    section_type = "requirement_driven"

                section = ResponseSection(
                    section_id=item.get("section_id", f"SEC-{i + 1:02d}"),
                    title=item.get("title", item.get("section_title", "Untitled")),
                    section_type=section_type,
                    description=item.get("description", ""),
                    content_guidance=item.get("content_guidance", ""),
                    requirement_ids=item.get(
                        "requirement_ids",
                        item.get("assigned_requirements", []),
                    ),
                    mapped_capabilities=item.get(
                        "mapped_capabilities",
                        item.get("key_technologies", []),
                    ),
                    priority=int(item.get("priority", i + 1)),
                    source_rfp_section=item.get("source_rfp_section", ""),
                )
                sections.append(section)
            except (ValueError, TypeError) as exc:
                logger.warning(f"[C1] Skipping invalid section {i}: {exc}")
                continue

        return sections

    def _detect_coverage_gaps(
        self,
        requirements: list[dict[str, Any]],
        sections: list[ResponseSection],
    ) -> list[str]:
        """
        Find mandatory requirement IDs not assigned to any
        requirement_driven section.
        """
        # Collect all mandatory requirement IDs
        mandatory_ids: set[str] = set()
        for req in requirements:
            req_type = req.get("type", "MANDATORY")
            if isinstance(req_type, str) and req_type.upper() == "MANDATORY":
                req_id = req.get("requirement_id", "")
                if req_id:
                    mandatory_ids.add(req_id)

        # Collect all assigned requirement IDs across requirement-driven sections
        assigned_ids: set[str] = set()
        for section in sections:
            if section.section_type == "requirement_driven":
                assigned_ids.update(section.requirement_ids)

        # Gap = mandatory IDs not in any requirement-driven section
        gaps = sorted(mandatory_ids - assigned_ids)
        return gaps
