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
from rfp_automation.services.llm_service import llm_text_call, llm_large_text_call

logger = logging.getLogger(__name__)

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "prompts"
    / "requirements_validation_prompt.txt"
)

_CORRECTION_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "prompts"
    / "factual_correction_prompt.txt"
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
        # Inject original RFP text so LLM can cross-check factual accuracy.
        # This agent calls llm_large_text_call → Llama 4 Scout
        # with 131K context window and 30K TPM per key.
        # Budget: ~25K tokens input comfortably fits all requirements + full RFP text.
        rfp_context = state.raw_text[:80_000] if state.raw_text else "No RFP source text available."
        prompt = template.format(
            requirements_json=requirements_json[:50_000],
            rfp_context=rfp_context,
        )

        if len(prompt) > 100_000:
            logger.warning(
                f"[B2] Prompt is large ({len(prompt)} chars ≈ "
                f"{len(prompt) // 4} tokens) — may hit TPM limits"
            )

        # ── 2. Call LLM for validation ──────────────────────
        logger.info(f"[B2] Calling LLM for validation ({len(prompt)} char prompt)")
        try:
            raw_response = llm_large_text_call(prompt, deterministic=True)
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
        issues = self._build_issues(validation_data.get("issues", []))

        # Confidence: use LLM value, but apply heuristic if it returned 0.0
        # with no issues (likely a parse or LLM output quirk).
        raw_conf = validation_data.get("confidence_score")
        if raw_conf is None or (raw_conf == 0 and not issues):
            # Heuristic: base 0.90, subtract 0.05 per issue
            confidence_score = max(0.90 - 0.05 * len(issues), 0.10)
            logger.warning(
                f"[B2] LLM returned no / zero confidence with {len(issues)} "
                f"issues — using heuristic: {confidence_score:.3f}"
            )
        else:
            confidence_score = float(raw_conf)

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
                requirements, issues, confidence_score, state.raw_text
            )

        # ── 4b. Apply factual corrections ────────────────
        requirements, corrected_ids = self._apply_factual_corrections(
            requirements, issues, state.raw_text
        )
        # Remove stale factual_error issues for corrected requirements
        if corrected_ids:
            issues = [
                i for i in issues
                if i.issue_type != "factual_error"
                or not all(rid in corrected_ids for rid in i.requirement_ids)
            ]
            logger.info(
                f"[B2] Pruned stale factual_error issues for "
                f"{len(corrected_ids)} corrected requirement(s)"
            )
        state.requirements = requirements

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

    # ── Factual correction ────────────────────────────────────

    def _apply_factual_corrections(
        self,
        requirements: list[Requirement],
        issues: list[ValidationIssue],
        raw_text: str = "",
    ) -> tuple[list[Requirement], set[str]]:
        """
        Fix requirement text for any 'factual_error' issues detected
        during validation, by cross-referencing the original RFP text.

        Returns:
            (requirements, corrected_ids) — the updated list and the set of
            requirement IDs that were successfully corrected.

        Guardrails:
        - Only requirements explicitly flagged as factual_error are touched.
        - If the LLM call fails, requirements pass through unchanged.
        - Both old and new text are logged for auditability.
        """
        factual_issues = [
            i for i in issues if i.issue_type == "factual_error"
        ]
        if not factual_issues:
            return requirements, set()

        # Collect affected requirement IDs
        affected_ids: set[str] = set()
        for issue in factual_issues:
            affected_ids.update(issue.requirement_ids)

        # Build a lookup of affected requirements
        affected_reqs = [
            r for r in requirements if r.requirement_id in affected_ids
        ]
        if not affected_reqs:
            return requirements, set()

        logger.info(
            f"[B2] Applying factual corrections to "
            f"{len(affected_reqs)} requirement(s): {sorted(affected_ids)}"
        )

        # Build the correction prompt
        error_requirements_json = json.dumps(
            [{"requirement_id": r.requirement_id, "text": r.text}
             for r in affected_reqs],
            indent=2,
        )
        error_descriptions = "\n".join(
            f"- {i.requirement_ids}: {i.description}" for i in factual_issues
        )
        rfp_context = (
            raw_text[:12_000] if raw_text
            else "No RFP source text available."
        )

        try:
            template = _CORRECTION_PROMPT_PATH.read_text(encoding="utf-8")
            prompt = template.format(
                error_requirements_json=error_requirements_json,
                error_descriptions=error_descriptions,
                rfp_context=rfp_context,
            )
        except (FileNotFoundError, KeyError) as exc:
            logger.warning(
                f"[B2] Could not build correction prompt: {exc} — "
                f"skipping factual corrections"
            )
            return requirements, set()

        try:
            raw_response = llm_large_text_call(prompt, deterministic=True)
            correction_data = self._parse_validation_json(raw_response)
        except Exception as exc:
            logger.warning(
                f"[B2] Factual correction LLM call failed: {exc} — "
                f"requirements pass through uncorrected"
            )
            return requirements, set()

        # Apply corrections
        corrections = correction_data.get("corrections", [])
        req_lookup = {r.requirement_id: r for r in requirements}
        corrected_count = 0
        corrected_ids: set[str] = set()

        for corr in corrections:
            if not isinstance(corr, dict):
                continue
            req_id = corr.get("requirement_id", "")
            corrected_text = corr.get("corrected_text", "")
            if not req_id or not corrected_text:
                continue
            if req_id not in affected_ids:
                logger.warning(
                    f"[B2] LLM tried to correct {req_id} which was not "
                    f"flagged — skipping (guardrail)"
                )
                continue
            req = req_lookup.get(req_id)
            if req and req.text != corrected_text:
                logger.info(
                    f"[B2] Corrected {req_id}: "
                    f"{req.text!r} → {corrected_text!r}"
                )
                req.text = corrected_text
                corrected_count += 1
                corrected_ids.add(req_id)

        logger.info(
            f"[B2] Factual corrections applied: {corrected_count} of "
            f"{len(affected_reqs)} requirement(s) updated"
        )
        return requirements, corrected_ids

    # ── Refinement ───────────────────────────────────────────

    def _refine(
        self,
        requirements: list[Requirement],
        issues: list[ValidationIssue],
        original_confidence: float,
        raw_text: str = "",
    ) -> tuple[list[Requirement], float, list[ValidationIssue]]:
        """
        Attempt one LLM-based refinement pass, grounded in original RFP text.

        Guardrail: the refinement can only *remove* issues or *lower* severity.
        If the LLM returns more issues than the original set, the refinement
        is discarded to prevent hallucinated issue injection.
        """
        issues_text = "\n".join(
            f"- [{i.issue_type}] {i.requirement_ids}: {i.description}"
            for i in issues
        )

        # Include RFP context so the LLM can ground its re-evaluation
        rfp_context = ""
        if raw_text:
            rfp_context = (
                "\n\nHere is the original RFP text for reference "
                "(use this to verify whether issues are real):\n"
                f"{raw_text[:8_000]}\n"
            )

        refinement_prompt = (
            "You previously validated a set of RFP requirements and found these issues:\n\n"
            f"{issues_text}\n\n"
            "Here are the requirements again:\n"
            f"{json.dumps([r.model_dump(mode='json') for r in requirements], indent=2)[:10_000]}\n\n"
            f"{rfp_context}\n"
            "IMPORTANT INSTRUCTIONS:\n"
            "- Only keep issues that are supported by the RFP text above.\n"
            "- Do NOT add new requirements or modify requirement text.\n"
            "- Do NOT add new issues that were not in the original list.\n"
            "- Only re-evaluate the confidence score and issue list.\n"
            "- You may remove issues or lower their severity if evidence is weak.\n\n"
            "Return ONLY valid JSON with the same structure as before:\n"
            '{"confidence_score": 0.85, "issues": [...], "requirement_notes": {...}}'
        )

        try:
            raw = llm_large_text_call(refinement_prompt, deterministic=True)
            refined_data = self._parse_validation_json(raw)
            new_confidence = float(refined_data.get("confidence_score", original_confidence))
            new_issues = self._build_issues(refined_data.get("issues", []))

            # Guardrail: refinement must not add new issues
            if len(new_issues) > len(issues):
                logger.warning(
                    f"[B2] Refinement guardrail triggered: LLM returned "
                    f"{len(new_issues)} issues (was {len(issues)}). "
                    f"Discarding refinement to prevent issue injection."
                )
                return requirements, original_confidence, issues

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
        """Parse the LLM validation response into a dict.

        Robustness layers:
        1. Strip <think>…</think> reasoning tags (Qwen3 models)
        2. Strip markdown code fences
        3. Locate outermost { … } JSON object
        4. On parse failure, attempt structural repair (remove trailing comma,
           truncated strings, etc.)
        """
        text = raw_response.strip()

        # Strip <think>…</think> tags that Qwen models emit
        text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        # Extract JSON object or array
        try:
            obj_start = text.find("{")
            arr_start = text.find("[")
            
            starts = [s for s in (obj_start, arr_start) if s != -1]
            if not starts:
                raise ValueError("No JSON structure")
                
            start = min(starts)
            if start == obj_start:
                end = text.rindex("}") + 1
            else:
                end = text.rindex("]") + 1
                
            text = text[start:end]
        except ValueError:
            logger.warning("[B2] No JSON object/array found in LLM response")
            return {}

        try:
            data = json.loads(text)
            if isinstance(data, list):
                if data and isinstance(data[0], dict) and "corrected_text" in data[0]:
                    data = {"corrections": data}
                else:
                    data = {"issues": data}
        except json.JSONDecodeError as exc:
            logger.warning(f"[B2] JSON parse error: {exc} — attempting repair")
            data = self._attempt_json_repair(text, "B2")
            if data is None:
                return {}

        return data if isinstance(data, dict) else {}

    @staticmethod
    def _attempt_json_repair(text: str, agent_tag: str) -> dict | None:
        """Try to fix common JSON issues from LLM output."""
        import re as _re

        # 1. Remove trailing commas before } or ]
        repaired = _re.sub(r",\s*([}\]])", r"\1", text)
        try:
            data = json.loads(repaired)
            logger.info(f"[{agent_tag}] JSON repaired (trailing comma fix)")
            return data
        except json.JSONDecodeError:
            pass

        # 2. Truncated output — find last valid } and close
        last_brace = text.rfind("}")
        if last_brace > 0:
            candidate = text[:last_brace + 1]
            # Balance braces
            open_count = candidate.count("{")
            close_count = candidate.count("}")
            if open_count > close_count:
                candidate += "}" * (open_count - close_count)
            try:
                data = json.loads(candidate)
                logger.info(f"[{agent_tag}] JSON repaired (truncation fix)")
                return data
            except json.JSONDecodeError:
                pass

        logger.error(f"[{agent_tag}] JSON repair failed — returning None")
        return None

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
        factual_error_count = sum(
            1 for i in issues if i.issue_type == "factual_error"
        )

        if factual_error_count:
            logger.warning(
                f"[B2] {factual_error_count} factual error(s) detected — "
                f"extracted values don't match RFP source text"
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
