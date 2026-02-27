"""
C1 — Architecture Planning Agent
Responsibility: Group validated requirements into response sections, map each
                to company capabilities via Knowledge Store, verify every
                mandatory requirement appears in the plan.

Inputs:
  - requirements_validation.validated_requirements (from B2)
  - Falls back to requirements (raw B1 output) if B2 returned empty
  - Company capabilities from MCP Knowledge Store

Outputs:
  - architecture_plan: ArchitecturePlan with ResponseSection list
  - status → WRITING_RESPONSES
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from rfp_automation.agents.base_agent import BaseAgent
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
        # Prefer validated requirements from B2; fall back to raw B1
        requirements = state.requirements_validation.validated_requirements
        if not requirements:
            requirements = state.requirements
            logger.debug("[C1] Using raw B1 requirements (B2 validated list empty)")
        else:
            logger.debug(f"[C1] Using {len(requirements)} validated requirements from B2")

        if not requirements:
            logger.warning("[C1] No requirements available — producing empty plan")
            state.architecture_plan = ArchitecturePlan(
                sections=[],
                coverage_gaps=[],
                total_sections=0,
            )
            state.status = PipelineStatus.WRITING_RESPONSES
            return state

        # Serialize requirements for prompt
        requirements_data = []
        for req in requirements:
            if hasattr(req, "model_dump"):
                requirements_data.append(req.model_dump())
            elif isinstance(req, dict):
                requirements_data.append(req)
            else:
                requirements_data.append({"text": str(req)})

        requirements_json = json.dumps(requirements_data, indent=2, default=str)
        logger.debug(f"[C1] Serialized {len(requirements_data)} requirements ({len(requirements_json)} chars)")

        # ── 3. Query MCP Knowledge Store for capabilities ─
        mcp = MCPService()
        capabilities = self._fetch_capabilities(mcp, requirements_data)
        capabilities_json = json.dumps(capabilities, indent=2, default=str) if capabilities else "No company capabilities available."
        logger.debug(f"[C1] Fetched {len(capabilities)} capability entries")

        # ── 4. Build prompt ─────────────────────────────
        prompt = self._build_prompt(requirements_json, capabilities_json)
        logger.debug(f"[C1] Prompt built — {len(prompt)} chars")

        # ── 5. Call LLM ─────────────────────────────────
        logger.info(f"[C1] Calling LLM with {len(requirements_data)} requirements, {len(capabilities)} capabilities")
        raw_response = llm_text_call(prompt, deterministic=True)
        logger.debug(f"[C1] Raw LLM response ({len(raw_response)} chars):\n{raw_response[:2000]}")

        # ── 6. Parse response ───────────────────────────
        sections = self._parse_sections(raw_response)
        logger.info(f"[C1] Parsed {len(sections)} response sections")
        for s in sections:
            logger.debug(
                f"[C1]   Section: {s.section_id} | {s.title} | "
                f"{len(s.requirement_ids)} reqs | {len(s.mapped_capabilities)} caps | "
                f"priority={s.priority}"
            )

        # ── 7. Coverage gap detection ───────────────────
        coverage_gaps = self._detect_coverage_gaps(requirements_data, sections)
        if coverage_gaps:
            logger.warning(f"[C1] Coverage gaps — {len(coverage_gaps)} mandatory requirements unassigned: {coverage_gaps}")
        else:
            logger.info("[C1] Full coverage — all mandatory requirements assigned to sections")

        # ── 8. Build result and update state ────────────
        plan = ArchitecturePlan(
            sections=sections,
            coverage_gaps=coverage_gaps,
            total_sections=len(sections),
        )
        state.architecture_plan = plan
        state.status = PipelineStatus.WRITING_RESPONSES

        logger.info(
            f"[C1] Architecture plan complete — {plan.total_sections} sections, "
            f"{len(coverage_gaps)} coverage gaps"
        )

        return state

    # ── Helpers ──────────────────────────────────────────

    def _fetch_capabilities(
        self,
        mcp: MCPService,
        requirements: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Query the Knowledge Store for company capabilities relevant to
        the requirement set. Uses category-based queries to get broad
        coverage, then deduplicates.
        """
        # Collect unique categories from requirements
        categories = set()
        for req in requirements:
            cat = req.get("category", "")
            if cat:
                categories.add(cat.lower())

        # Always include a general capabilities query
        queries = ["company capabilities services products solutions"]
        for cat in categories:
            queries.append(f"{cat} capabilities solutions experience")

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

    def _build_prompt(self, requirements: str, capabilities: str) -> str:
        """Load the prompt template and inject requirements + capabilities."""
        template = _PROMPT_PATH.read_text(encoding="utf-8")
        return (
            template
            .replace("{requirements}", requirements[:15_000])
            .replace("{capabilities}", capabilities[:10_000])
        )

    def _parse_sections(self, raw_response: str) -> list[ResponseSection]:
        """
        Parse the LLM JSON response into a list of ResponseSection.
        Handles markdown fencing, extra text around JSON.
        """
        text = raw_response.strip()

        # Strip markdown code fences
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        # Try to extract JSON array
        try:
            start = text.index("[")
            end = text.rindex("]") + 1
            text = text[start:end]
        except ValueError:
            # Maybe the LLM returned a JSON object with a "sections" key
            try:
                start = text.index("{")
                end = text.rindex("}") + 1
                obj = json.loads(text[start:end])
                if isinstance(obj, dict) and "sections" in obj:
                    return self._build_sections(obj["sections"])
            except (ValueError, json.JSONDecodeError):
                pass
            logger.warning("[C1] No JSON array or object found in LLM response")
            return []

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning(f"[C1] JSON parse error: {exc}")
            return []

        if isinstance(data, list):
            return self._build_sections(data)
        elif isinstance(data, dict) and "sections" in data:
            return self._build_sections(data["sections"])

        logger.warning("[C1] Unexpected JSON structure in LLM response")
        return []

    def _build_sections(self, items: list[dict[str, Any]]) -> list[ResponseSection]:
        """Build ResponseSection objects from parsed JSON items."""
        sections: list[ResponseSection] = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                logger.warning(f"[C1] Skipping non-dict section item {i}")
                continue
            try:
                section = ResponseSection(
                    section_id=item.get("section_id", f"SEC-{i + 1:02d}"),
                    title=item.get("title", item.get("section_title", "Untitled")),
                    requirement_ids=item.get("requirement_ids", item.get("assigned_requirements", [])),
                    mapped_capabilities=item.get("mapped_capabilities", item.get("key_technologies", [])),
                    priority=int(item.get("priority", i + 1)),
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
        Find mandatory requirement IDs not assigned to any section.
        Returns list of unassigned requirement IDs.
        """
        # Collect all mandatory requirement IDs
        mandatory_ids: set[str] = set()
        for req in requirements:
            req_type = req.get("type", "MANDATORY")
            if isinstance(req_type, str) and req_type.upper() == "MANDATORY":
                req_id = req.get("requirement_id", "")
                if req_id:
                    mandatory_ids.add(req_id)

        # Collect all assigned requirement IDs across sections
        assigned_ids: set[str] = set()
        for section in sections:
            assigned_ids.update(section.requirement_ids)

        # Gap = mandatory IDs not in any section
        gaps = sorted(mandatory_ids - assigned_ids)
        return gaps
