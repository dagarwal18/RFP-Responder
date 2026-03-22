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
from rfp_automation.services.review_service import ReviewService

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "architecture_prompt.txt"

# Maximum requirements per section before splitting — keeps C2's token budget
# manageable and ensures each section gets adequate LLM attention.
_MAX_REQS_PER_SECTION = 10


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
        review_feedback = ReviewService.build_global_feedback(state.review_package)

        # ── 6. PASS 1 — Structure planning (compact, no capabilities) ─
        #    Send only req IDs/types and section titles for structural planning.
        #    Capabilities are fetched per-section in Pass 2 to stay within budget.
        prompt = self._build_prompt(
            rfp_sections=rfp_sections_text,
            requirements=requirements_compact,
            capabilities="Capabilities will be mapped per-section after structure is planned.",
            submission_instructions=submission_instructions,
            review_feedback=review_feedback,
        )
        logger.info(
            f"[C1] Pass 1 (structure): Calling LLM with {len(requirements_data)} requirements, "
            f"{len(state.structuring_result.sections)} RFP sections (no capabilities)"
        )
        raw_response = llm_text_call(prompt, deterministic=True)
        logger.debug(f"[C1] Pass 1 LLM response ({len(raw_response)} chars)")

        # ── 7. Parse Pass 1 response ────────────────────
        sections, rfp_instructions = self._parse_response(raw_response)
        logger.info(f"[C1] Pass 1 produced {len(sections)} response sections")
        for s in sections:
            logger.debug(
                f"[C1]   Section: {s.section_id} | {s.title} | "
                f"type={s.section_type} | {len(s.requirement_ids)} reqs | "
                f"{len(s.mapped_capabilities)} caps | priority={s.priority}"
            )

        # ── 8. Programmatic gap filling ─────────────────────
        #    The LLM only assigns representative IDs per section.
        #    We now deterministically assign ALL remaining requirements
        #    by matching classification / category / keywords to sections.
        #    This is instant, uses zero LLM tokens, and guarantees coverage.
        before_gaps = self._detect_coverage_gaps(requirements_data, sections)
        if before_gaps:
            logger.info(
                f"[C1] Programmatic mapping: {len(before_gaps)} mandatory "
                f"requirements unassigned after Pass 1 — assigning now"
            )
            sections = self._programmatic_assign(
                requirements_data, sections
            )

        # ── 8b. Split overloaded sections ────────────────
        sections = self._split_overloaded_sections(
            requirements_data, sections
        )

        # ── 8b2. Enforce correct types for commercial/legal sections ──
        sections = self._enforce_section_types(sections)

        # ── 8c. PASS 2 — Per-section capability enrichment ──
        #    Now that we know the structure, query KB for capabilities
        #    targeted to each section's specific requirements.
        logger.info(f"[C1] Pass 2 (enrich): Fetching capabilities for {len(sections)} sections")
        sections = self._enrich_sections_with_capabilities(
            mcp, requirements_data, sections
        )

        # ── 9. Final coverage check ─────────────────────
        coverage_gaps = self._detect_coverage_gaps(requirements_data, sections)
        if coverage_gaps:
            logger.warning(
                f"[C1] Final coverage gaps — {len(coverage_gaps)} mandatory "
                f"requirements still unassigned: "
                f"{coverage_gaps[:20]}{'...' if len(coverage_gaps) > 20 else ''}"
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
        review_feedback: str = "",
    ) -> str:
        """Load the prompt template and inject data with TPM-aware truncation.

        Groq free tier has a 6,000 TPM (tokens per minute) limit.
        A single request's total tokens (input + output) cannot exceed this.
        We budget ~4,000 tokens for input and ~2,000 for output.
        """
        template = _PROMPT_PATH.read_text(encoding="utf-8")

        # ── Budget calculation ───────────────────────────
        chars_per_token = 4  # conservative estimate
        settings = get_settings()
        # Use llm_max_tokens as the per-request token budget (covers TPM limit).
        # On Groq free tier (6K TPM), a single request can use up to 6K tokens.
        # llm_max_tokens (8192) is a reasonable cap; we reserve output headroom.
        total_token_budget = settings.llm_max_tokens  # 8192
        output_reserve = 2000  # tokens for LLM JSON response
        template_tokens = len(template) // chars_per_token + 200  # ~1,950 tokens
        data_budget_tokens = total_token_budget - output_reserve - template_tokens
        data_budget_chars = max(data_budget_tokens * chars_per_token, 4000)

        # Proportional allocation: requirements 55%, sections 20%, capabilities 15%, submission 10%
        budget_reqs = int(data_budget_chars * 0.55)
        budget_sections = int(data_budget_chars * 0.20)
        budget_caps = int(data_budget_chars * 0.15)
        budget_sub = int(data_budget_chars * 0.10)

        total_input = len(rfp_sections) + len(requirements) + len(capabilities) + len(submission_instructions)
        if total_input > data_budget_chars:
            logger.info(
                f"[C1] Truncating prompt inputs ({total_input} chars, "
                f"~{total_input // chars_per_token} tokens) to fit budget "
                f"({data_budget_chars} chars, ~{data_budget_tokens} tokens)"
            )

        prompt = (
            template
            .replace("{rfp_sections}", self._truncate_at_word(rfp_sections, budget_sections))
            .replace("{requirements}", self._truncate_at_word(requirements, budget_reqs))
            .replace("{capabilities}", self._truncate_at_word(capabilities, budget_caps))
            .replace("{submission_instructions}", self._truncate_at_word(submission_instructions, budget_sub))
        )
        if review_feedback:
            prompt += (
                "\n\n## Human Validation Feedback\n\n"
                + self._truncate_at_word(review_feedback, 1500)
                + "\n\nRevise the proposal structure to address this feedback."
            )
        return prompt

    @staticmethod
    def _truncate_at_word(text: str, max_chars: int) -> str:
        """Truncate text at a word boundary, never mid-word."""
        if len(text) <= max_chars:
            return text
        cut = text.rfind(" ", 0, max_chars)
        if cut <= 0:
            cut = max_chars
        return text[:cut]

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

    def _programmatic_assign(
        self,
        requirements: list[dict[str, Any]],
        sections: list[ResponseSection],
    ) -> list[ResponseSection]:
        """
        Deterministically assign ALL unassigned mandatory requirements
        to sections using classification, category, and keyword matching.
        No LLM calls — instant and guarantees 100% coverage.
        """
        # Build section index for matching
        section_map = {s.section_id: s for s in sections}
        req_driven = [s for s in sections if s.section_type == "requirement_driven"]

        # Collect already-assigned IDs
        assigned_ids: set[str] = set()
        for s in req_driven:
            assigned_ids.update(s.requirement_ids)

        # Build keyword index: lowercase words in section title → section_id
        title_words: dict[str, list[str]] = {}  # word → [section_ids]
        for s in req_driven:
            words = set(re.findall(r"[a-z]+", s.title.lower()))
            # Also include description keywords
            words.update(re.findall(r"[a-z]+", s.description.lower())[:10])
            for w in words:
                if len(w) > 3:  # skip tiny words
                    title_words.setdefault(w, []).append(s.section_id)

        # Category → likely section keywords for matching
        _CATEGORY_KEYWORDS: dict[str, list[str]] = {
            "TECHNICAL": ["technical", "solution", "architecture", "platform",
                          "system", "integration", "infrastructure"],
            "FUNCTIONAL": ["technical", "solution", "functional", "feature",
                           "capability", "system"],
            "SECURITY": ["security", "compliance", "privacy", "data",
                         "protection", "access", "encryption"],
            "COMPLIANCE": ["compliance", "regulatory", "certification",
                           "standard", "audit", "governance"],
            "COMMERCIAL": ["pricing", "commercial", "cost", "financial",
                           "payment", "licensing"],
            "OPERATIONAL": ["support", "maintenance", "operational", "sla",
                            "service", "monitoring", "management"],
            "TRAINING": ["training", "change", "adoption", "workshop", "learning"],
            "SUBMISSION": ["submission", "proposal", "format", "deadline", "forms"],
            "EVALUATION": ["evaluation", "scoring", "criteria", "assessment"],
        }

        _SLA_KEYWORDS = {"sla", "uptime", "downtime", "availability", "resolution"}

        # Classification → preferred section keywords
        _CLASS_KEYWORDS: dict[str, list[str]] = {
            "FUNCTIONAL": ["technical", "solution", "functional"],
            "NON_FUNCTIONAL": ["sla", "performance", "compliance",
                               "non-functional", "availability", "security"],
            "EVALUATION_CRITERIA": ["compliance", "matrix", "evaluation",
                                    "scoring", "qualification"],
        }

        # Track assignments for logging
        assignments: dict[str, int] = {}
        catch_all_id: str | None = None

        # Find or plan catch-all section
        for s in req_driven:
            lower_title = s.title.lower()
            if any(kw in lower_title for kw in ["compliance matrix", "general", "additional"]):
                catch_all_id = s.section_id
                break

        # Process each unassigned mandatory requirement
        for req in requirements:
            req_id = req.get("requirement_id", "")
            req_type = req.get("type", "MANDATORY")
            if not req_id or req_id in assigned_ids:
                continue
            if isinstance(req_type, str) and req_type.upper() != "MANDATORY":
                continue

            classification = req.get("classification", "FUNCTIONAL")
            if not isinstance(classification, str):
                classification = str(classification)
            classification = classification.upper()

            category = req.get("category", "TECHNICAL")
            if not isinstance(category, str):
                category = str(category)
            category = category.upper()

            req_text = req.get("text", "").lower()
            req_keywords = [k.lower() for k in req.get("keywords", [])]

            best_section: str | None = None
            best_score = 0

            for s in req_driven:
                # Skip sections already at capacity
                current_count = len(s.requirement_ids)
                if current_count >= _MAX_REQS_PER_SECTION:
                    continue

                score = 0
                lower_title = s.title.lower()
                lower_desc = s.description.lower()

                # Score 1: keyword overlap between requirement text and section
                for kw in req_keywords:
                    if kw in lower_title:
                        score += 3
                    elif kw in lower_desc:
                        score += 1

                # Score 2: category keyword match
                cat_keywords = _CATEGORY_KEYWORDS.get(category, [])
                for ck in cat_keywords:
                    if ck in lower_title:
                        score += 2

                # Score 3: classification keyword match
                cls_keywords = _CLASS_KEYWORDS.get(classification, [])
                for ck in cls_keywords:
                    if ck in lower_title:
                        score += 2

                # Score 4: requirement text word overlap with section title
                req_words = set(re.findall(r"[a-z]{4,}", req_text))
                title_kws = set(re.findall(r"[a-z]{4,}", lower_title))
                overlap = req_words & title_kws
                score += len(overlap) * 2

                # Negative filter: SLA requirements in training sections
                if any(kw in req_text for kw in _SLA_KEYWORDS) and "training" in lower_title:
                    score -= 5

                if score > best_score:
                    best_score = score
                    best_section = s.section_id

            # Assign to best match, or catch-all
            target = best_section if best_score >= 2 else catch_all_id

            if not target:
                # Create catch-all Compliance Matrix section
                catch_all_id = f"SEC-{len(sections) + 1:02d}"
                catch_all = ResponseSection(
                    section_id=catch_all_id,
                    title="Compliance Matrix & General Requirements",
                    section_type="requirement_driven",
                    description="Catch-all section for requirements not fitting other sections",
                    priority=5,
                )
                sections.append(catch_all)
                req_driven.append(catch_all)
                section_map[catch_all_id] = catch_all
                target = catch_all_id

            section = section_map[target]
            if req_id not in section.requirement_ids:
                section.requirement_ids.append(req_id)
                assigned_ids.add(req_id)
                assignments[target] = assignments.get(target, 0) + 1

        # Log summary
        for sec_id, count in sorted(assignments.items()):
            sec = section_map[sec_id]
            logger.debug(
                f"[C1] Programmatic: assigned {count} requirements "
                f"to {sec_id} ({sec.title})"
            )
        total = sum(assignments.values())
        logger.info(
            f"[C1] Programmatic mapping complete: {total} requirements "
            f"assigned across {len(assignments)} sections"
        )

        return sections

    def _split_overloaded_sections(
        self,
        requirements: list[dict[str, Any]],
        sections: list[ResponseSection],
    ) -> list[ResponseSection]:
        """
        Split any section with more than _MAX_REQS_PER_SECTION requirements
        into sub-sections grouped by requirement category.

        This prevents C2's token budget from being overwhelmed and ensures
        each sub-section gets adequate LLM attention.
        """
        req_lookup = {
            r.get("requirement_id", ""): r
            for r in requirements if r.get("requirement_id")
        }

        result: list[ResponseSection] = []
        next_section_num = max(
            (int(re.search(r"\d+", s.section_id).group())
             for s in sections if re.search(r"\d+", s.section_id)),
            default=0,
        ) + 1

        # Regex to detect table/matrix/compliance sections that should NOT
        # be split — the writing agent will batch these instead.
        _TABLE_TITLE_RE = re.compile(
            r'\b(?:matrix|table|compliance|checklist|questionnaire)\b',
            re.IGNORECASE,
        )

        for section in sections:
            if (
                section.section_type != "requirement_driven"
                or len(section.requirement_ids) <= _MAX_REQS_PER_SECTION
            ):
                result.append(section)
                continue

            # ── Bypass: never split table/matrix sections ──
            if _TABLE_TITLE_RE.search(section.title):
                logger.info(
                    f"[C1] Keeping table/matrix section {section.section_id} "
                    f"({section.title}) intact — {len(section.requirement_ids)} "
                    f"reqs will be batched by the writing agent"
                )
                result.append(section)
                continue

            # Group requirements by category
            category_groups: dict[str, list[str]] = {}
            for rid in section.requirement_ids:
                req = req_lookup.get(rid, {})
                cat = req.get("category", "GENERAL")
                if not isinstance(cat, str):
                    cat = str(cat)
                cat = cat.upper()
                category_groups.setdefault(cat, []).append(rid)

            # Friendly names for sub-section titles
            _CAT_LABELS: dict[str, str] = {
                "TECHNICAL": "Core Platform & Infrastructure",
                "FUNCTIONAL": "Functional Capabilities",
                "SECURITY": "Security & Data Protection",
                "COMPLIANCE": "Regulatory Compliance",
                "OPERATIONAL": "Operations & Support",
                "COMMERCIAL": "Commercial Terms",
            }

            logger.info(
                f"[C1] Splitting overloaded section {section.section_id} "
                f"({section.title}): {len(section.requirement_ids)} reqs "
                f"→ {len(category_groups)} sub-sections by category"
            )

            # If all reqs are same category, split by chunks instead
            if len(category_groups) <= 1:
                reqs = section.requirement_ids
                chunk_size = _MAX_REQS_PER_SECTION
                for i in range(0, len(reqs), chunk_size):
                    chunk = reqs[i : i + chunk_size]
                    part_num = i // chunk_size + 1
                    sub = ResponseSection(
                        section_id=f"SEC-{next_section_num:02d}",
                        title=f"{section.title} (Part {part_num})",
                        section_type="requirement_driven",
                        description=section.description,
                        content_guidance=section.content_guidance,
                        requirement_ids=chunk,
                        mapped_capabilities=section.mapped_capabilities,
                        priority=section.priority,
                        source_rfp_section=section.source_rfp_section,
                    )
                    result.append(sub)
                    next_section_num += 1
                    logger.debug(
                        f"[C1]   Created {sub.section_id}: "
                        f"{sub.title} ({len(chunk)} reqs)"
                    )
            else:
                # Create a sub-section per category group
                for cat, req_ids in sorted(category_groups.items()):
                    label = _CAT_LABELS.get(cat, cat.title())
                    sub = ResponseSection(
                        section_id=f"SEC-{next_section_num:02d}",
                        title=f"{section.title} — {label}",
                        section_type="requirement_driven",
                        description=(
                            f"{section.description} "
                            f"Focus on {label.lower()} requirements."
                        ),
                        content_guidance=section.content_guidance,
                        requirement_ids=req_ids,
                        mapped_capabilities=section.mapped_capabilities,
                        priority=section.priority,
                        source_rfp_section=section.source_rfp_section,
                    )
                    result.append(sub)
                    next_section_num += 1
                    logger.debug(
                        f"[C1]   Created {sub.section_id}: "
                        f"{sub.title} ({len(req_ids)} reqs)"
                    )

                    # Recursively split if still overloaded
                    if len(req_ids) > _MAX_REQS_PER_SECTION:
                        logger.info(
                            f"[C1] Sub-section {sub.section_id} still "
                            f"overloaded ({len(req_ids)} reqs) — "
                            f"will be split again"
                        )

        # Second pass: split any sub-sections still over limit
        final: list[ResponseSection] = []
        for section in result:
            if (
                section.section_type == "requirement_driven"
                and len(section.requirement_ids) > _MAX_REQS_PER_SECTION
            ):
                reqs = section.requirement_ids
                chunk_size = _MAX_REQS_PER_SECTION
                for i in range(0, len(reqs), chunk_size):
                    chunk = reqs[i : i + chunk_size]
                    part_num = i // chunk_size + 1
                    sub = ResponseSection(
                        section_id=f"SEC-{next_section_num:02d}",
                        title=f"{section.title} (Part {part_num})",
                        section_type=section.section_type,
                        description=section.description,
                        content_guidance=section.content_guidance,
                        requirement_ids=chunk,
                        mapped_capabilities=section.mapped_capabilities,
                        priority=section.priority,
                        source_rfp_section=section.source_rfp_section,
                    )
                    final.append(sub)
                    next_section_num += 1
            else:
                final.append(section)

        return final

    def _enforce_section_types(
        self, sections: list[ResponseSection]
    ) -> list[ResponseSection]:
        """Ensure commercial/legal sections have correct section_type
        regardless of what the LLM returned.
        
        Only overrides when the section title clearly indicates it is
        a commercial or legal section (not merely mentioning compliance
        in a security context, for example).
        """
        _COMMERCIAL_KEYWORDS = {"commercial", "pricing", "cost proposal", "financial proposal", "price schedule"}
        _LEGAL_KEYWORDS = {
            "legal", "contract", "contractual",
            "terms and conditions", "terms & conditions",
            "legal & compliance", "legal and compliance",
        }

        for section in sections:
            title_lower = section.title.lower()
            if any(kw in title_lower for kw in _COMMERCIAL_KEYWORDS):
                if section.section_type != "commercial":
                    logger.info(
                        f"[C1] Overriding section_type for '{section.title}': "
                        f"{section.section_type} → commercial"
                    )
                    section.section_type = "commercial"
            elif any(kw in title_lower for kw in _LEGAL_KEYWORDS):
                if section.section_type != "legal":
                    logger.info(
                        f"[C1] Overriding section_type for '{section.title}': "
                        f"{section.section_type} → legal"
                    )
                    section.section_type = "legal"
        return sections

    def _enrich_sections_with_capabilities(
        self,
        mcp: MCPService,
        requirements: list[dict[str, Any]],
        sections: list[ResponseSection],
    ) -> list[ResponseSection]:
        """Pass 2: Enrich each section with relevant capabilities from KB.

        By querying the Knowledge Store per-section using the section's
        specific requirements and title, we get highly relevant capabilities
        and keep the total token budget under control.
        """
        # Create a lookup for requirement text
        req_lookup = {r.get("requirement_id"): r for r in requirements}

        for section in sections:
            queries: set[str] = set()

            # 1. Query by section title and description
            if section.title:
                queries.add(f"{section.title} capabilities solutions experience")
            if section.description:
                # Use first few words of description
                desc_prefix = " ".join(section.description.split()[:10])
                queries.add(desc_prefix)

            # 2. Query by requirement categories and key phrases
            cats = set()
            for rid in section.requirement_ids:
                req = req_lookup.get(rid, {})
                if req.get("category"):
                    cats.add(req["category"])
                # Add requirement text snippet if available
                text = req.get("text", "")
                if text:
                    # Take first 6-8 words
                    snippet = " ".join(text.split()[:8])
                    if len(snippet) > 15:
                        queries.add(snippet)

            for cat in cats:
                queries.add(f"{cat} capabilities features")

            # Execute queries and collect unique capabilities
            seen_texts: set[str] = set()
            section_caps: list[str] = []

            # Limit to top 3-4 queries to avoid excessive DB calls
            top_queries = list(queries)[:4]
            for query in top_queries:
                try:
                    results = mcp.query_knowledge(query, top_k=3)
                    for r in results:
                        text = r.get("text", "")
                        if text and text not in seen_texts:
                            seen_texts.add(text)
                            # Create a clean string representation for the prompt
                            preview = text[:600]
                            if len(text) > 600:
                                preview += "..."
                            meta = r.get("metadata", {})
                            source = meta.get("category") or meta.get("id") or "Knowledge Base"
                            section_caps.append(f"[{source}] {preview}")
                except Exception as exc:
                    logger.warning(
                        f"[C1] Knowledge query failed for section "
                        f"{section.section_id} query '{query}': {exc}"
                    )

            # Keep only the most relevant ones (top 5 max per section)
            # to keep Prompt Token usage safe in C2
            section.mapped_capabilities = section_caps[:5]
            if section_caps:
                logger.debug(
                    f"[C1] Enriched {section.section_id} with "
                    f"{len(section.mapped_capabilities)} capabilities"
                )

        return sections


    def _gap_fill_pass(
        self,
        sections: list[ResponseSection],
        gap_req_lines: list[str],
        pass_num: int,
    ) -> list[ResponseSection]:
        """
        Run a focused LLM call to assign unassigned requirements to
        existing sections. Much lighter than the full architecture prompt,
        so all remaining requirements can fit.
        """
        # Build existing sections summary for context
        section_summary_lines = []
        for s in sections:
            if s.section_type == "requirement_driven":
                section_summary_lines.append(
                    f"  {s.section_id}: {s.title} "
                    f"(currently has {len(s.requirement_ids)} requirements)"
                )

        section_summary = "\n".join(section_summary_lines)
        gap_requirements = "\n".join(gap_req_lines)

        prompt = (
            "You are assigning unassigned RFP requirements to existing proposal sections.\n\n"
            "## Existing Sections (requirement-driven only)\n\n"
            f"{section_summary}\n\n"
            "## Unassigned Requirements\n"
            "Format: REQUIREMENT_ID | TYPE | CLASSIFICATION | Requirement text\n\n"
            f"{gap_requirements}\n\n"
            "## Instructions\n\n"
            "For EACH unassigned requirement above, assign it to the most appropriate "
            "existing section. Use the section_id from the list above.\n\n"
            "Rules:\n"
            "- SLA/performance metrics (availability, latency, uptime, jitter, packet loss, "
            "response time, RPO, RTO) → assign to the SLA section\n"
            "- Security/compliance requirements → assign to the Compliance section\n"
            "- Technical capabilities → assign to the Technical Solution section\n"
            "- If no existing section fits, assign to the Compliance Matrix as a catch-all\n"
            "- Every requirement MUST be assigned to exactly one section\n\n"
            "Return ONLY a JSON object mapping section_id to a list of requirement IDs:\n"
            "```json\n"
            '{\n'
            '  "assignments": {\n'
            '    "SEC-03": ["REQ-0050", "REQ-0051"],\n'
            '    "SEC-04": ["REQ-0067", "REQ-0068"],\n'
            '    "SEC-05": ["REQ-0089", "REQ-0090"]\n'
            '  }\n'
            '}\n'
            "```\n\n"
            "Return ONLY the JSON object, no additional text."
        )

        logger.debug(
            f"[C1] Gap-fill pass {pass_num} prompt: {len(prompt)} chars, "
            f"{len(gap_req_lines)} requirements to assign"
        )

        try:
            raw_response = llm_text_call(prompt, deterministic=True)
            logger.debug(
                f"[C1] Gap-fill pass {pass_num} response: "
                f"{len(raw_response)} chars"
            )

            # Parse the assignments
            assignments = self._parse_gap_assignments(raw_response)
            if not assignments:
                logger.warning(
                    f"[C1] Gap-fill pass {pass_num}: no valid assignments parsed"
                )
                return sections

            # Merge assignments into existing sections
            total_assigned = 0
            section_map = {s.section_id: s for s in sections}

            for section_id, req_ids in assignments.items():
                section = section_map.get(section_id)
                if section:
                    existing_ids = set(section.requirement_ids)
                    new_ids = [rid for rid in req_ids if rid not in existing_ids]
                    section.requirement_ids.extend(new_ids)
                    total_assigned += len(new_ids)
                    if new_ids:
                        logger.debug(
                            f"[C1] Gap-fill: added {len(new_ids)} requirements "
                            f"to {section_id} ({section.title})"
                        )
                else:
                    logger.warning(
                        f"[C1] Gap-fill: unknown section_id '{section_id}', "
                        f"skipping {len(req_ids)} requirements"
                    )

            logger.info(
                f"[C1] Gap-fill pass {pass_num}: assigned {total_assigned} "
                f"requirements across sections"
            )

        except Exception as exc:
            logger.error(f"[C1] Gap-fill pass {pass_num} failed: {exc}")

        return sections

    def _parse_gap_assignments(
        self, raw_response: str
    ) -> dict[str, list[str]]:
        """Parse gap-filling LLM response into section_id -> [req_ids] mapping."""
        text = raw_response.strip()

        # Strip markdown fences
        fence_match = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?\s*```",
            text,
            re.DOTALL,
        )
        if fence_match:
            text = fence_match.group(1).strip()

        # Extract JSON object
        data = self._extract_json(text)

        if isinstance(data, dict):
            assignments = data.get("assignments", data)
            if isinstance(assignments, dict):
                result: dict[str, list[str]] = {}
                for section_id, req_ids in assignments.items():
                    if isinstance(req_ids, list):
                        result[section_id] = [
                            str(rid) for rid in req_ids
                        ]
                return result

        logger.warning("[C1] Could not parse gap-fill assignments")
        return {}

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
