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
_MAX_REQS_PER_SECTION = 20
_TABLE_TECH_REQ_ID_RE = re.compile(r"^TR-\d{3}$", re.IGNORECASE)
_TABLE_PRICING_REQ_ID_RE = re.compile(r"^\d+\.\d{2}$")
_TABLE_APPENDIX_REQ_ID_RE = re.compile(r"^CM-\d{2}$", re.IGNORECASE)
_MERGED_TECH_SECTION_TITLE = "Technical Implementation"
_TECHNICAL_NARRATIVE_TITLE = "Technical Implementation Narrative"
_PRICING_MATRIX_TITLE = "Pricing Schedule Matrix"
_APPENDIX_TABLES_TITLE = "Appendix Forms & Declarations"
_SECTION_TITLE_NORMALIZATION: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^technical implementation$", re.IGNORECASE), "Technical Implementation — Technical Compliance Matrix"),
    (re.compile(r"^technical solution narrative$", re.IGNORECASE), "Technical Implementation — Solution Narrative"),
    (re.compile(r"sd-wan|network & edge", re.IGNORECASE), "Technical Implementation — Network & Edge Architecture"),
    (re.compile(r"cloud interconnect", re.IGNORECASE), "Technical Implementation — Cloud Interconnect"),
    (re.compile(r"managed security operations|soc", re.IGNORECASE), "Technical Implementation — Managed Security Operations"),
    (re.compile(r"iot|mobility", re.IGNORECASE), "Technical Implementation — IoT & Mobility"),
    (re.compile(r"^compliance & regulatory framework$", re.IGNORECASE), "Governance & Compliance — Compliance Framework"),
    (re.compile(r"^operational support & slas?$", re.IGNORECASE), "Service Management — Operations & SLA Commitments"),
    (re.compile(r"^implementation & migration plan$", re.IGNORECASE), "Delivery Approach — Implementation & Migration"),
)


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
            req_text = d.get("text", str(d))[:120]  # keep C1 under Groq TPM limits
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
        sections = self._normalize_vendor_fill_sections(
            requirements_data, sections
        )

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
            summary = self._truncate_at_word(summary, 180)
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

        try:
            result_sets = mcp.query_rfp_batch(queries, rfp_id, top_k=5)
            for query, results in zip(queries, result_sets):
                for r in results:
                    text = r.get("text", "").strip()
                    if text and text not in seen:
                        seen.add(text)
                        all_texts.append(text)
        except Exception as exc:
            logger.warning(f"[C1] Batched RFP submission-instruction query failed: {exc}")
            for query in queries:
                try:
                    results = mcp.query_rfp(query, rfp_id, top_k=5)
                    for r in results:
                        text = r.get("text", "").strip()
                        if text and text not in seen:
                            seen.add(text)
                            all_texts.append(text)
                except Exception as inner_exc:
                    logger.warning(f"[C1] RFP query failed for '{query}': {inner_exc}")

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

        unique_queries = list(dict.fromkeys(queries))
        try:
            result_sets = mcp.query_knowledge_batch(unique_queries, top_k=5)
            for query, results in zip(unique_queries, result_sets):
                for r in results:
                    text = r.get("text", "")
                    if text and text not in seen_texts:
                        seen_texts.add(text)
                        all_capabilities.append({
                            "text": text,
                            "metadata": r.get("metadata", {}),
                        })
        except Exception as exc:
            logger.warning(f"[C1] Batched knowledge query failed: {exc}")
            for query in unique_queries:
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
                except Exception as inner_exc:
                    logger.warning(f"[C1] Knowledge query failed for '{query}': {inner_exc}")

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
        # Groq on-demand for qwen/qwen3-32b hard-fails once a single request
        # gets near the 6K TPM ceiling, so stay comfortably below that.
        total_token_budget = min(settings.llm_max_tokens, 5200)
        output_reserve = 1200  # JSON response remains small in practice
        template_tokens = len(template) // chars_per_token + 200  # ~1,950 tokens
        feedback_reserve = 250 if review_feedback else 0
        data_budget_tokens = total_token_budget - output_reserve - template_tokens - feedback_reserve
        data_budget_chars = max(data_budget_tokens * chars_per_token, 4000)

        # Proportional allocation: requirements 50%, sections 22%, capabilities 13%, submission 15%
        budget_reqs = int(data_budget_chars * 0.50)
        budget_sections = int(data_budget_chars * 0.22)
        budget_caps = int(data_budget_chars * 0.13)
        budget_sub = int(data_budget_chars * 0.15)

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
                + self._truncate_at_word(review_feedback, 800)
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
                visual_relevance = str(item.get("visual_relevance", "auto") or "auto").lower()
                if visual_relevance not in {"auto", "none", "optional", "required"}:
                    visual_relevance = "auto"
                visual_type_hint = str(item.get("visual_type_hint", "") or "").strip().lower()
                raw_source_terms = item.get("visual_source_terms", [])
                if isinstance(raw_source_terms, list):
                    visual_source_terms = [str(term).strip() for term in raw_source_terms if str(term).strip()]
                elif raw_source_terms:
                    visual_source_terms = [str(raw_source_terms).strip()]
                else:
                    visual_source_terms = []

                section = ResponseSection(
                    section_id=item.get("section_id", f"SEC-{i + 1:02d}"),
                    title=item.get("title", item.get("section_title", "Untitled")),
                    section_type=section_type,
                    description=item.get("description", ""),
                    content_guidance=item.get("content_guidance", ""),
                    visual_relevance=visual_relevance,
                    visual_type_hint=visual_type_hint,
                    visual_notes=item.get("visual_notes", ""),
                    visual_source_terms=visual_source_terms,
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

            # We need the table regex here as well
            _TABLE_TITLE_RE = re.compile(
                r'\b(?:matrix|table|compliance|checklist|questionnaire)\b',
                re.IGNORECASE,
            )

            for s in req_driven:
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

            # Assign to best match, or a category-specific catch-all
            target = best_section if best_score >= 2 else None

            if not target:
                append_title = "Appendix: Additional Compliance"
                
                # Check if we already have this appendix
                for s in sections:
                    if s.title == append_title:
                        target = s.section_id
                        break
                
                if not target:
                    # Create appendix section
                    catch_all_id = f"SEC-{len(sections) + 1:02d}"
                    catch_all = ResponseSection(
                        section_id=catch_all_id,
                        title=append_title,
                        section_type="requirement_driven",
                        description="Additional requirements mapped to an appendix to preserve main proposal flow",
                        priority=10,
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
        Bypass programmatic splitting entirely. 
        The writing agent now handles transparent chunking of large sections
        to avoid injecting ugly "(Part X)" or category suffixes into the user's PDF.
        """
        logger.info("[C1] Bypassing programmatic section splitting. Sections will remain intact.")
        return sections

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
            if (
                any(kw in title_lower for kw in _COMMERCIAL_KEYWORDS)
                and not any(kw in title_lower for kw in ("matrix", "schedule"))
            ):
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

    def _normalize_vendor_fill_sections(
        self,
        requirements: list[dict[str, Any]],
        sections: list[ResponseSection],
    ) -> list[ResponseSection]:
        """Preserve original vendor-fill tables in dedicated sections."""
        if not sections:
            return sections

        req_map = {
            str(req.get("requirement_id", "")).strip(): req
            for req in requirements
            if req.get("requirement_id")
        }

        technical_table_ids = sorted(
            rid for rid in req_map
            if _TABLE_TECH_REQ_ID_RE.match(rid)
        )
        pricing_table_ids = sorted(
            rid for rid in req_map
            if _TABLE_PRICING_REQ_ID_RE.match(rid)
        )
        appendix_table_ids = sorted(
            rid for rid in req_map
            if _TABLE_APPENDIX_REQ_ID_RE.match(rid)
        )

        sections = self._merge_technical_sections(
            sections,
            set(technical_table_ids),
        )
        sections = self._reassign_requirement_ids(
            sections=sections,
            target_title=_MERGED_TECH_SECTION_TITLE,
            requirement_ids=technical_table_ids,
            description=(
                "Primary technical implementation section. Reproduce the exact "
                "technical requirement matrix from the RFP as one consolidated "
                "table and support it with the architecture narrative."
            ),
            content_guidance=(
                "Keep all table-backed technical requirements together in a single "
                "Technical Implementation section. Do not split the matrix by "
                "workstream or platform."
            ),
            priority=4,
        )
        sections = self._reassign_requirement_ids(
            sections=sections,
            target_title=_PRICING_MATRIX_TITLE,
            requirement_ids=pricing_table_ids,
            description=(
                "Exact pricing schedule from the RFP. Preserve the original row "
                "IDs and vendor-fill columns."
            ),
            content_guidance=(
                "Reproduce the original pricing table exactly. Keep line IDs such "
                "as 1.01, 2.01, 4.04, and 5.03 unchanged."
            ),
            priority=90,
        )
        sections = self._reassign_requirement_ids(
            sections=sections,
            target_title=_APPENDIX_TABLES_TITLE,
            requirement_ids=appendix_table_ids,
            description=(
                "Appendix declarations, compliance matrices, and other small "
                "vendor-fill tables that belong in the appendices."
            ),
            content_guidance=(
                "Keep appendix declaration tables together. Preserve exact row IDs "
                "and fill only the vendor-input cells."
            ),
            priority=95,
        )
        sections = self._drop_empty_requirement_sections(sections)
        return self._normalize_section_titles(sections)

    def _merge_technical_sections(
        self,
        sections: list[ResponseSection],
        technical_table_ids: set[str],
    ) -> list[ResponseSection]:
        """Replace fragmented domain sections with one Technical Implementation section."""
        if not technical_table_ids:
            return sections

        tech_keywords = (
            "sd-wan",
            "cloud interconnect",
            "managed security operations center",
            "managed security operations centre",
            "mobility",
            "operational support",
            "technical solution",
            "architecture",
            "soc",
        )

        merged_ids: list[str] = []
        merged_descriptions: list[str] = []
        merged_guidance: list[str] = []
        keep: list[ResponseSection] = []
        technical_section: ResponseSection | None = None

        for section in sections:
            title_lower = section.title.lower()
            is_target = section.title == _MERGED_TECH_SECTION_TITLE
            is_fragment = (
                section.section_type == "requirement_driven"
                and any(keyword in title_lower for keyword in tech_keywords)
                and section.title not in {_PRICING_MATRIX_TITLE, _APPENDIX_TABLES_TITLE}
            )
            table_ids_here = [
                rid for rid in section.requirement_ids
                if rid in technical_table_ids
            ]
            leftover_ids = [
                rid for rid in section.requirement_ids
                if rid not in technical_table_ids
            ]

            if is_target or (is_fragment and table_ids_here):
                if technical_section is None:
                    technical_section = ResponseSection(
                        section_id=section.section_id,
                        title=_MERGED_TECH_SECTION_TITLE,
                        section_type="requirement_driven",
                        description=section.description,
                        content_guidance=section.content_guidance,
                        requirement_ids=list(table_ids_here),
                        mapped_capabilities=[],
                        priority=min(getattr(section, "priority", 4), 4),
                        source_rfp_section=section.source_rfp_section,
                    )
                else:
                    for rid in table_ids_here:
                        if rid not in technical_section.requirement_ids:
                            technical_section.requirement_ids.append(rid)
                if section.description:
                    merged_descriptions.append(section.description)
                if section.content_guidance:
                    merged_guidance.append(section.content_guidance)
                merged_ids.extend(table_ids_here)
                if leftover_ids:
                    fallback_title = (
                        _TECHNICAL_NARRATIVE_TITLE if is_target else section.title
                    )
                    keep.append(
                        section.model_copy(
                            update={
                                "section_id": self._next_section_id(
                                    keep + sections + ([technical_section] if technical_section else [])
                                ),
                                "title": fallback_title,
                                "requirement_ids": leftover_ids,
                            }
                        )
                    )
                continue

            keep.append(section)

        if technical_section is None:
            return sections

        technical_section.requirement_ids = list(dict.fromkeys(merged_ids))
        technical_section.description = " ".join(
            part for part in dict.fromkeys(merged_descriptions) if part
        ).strip() or technical_section.description
        technical_section.content_guidance = " ".join(
            part for part in dict.fromkeys(merged_guidance) if part
        ).strip() or technical_section.content_guidance

        keep.append(technical_section)
        keep.sort(key=lambda sec: sec.priority)
        return keep

    def _reassign_requirement_ids(
        self,
        sections: list[ResponseSection],
        target_title: str,
        requirement_ids: list[str],
        description: str,
        content_guidance: str,
        priority: int,
    ) -> list[ResponseSection]:
        """Move the supplied requirement IDs into a dedicated section."""
        if not requirement_ids:
            return sections

        req_id_set = {rid for rid in requirement_ids if rid}
        target_section: ResponseSection | None = None

        for section in sections:
            if section.title == target_title:
                target_section = section
                break

        if target_section is None:
            target_section = ResponseSection(
                section_id=self._next_section_id(sections),
                title=target_title,
                section_type="requirement_driven",
                description=description,
                content_guidance=content_guidance,
                requirement_ids=[],
                priority=priority,
            )
            sections.append(target_section)

        for section in sections:
            if section.section_id == target_section.section_id:
                continue
            section.requirement_ids = [
                rid for rid in section.requirement_ids
                if rid not in req_id_set
            ]

        merged_ids = list(target_section.requirement_ids)
        for rid in requirement_ids:
            if rid not in merged_ids:
                merged_ids.append(rid)
        target_section.requirement_ids = merged_ids
        target_section.section_type = "requirement_driven"
        target_section.description = description
        target_section.content_guidance = content_guidance
        target_section.priority = priority

        sections.sort(key=lambda sec: sec.priority)
        return sections

    @staticmethod
    def _next_section_id(sections: list[ResponseSection]) -> str:
        used_numbers = {
            int(match.group(1))
            for section in sections
            for match in [re.match(r"SEC-(\d+)", section.section_id)]
            if match
        }
        next_number = 1
        while next_number in used_numbers:
            next_number += 1
        return f"SEC-{next_number:02d}"

    @staticmethod
    def _drop_empty_requirement_sections(
        sections: list[ResponseSection],
    ) -> list[ResponseSection]:
        """Remove fragmented requirement-driven sections left empty after normalization."""
        cleaned: list[ResponseSection] = []
        for section in sections:
            if (
                section.section_type == "requirement_driven"
                and not section.requirement_ids
                and section.title not in {
                    "Executive Summary",
                    _MERGED_TECH_SECTION_TITLE,
                    _PRICING_MATRIX_TITLE,
                    _APPENDIX_TABLES_TITLE,
                }
            ):
                continue
            cleaned.append(section)
        cleaned.sort(key=lambda sec: sec.priority)
        return cleaned

    @staticmethod
    def _normalize_section_titles(
        sections: list[ResponseSection],
    ) -> list[ResponseSection]:
        """Rename overly specific top-level sections into broader parent/subsection titles."""
        normalized: list[ResponseSection] = []
        seen_titles: set[str] = set()

        for section in sections:
            title = section.title.strip()
            new_title = title
            for pattern, replacement in _SECTION_TITLE_NORMALIZATION:
                if pattern.search(title):
                    new_title = replacement
                    break

            candidate = section.model_copy(update={"title": new_title})
            if candidate.title in seen_titles:
                continue
            seen_titles.add(candidate.title)
            normalized.append(candidate)

        normalized.sort(key=lambda sec: sec.priority)
        return normalized

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

        section_queries: list[tuple[ResponseSection, list[str]]] = []
        unique_queries: list[str] = []
        query_to_results: dict[str, list[dict[str, Any]]] = {}

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

            top_queries = list(queries)[:4]
            section_queries.append((section, top_queries))
            for query in top_queries:
                if query not in query_to_results:
                    unique_queries.append(query)
                    query_to_results[query] = []

        try:
            result_sets = mcp.query_knowledge_batch(unique_queries, top_k=3)
            for query, results in zip(unique_queries, result_sets):
                query_to_results[query] = results
        except Exception as exc:
            logger.warning(f"[C1] Batched section-enrichment query failed: {exc}")
            for query in unique_queries:
                try:
                    query_to_results[query] = mcp.query_knowledge(query, top_k=3)
                except Exception as inner_exc:
                    logger.warning(
                        f"[C1] Knowledge query failed for enrich query '{query}': {inner_exc}"
                    )

        for section, top_queries in section_queries:
            seen_texts: set[str] = set()
            section_caps: list[str] = []
            for query in top_queries:
                try:
                    results = query_to_results.get(query, [])
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
