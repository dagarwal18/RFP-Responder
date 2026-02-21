"""
B2 — Requirements Validation Agent
Responsibility: Cross-check extracted requirements for completeness,
                duplicates, contradictions, and ambiguities.
                Issues do NOT block the pipeline — they flow forward as context.

If the overall confidence score falls below the configured threshold
(settings.min_validation_confidence), the agent attempts one LLM-based
refinement pass before finalizing.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.config import get_settings
from rfp_automation.models.enums import (
    AgentName,
    PipelineStatus,
    RequirementType,
    RequirementClassification,
)
from rfp_automation.models.schemas import (
    Requirement,
    RequirementsValidationResult,
    ValidationIssue,
)
from rfp_automation.models.state import RFPGraphState
from rfp_automation.services.llm_service import llm_text_call

logger = logging.getLogger(__name__)

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "prompts"
    / "requirements_validation_prompt.txt"
)


class RequirementsValidationAgent(BaseAgent):
    name = AgentName.B2_REQUIREMENTS_VALIDATION

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        requirements = state.requirements
        settings = get_settings()
        min_confidence = settings.min_validation_confidence

        logger.info(
            f"[B2] Starting validation of {len(requirements)} requirements "
            f"(min_confidence={min_confidence})"
        )

        if not requirements:
            logger.warning("[B2] No requirements to validate — passing through")
            state.requirements_validation = RequirementsValidationResult()
            state.status = PipelineStatus.ARCHITECTURE_PLANNING
            return state

        # ── 1. Build validation prompt ──────────────────────
        template = _PROMPT_PATH.read_text(encoding="utf-8")
        requirements_json = json.dumps(
            [r.model_dump(mode="json") for r in requirements],
            indent=2,
        )
        prompt = template.format(requirements_json=requirements_json[:12_000])

        # ── 2. Call LLM for validation ──────────────────────
        logger.info(f"[B2] Calling LLM for validation ({len(prompt)} char prompt)")
        try:
            raw_response = llm_text_call(prompt)
            logger.debug(
                f"[B2] Validation LLM response ({len(raw_response)} chars):\n"
                f"{raw_response[:2000]}"
            )
        except Exception as exc:
            logger.error(f"[B2] LLM call failed: {exc}")
            # On failure, pass requirements through unvalidated
            state.requirements_validation = self._build_result(
                requirements, issues=[], confidence_score=0.0
            )
            state.status = PipelineStatus.ARCHITECTURE_PLANNING
            return state

        # ── 3. Parse validation response ────────────────────
        validation_data = self._parse_validation_json(raw_response)
        confidence_score = float(validation_data.get("confidence_score", 0.0))
        issues = self._build_issues(validation_data.get("issues", []))

        logger.info(
            f"[B2] Validation result: confidence={confidence_score:.3f}, "
            f"{len(issues)} issues found"
        )
        for issue in issues:
            logger.debug(
                f"[B2]   {issue.issue_type} | {issue.requirement_ids} | "
                f"{issue.description[:80]}"
            )

        # ── 4. Refinement pass if confidence is low ─────────
        if confidence_score < min_confidence:
            logger.info(
                f"[B2] Confidence {confidence_score:.3f} < {min_confidence} — "
                f"attempting refinement"
            )
            requirements, confidence_score, issues = self._refine(
                requirements, issues, confidence_score
            )

        # ── 5. Build final result ───────────────────────────
        result = self._build_result(requirements, issues, confidence_score)
        state.requirements_validation = result
        state.status = PipelineStatus.ARCHITECTURE_PLANNING

        logger.info(
            f"[B2] Validation complete: {result.total_requirements} requirements, "
            f"confidence={result.confidence_score:.3f}, "
            f"functional={result.functional_count}, non_functional={result.non_functional_count}, "
            f"duplicates={result.duplicate_count}, "
            f"contradictions={result.contradiction_count}, "
            f"ambiguities={result.ambiguity_count}"
        )
        return state

    # ── Refinement ───────────────────────────────────────────

    def _refine(
        self,
        requirements: list[Requirement],
        issues: list[ValidationIssue],
        original_confidence: float,
    ) -> tuple[list[Requirement], float, list[ValidationIssue]]:
        """
        Attempt one LLM-based refinement pass.
        Sends the flagged issues back to the LLM and asks it to re-evaluate.
        """
        issues_text = "\n".join(
            f"- [{i.issue_type}] {i.requirement_ids}: {i.description}"
            for i in issues
        )
        refinement_prompt = (
            "You previously validated a set of RFP requirements and found these issues:\n\n"
            f"{issues_text}\n\n"
            "Here are the requirements again:\n"
            f"{json.dumps([r.model_dump(mode='json') for r in requirements], indent=2)[:10_000]}\n\n"
            "Please re-evaluate the requirements in light of these issues.\n"
            "Return ONLY valid JSON with the same structure as before:\n"
            '{"confidence_score": 0.85, "issues": [...], "requirement_notes": {...}}'
        )

        try:
            raw = llm_text_call(refinement_prompt)
            refined_data = self._parse_validation_json(raw)
            new_confidence = float(refined_data.get("confidence_score", original_confidence))
            new_issues = self._build_issues(refined_data.get("issues", []))

            logger.info(
                f"[B2] Refinement result: confidence {original_confidence:.3f} → "
                f"{new_confidence:.3f}, issues {len(issues)} → {len(new_issues)}"
            )
            return requirements, new_confidence, new_issues

        except Exception as exc:
            logger.warning(f"[B2] Refinement failed: {exc} — keeping original")
            return requirements, original_confidence, issues

    # ── JSON parsing ─────────────────────────────────────────

    def _parse_validation_json(self, raw_response: str) -> dict[str, Any]:
        """Parse the LLM validation response into a dict."""
        text = raw_response.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        # Extract JSON object
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            text = text[start:end]
        except ValueError:
            logger.warning("[B2] No JSON object found in LLM response")
            return {}

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning(f"[B2] JSON parse error: {exc}")
            return {}

        return data if isinstance(data, dict) else {}

    # ── Issue building ───────────────────────────────────────

    @staticmethod
    def _build_issues(raw_issues: list[dict[str, Any]]) -> list[ValidationIssue]:
        """Convert raw dicts from LLM into ValidationIssue objects."""
        issues: list[ValidationIssue] = []
        for item in raw_issues:
            if not isinstance(item, dict):
                continue
            try:
                issues.append(
                    ValidationIssue(
                        issue_type=item.get("issue_type", "ambiguity"),
                        requirement_ids=item.get("requirement_ids", []),
                        description=item.get("description", ""),
                        severity=item.get("severity", "warning"),
                    )
                )
            except (ValueError, TypeError):
                continue
        return issues

    # ── Result building ──────────────────────────────────────

    @staticmethod
    def _build_result(
        requirements: list[Requirement],
        issues: list[ValidationIssue],
        confidence_score: float,
    ) -> RequirementsValidationResult:
        """Build the final RequirementsValidationResult with computed counts."""
        mandatory = sum(
            1 for r in requirements if r.type == RequirementType.MANDATORY
        )
        optional = sum(
            1 for r in requirements if r.type == RequirementType.OPTIONAL
        )
        functional = sum(
            1 for r in requirements
            if r.classification == RequirementClassification.FUNCTIONAL
        )
        non_functional = sum(
            1 for r in requirements
            if r.classification == RequirementClassification.NON_FUNCTIONAL
        )
        duplicate_count = sum(
            1 for i in issues if i.issue_type == "duplicate"
        )
        contradiction_count = sum(
            1 for i in issues if i.issue_type == "contradiction"
        )
        ambiguity_count = sum(
            1 for i in issues if i.issue_type == "ambiguity"
        )

        return RequirementsValidationResult(
            validated_requirements=requirements,
            issues=issues,
            confidence_score=round(confidence_score, 4),
            total_requirements=len(requirements),
            mandatory_count=mandatory,
            optional_count=optional,
            functional_count=functional,
            non_functional_count=non_functional,
            duplicate_count=duplicate_count,
            contradiction_count=contradiction_count,
            ambiguity_count=ambiguity_count,
        )
