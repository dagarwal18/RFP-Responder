"""
B1 — Requirements Extraction Agent
Responsibility: Extract every requirement from the RFP, classify by type,
                category, and impact, and assign unique IDs.

Reads approved sections from A2 Structuring, fetches relevant chunks from
the MCP vector store, then calls the LLM per-section to extract requirements.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.mcp import MCPService
from rfp_automation.models.enums import (
    AgentName,
    PipelineStatus,
    RequirementType,
    RequirementClassification,
    RequirementCategory,
    ImpactLevel,
)
from rfp_automation.models.schemas import Requirement
from rfp_automation.models.state import RFPGraphState
from rfp_automation.services.llm_service import llm_text_call

logger = logging.getLogger(__name__)

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "extraction_prompt.txt"
)

# Minimum section confidence to consider for extraction
_MIN_SECTION_CONFIDENCE = 0.5


class RequirementsExtractionAgent(BaseAgent):
    name = AgentName.B1_REQUIREMENTS_EXTRACTION

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        rfp_id = state.rfp_metadata.rfp_id
        if not rfp_id:
            raise ValueError("No rfp_id in state — A1 Intake must run first")

        logger.info(f"[B1] Starting requirements extraction for {rfp_id}")

        # ── 1. Gather approved sections ─────────────────────
        sections = [
            s
            for s in state.structuring_result.sections
            if s.confidence >= _MIN_SECTION_CONFIDENCE
        ]
        logger.info(
            f"[B1] {len(sections)} sections with confidence >= "
            f"{_MIN_SECTION_CONFIDENCE} (of {len(state.structuring_result.sections)} total)"
        )

        if not sections:
            logger.warning("[B1] No qualifying sections — producing 0 requirements")
            state.requirements = []
            state.status = PipelineStatus.VALIDATING_REQUIREMENTS
            return state

        # ── 2. Load prompt template ─────────────────────────
        template = _PROMPT_PATH.read_text(encoding="utf-8")

        # ── 3. Per-section extraction via LLM ───────────────
        mcp = MCPService()
        all_requirements: list[Requirement] = []
        global_id_counter = 1

        for section in sections:
            # Fetch relevant chunks from MCP for this section
            chunks = mcp.query_rfp(section.title, rfp_id, top_k=10)
            chunk_text = "\n\n".join(
                c.get("text", "") for c in chunks if c.get("text")
            )

            # Use content_summary + chunk content as context
            section_content = section.content_summary
            if chunk_text.strip():
                section_content += "\n\n--- Additional Context ---\n" + chunk_text

            # Build prompt
            start_id = f"REQ-{global_id_counter:03d}"
            prompt = template.format(
                section_title=section.title,
                section_content=section_content[:8000],
                start_id=start_id,
            )

            logger.debug(
                f"[B1] Extracting from section '{section.title}' "
                f"({len(section_content)} chars, start_id={start_id})"
            )

            # Call LLM
            try:
                raw_response = llm_text_call(prompt)
                logger.debug(
                    f"[B1] LLM response for '{section.title}': "
                    f"{len(raw_response)} chars"
                )
            except Exception as exc:
                logger.error(
                    f"[B1] LLM call failed for section '{section.title}': {exc}"
                )
                continue

            # Parse into Requirement objects
            parsed = self._parse_requirements_json(
                raw_response, section.title, global_id_counter
            )
            logger.info(
                f"[B1] Extracted {len(parsed)} requirements from "
                f"'{section.title}'"
            )
            for req in parsed:
                logger.debug(
                    f"[B1]   {req.requirement_id} | {req.classification.value} | "
                    f"{req.category.value} | {req.impact.value} | "
                    f"{req.text[:60]}"
                )

            global_id_counter += len(parsed)
            all_requirements.extend(parsed)

        # ── 4. Deduplicate ──────────────────────────────────
        before_dedup = len(all_requirements)
        all_requirements = self._deduplicate(all_requirements)
        logger.info(
            f"[B1] Deduplicated: {before_dedup} → {len(all_requirements)} requirements"
        )

        # ── 5. Re-assign sequential IDs after dedup ─────────
        for i, req in enumerate(all_requirements, start=1):
            req.requirement_id = f"REQ-{i:03d}"

        # ── 6. Update state ─────────────────────────────────
        state.requirements = all_requirements
        state.status = PipelineStatus.VALIDATING_REQUIREMENTS

        func_count = sum(1 for r in all_requirements if r.classification == RequirementClassification.FUNCTIONAL)
        nonfunc_count = sum(1 for r in all_requirements if r.classification == RequirementClassification.NON_FUNCTIONAL)
        logger.info(
            f"[B1] Extraction complete: {len(all_requirements)} requirements "
            f"(Functional: {func_count}, Non-Functional: {nonfunc_count})"
        )
        return state

    # ── JSON parsing ─────────────────────────────────────────

    def _parse_requirements_json(
        self,
        raw_response: str,
        source_section: str,
        start_id: int,
    ) -> list[Requirement]:
        """Parse LLM JSON response into a list of Requirement objects."""
        text = raw_response.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        # Extract JSON array
        try:
            start = text.index("[")
            end = text.rindex("]") + 1
            text = text[start:end]
        except ValueError:
            logger.warning("[B1] No JSON array found in LLM response")
            return []

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning(f"[B1] JSON parse error: {exc}")
            return []

        if not isinstance(data, list):
            logger.warning("[B1] LLM response is not a JSON array")
            return []

        # Build Requirement objects
        requirements: list[Requirement] = []
        for i, item in enumerate(data):
            try:
                req = Requirement(
                    requirement_id=item.get(
                        "requirement_id", f"REQ-{start_id + i:03d}"
                    ),
                    text=item.get("text", ""),
                    type=self._normalize_type(item.get("type", "MANDATORY")),
                    classification=self._normalize_classification(
                        item.get("classification", "FUNCTIONAL")
                    ),
                    category=self._normalize_category(
                        item.get("category", "TECHNICAL")
                    ),
                    impact=self._normalize_impact(item.get("impact", "MEDIUM")),
                    source_section=source_section,
                    keywords=item.get("keywords", []),
                )
                if req.text.strip():
                    requirements.append(req)
            except (ValueError, TypeError) as exc:
                logger.warning(f"[B1] Skipping invalid requirement {i}: {exc}")
                continue

        return requirements

    # ── Deduplication ────────────────────────────────────────

    @staticmethod
    def _deduplicate(requirements: list[Requirement]) -> list[Requirement]:
        """Remove duplicate requirements by normalized text."""
        seen: set[str] = set()
        unique: list[Requirement] = []
        for req in requirements:
            normalized = re.sub(r"\s+", " ", req.text.strip().lower())
            if normalized not in seen:
                seen.add(normalized)
                unique.append(req)
        return unique

    # ── Enum normalization helpers ───────────────────────────

    @staticmethod
    def _normalize_type(value: str) -> RequirementType:
        v = value.strip().upper()
        try:
            return RequirementType(v)
        except ValueError:
            return RequirementType.MANDATORY

    @staticmethod
    def _normalize_classification(value: str) -> RequirementClassification:
        v = value.strip().upper().replace("-", "_").replace(" ", "_")
        try:
            return RequirementClassification(v)
        except ValueError:
            return RequirementClassification.FUNCTIONAL

    @staticmethod
    def _normalize_category(value: str) -> RequirementCategory:
        v = value.strip().upper()
        try:
            return RequirementCategory(v)
        except ValueError:
            return RequirementCategory.TECHNICAL

    @staticmethod
    def _normalize_impact(value: str) -> ImpactLevel:
        v = value.strip().upper()
        try:
            return ImpactLevel(v)
        except ValueError:
            return ImpactLevel.MEDIUM
