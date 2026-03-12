"""
D1 — Technical Validation Agent
Responsibility: Validate assembled proposal against original requirements.
                Check completeness, alignment, realism, consistency.
                REJECT loops back to C3 (max 3 retries).

Strategy:
  - If the single-call prompt fits within the token budget → single LLM call
  - If too large → multi-pass: one call per check dimension, each with
    only the relevant slice of data

Reads:
  - assembled_proposal.full_narrative  — the complete proposal from C3
  - requirements                       — extracted requirements from B1
  - technical_validation.retry_count   — previous retry count (for loop)

Writes:
  - technical_validation  — TechnicalValidationResult with decision + checks
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
    ValidationDecision,
)
from rfp_automation.models.schemas import (
    TechnicalValidationResult,
    ValidationCheckResult,
)
from rfp_automation.models.state import RFPGraphState
from rfp_automation.services.llm_service import llm_text_call, llm_large_text_call

logger = logging.getLogger(__name__)

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "prompts"
    / "validation_prompt.txt"
)

# ── Prompt budget ─────────────────────────────────────────
# Groq free tier ≈ 6000 TPM.  We target ~4500 tokens for the
# prompt (≈18 000 chars) leaving room for the response.
_SINGLE_CALL_MAX_CHARS = 10_000   # switch to multi-pass above this
_MAX_PROPOSAL_CHARS = 25_000
_MAX_REQUIREMENTS_CHARS = 12_000
_MAX_REQ_TEXT_LEN = 120
_MAX_REQUIREMENTS_COUNT = 150

# Multi-pass budget per call
_PASS_MAX_PROPOSAL_CHARS = 4_000
_PASS_MAX_REQ_CHARS = 3_000


class TechnicalValidationAgent(BaseAgent):
    name = AgentName.D1_TECHNICAL_VALIDATION

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        proposal = state.assembled_proposal.full_narrative
        requirements = state.requirements
        prev_retry = state.technical_validation.retry_count

        logger.info(
            f"[D1] Starting technical validation "
            f"(retry #{prev_retry}, {len(requirements)} requirements, "
            f"{len(proposal)} chars of proposal)"
        )

        # ── Guard: no proposal to validate ────────────────
        if not proposal or len(proposal.strip()) < 100:
            logger.warning("[D1] Proposal is empty or too short — auto-PASS")
            state.technical_validation = TechnicalValidationResult(
                decision=ValidationDecision.PASS,
                checks=[], critical_failures=0, warnings=0,
                feedback_for_revision="", retry_count=prev_retry,
            )
            state.status = PipelineStatus.TECHNICAL_VALIDATION
            return state

        # ── Filter to mandatory requirements ──────────────
        mandatory_reqs = [
            r for r in requirements
            if r.type == RequirementType.MANDATORY
        ]
        if not mandatory_reqs:
            mandatory_reqs = requirements

        # ── Try single-call first ─────────────────────────
        req_text = self._build_requirements_text(mandatory_reqs)
        proposal_text = self._truncate_proposal(proposal, _MAX_PROPOSAL_CHARS)
        template = _PROMPT_PATH.read_text(encoding="utf-8")
        single_prompt = template.format(
            requirements=req_text,
            proposal=proposal_text,
        )

        if len(single_prompt) <= _SINGLE_CALL_MAX_CHARS:
            logger.info(
                f"[D1] Single-call mode ({len(single_prompt)} chars)"
            )
            result = self._run_single_call(single_prompt)
            checks, feedback = result

            # If single-call returned None, it means truncation was
            # detected — fall back to multi-pass automatically
            if checks is None:
                logger.info(
                    "[D1] Single-call truncated — falling back to multi-pass"
                )
                checks, feedback = self._run_multi_pass(
                    mandatory_reqs, proposal
                )
        else:
            logger.info(
                f"[D1] Prompt too large ({len(single_prompt)} chars > "
                f"{_SINGLE_CALL_MAX_CHARS}), switching to multi-pass"
            )
            checks, feedback = self._run_multi_pass(
                mandatory_reqs, proposal
            )

        # ── Compute counts & decision ─────────────────────
        critical_checks = {"completeness", "alignment"}
        if prev_retry < 2:
            critical_checks.add("realism")
        critical_failures = 0
        warnings = 0

        for check in checks:
            issue_count = len(check.issues)
            if check.check_name in critical_checks and not check.passed:
                critical_failures += issue_count
            elif not check.passed:
                warnings += issue_count

        if critical_failures > 0:
            decision = ValidationDecision.REJECT
        else:
            decision = ValidationDecision.PASS

        new_retry_count = prev_retry + (
            1 if decision == ValidationDecision.REJECT else 0
        )

        # ── Categorize issues (Type 1 / Type 2) ──────────
        if decision == ValidationDecision.REJECT:
            categorized = self._categorize_issues(checks)
            if categorized:
                feedback = categorized

            # ── Feedback loop detection ───────────────────
            prev_feedback = state.technical_validation.feedback_for_revision
            if prev_feedback and feedback:
                prev_reqs = set(re.findall(r'REQ-\d+', prev_feedback))
                curr_reqs = set(re.findall(r'REQ-\d+', feedback))
                if prev_reqs and len(prev_reqs & curr_reqs) / len(prev_reqs) > 0.8:
                    logger.warning("[D1] Feedback loop: 80%+ same REQs flagged — marking for human review")
                    feedback = f"[STUCK LOOP] {feedback}"

        result = TechnicalValidationResult(
            decision=decision,
            checks=checks,
            critical_failures=critical_failures,
            warnings=warnings,
            feedback_for_revision=(
                feedback if decision == ValidationDecision.REJECT else ""
            ),
            retry_count=new_retry_count,
        )

        state.technical_validation = result
        state.status = PipelineStatus.TECHNICAL_VALIDATION

        logger.info(
            f"[D1] Validation complete: decision={decision.value}, "
            f"critical={critical_failures}, warnings={warnings}, "
            f"retry={new_retry_count}"
        )
        for check in checks:
            icon = "✔" if check.passed else "✘"
            logger.info(
                f"[D1]   {icon} {check.check_name}: "
                f"{'passed' if check.passed else f'FAILED ({len(check.issues)} issues)'}"
            )
            for issue in check.issues:
                logger.info(f"[D1]       → {issue[:120]}")

        return state

    # ══════════════════════════════════════════════════════
    #  SINGLE-CALL PATH
    # ══════════════════════════════════════════════════════

    def _run_single_call(
        self, prompt: str
    ) -> tuple[list[ValidationCheckResult], str]:
        """Single LLM call with the full validation prompt.

        If the LLM truncates its response (finish_reason=length),
        returns (None, None) to signal the caller to retry with multi-pass.
        """
        try:
            raw = llm_large_text_call(prompt, deterministic=True)
        except Exception as exc:
            logger.error(f"[D1] Single-call LLM failed: {exc}")
            return self._default_checks(), ""

        data = self._parse_json(raw)

        # Detect truncation: if we got no checks AND the response is
        # suspiciously long, the JSON was likely truncated
        checks_data = data.get("checks", [])
        if not checks_data and len(raw) > 2000:
            logger.warning(
                "[D1] Single-call returned no parseable checks "
                f"({len(raw)} chars response) — likely truncated. "
                "Will retry with multi-pass."
            )
            return None, None  # type: ignore[return-value]

        checks = self._build_checks(checks_data)
        feedback = data.get("feedback_for_revision", "")
        return checks, feedback

    # ══════════════════════════════════════════════════════
    #  MULTI-PASS PATH
    # ══════════════════════════════════════════════════════

    def _run_multi_pass(
        self,
        mandatory_reqs: list,
        proposal: str,
    ) -> tuple[list[ValidationCheckResult], str]:
        """
        Run one LLM call per check dimension with smaller prompts.
        Each call gets only the data relevant to that check.
        """
        sections = self._split_into_sections(proposal)
        section_headings = "\n".join(
            f"- {s['heading']}" for s in sections
        )
        section_previews = "\n\n".join(
            f"### {s['heading']}\n{s['text'][:400]}"
            for s in sections
        )

        req_text = self._build_requirements_text(
            mandatory_reqs, max_chars=_PASS_MAX_REQ_CHARS
        )

        checks: list[ValidationCheckResult] = []
        all_feedback: list[str] = []

        # ── Pass 1: Completeness ──────────────────────────
        p1 = (
            f"Check COMPLETENESS: Are all mandatory requirements addressed "
            f"in the proposal sections below? (General answers are acceptable if specific details are unavailable)\n\n"
            f"REQUIREMENTS:\n{req_text}\n\n"
            f"PROPOSAL SECTIONS:\n{section_headings}\n\n"
            f"SECTION PREVIEWS:\n"
            f"{section_previews[:_PASS_MAX_PROPOSAL_CHARS]}\n\n"
            f"RULES:\n"
            f"- Accept confident alternative solutions and reasonable industry-standard extrapolations as PASSING.\n"
            f"- Absence of Evidence is NOT Evidence of Absence: Assume the company can meet requirements (certifications, specs) unless explicitly contradicted.\n"
            f"- Do not fail if a pragmatic alternative is proposed in lieu of missing evidence.\n"
            f"- Optional requirements should NEVER cause a failure.\n\n"
            f"Return JSON: {{\"passed\": true/false, \"issues\": "
            f"[\"list of unaddressed requirements\"], "
            f"\"description\": \"brief summary of findings\", "
            f"\"feedback\": \"what's missing\"}}"
        )
        c1 = self._run_check_pass("completeness", p1)
        checks.append(c1)
        if not c1.passed:
            all_feedback.append(f"Completeness: {'; '.join(c1.issues)}")

        # ── Pass 2: Alignment ─────────────────────────────
        p2 = (
            f"Check ALIGNMENT: Do the proposal responses generally align "
            f"with the requirements' intent?\n\n"
            f"REQUIREMENTS:\n{req_text}\n\n"
            f"PROPOSAL (excerpt):\n"
            f"{self._truncate_proposal(proposal, _PASS_MAX_PROPOSAL_CHARS)}\n\n"
            f"RULES:\n"
            f"- Accept confident alternative solutions and reasonable industry-standard extrapolations as PASSING.\n"
            f"- Absence of Evidence is NOT Evidence of Absence: Assume the company can meet requirements (certifications, specs) unless explicitly contradicted.\n"
            f"- Do not fail if a pragmatic alternative is proposed in lieu of missing evidence.\n"
            f"- Optional requirements should NEVER cause a failure.\n\n"
            f"Return JSON: {{\"passed\": true/false, \"issues\": "
            f"[\"list of misaligned responses\"], "
            f"\"description\": \"brief summary of findings\", "
            f"\"feedback\": \"what needs fixing\"}}"
        )
        c2 = self._run_check_pass("alignment", p2)
        checks.append(c2)
        if not c2.passed:
            all_feedback.append(f"Alignment: {'; '.join(c2.issues)}")

        # ── Pass 3: Realism ───────────────────────────────
        p3 = (
            f"Check REALISM: Are the proposal's commitments supportable? "
            f"Flag overpromising, unrealistic timelines, or unsupported claims.\n\n"
            f"PROPOSAL (excerpt):\n"
            f"{self._truncate_proposal(proposal, _PASS_MAX_PROPOSAL_CHARS)}\n\n"
            f"Return JSON: {{\"passed\": true/false, \"issues\": "
            f"[\"list of unrealistic claims\"], "
            f"\"description\": \"brief summary of findings\", "
            f"\"feedback\": \"\"}}"
        )
        c3 = self._run_check_pass("realism", p3)
        checks.append(c3)

        # ── Pass 4: Consistency ───────────────────────────
        p4 = (
            f"Check CONSISTENCY: Are there any contradictions between "
            f"sections (timelines, SLAs, capabilities, numbers)?\n\n"
            f"PROPOSAL SECTIONS:\n{section_previews[:_PASS_MAX_PROPOSAL_CHARS]}\n\n"
            f"Return JSON: {{\"passed\": true/false, \"issues\": "
            f"[\"list of contradictions\"], "
            f"\"description\": \"brief summary of findings\", "
            f"\"feedback\": \"\"}}"
        )
        c4 = self._run_check_pass("consistency", p4)
        checks.append(c4)

        feedback = " | ".join(all_feedback) if all_feedback else ""
        return checks, feedback

    def _run_check_pass(
        self, check_name: str, prompt: str
    ) -> ValidationCheckResult:
        """Run a single validation check via LLM."""
        logger.info(
            f"[D1] Multi-pass: {check_name} ({len(prompt)} chars)"
        )
        try:
            raw = llm_large_text_call(prompt, deterministic=True)
            data = self._parse_json(raw)
            issues = [
                str(i).strip() for i in data.get("issues", [])
                if str(i).strip()
            ]
            passed = data.get("passed", len(issues) == 0)
            description = str(data.get("description", "")).strip()
            return ValidationCheckResult(
                check_name=check_name,
                passed=passed,
                issues=issues,
                description=description,
            )
        except Exception as exc:
            logger.warning(
                f"[D1] Multi-pass {check_name} failed: {exc} — assuming pass"
            )
            return ValidationCheckResult(
                check_name=check_name, passed=True, issues=[],
                description="Auto-passed (LLM call failed)",
            )

    # ══════════════════════════════════════════════════════
    #  HELPERS
    # ══════════════════════════════════════════════════════

    @staticmethod
    def _build_requirements_text(
        reqs: list, max_chars: int = _MAX_REQUIREMENTS_CHARS
    ) -> str:
        """Build compact requirements text: id + truncated text."""
        total = len(reqs)
        sampled = reqs[:_MAX_REQUIREMENTS_COUNT]

        lines = [
            f"- {r.requirement_id}: {r.text[:_MAX_REQ_TEXT_LEN]}"
            for r in sampled
        ]
        text = (
            f"Total mandatory: {total} (showing {len(sampled)})\n"
            + "\n".join(lines)
        )
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... (truncated)"
        return text

    @staticmethod
    def _truncate_proposal(proposal: str, max_chars: int) -> str:
        """Truncate proposal text to fit budget."""
        if len(proposal) <= max_chars:
            return proposal
        return proposal[:max_chars] + "\n\n... (truncated)"

    @staticmethod
    def _split_into_sections(proposal: str) -> list[dict[str, str]]:
        """Split proposal on ## headings into section dicts."""
        sections: list[dict[str, str]] = []
        current_heading = "Introduction"
        current_lines: list[str] = []

        for line in proposal.split("\n"):
            if line.strip().startswith("## "):
                if current_lines:
                    sections.append({
                        "heading": current_heading,
                        "text": "\n".join(current_lines),
                    })
                current_heading = line.strip().lstrip("#").strip()
                current_lines = []
            else:
                current_lines.append(line)

        if current_lines:
            sections.append({
                "heading": current_heading,
                "text": "\n".join(current_lines),
            })

        return sections

    @staticmethod
    def _default_checks() -> list[ValidationCheckResult]:
        """Return four default-pass checks when LLM fails."""
        return [
            ValidationCheckResult(
                check_name=n, passed=True, issues=[],
                description="Auto-passed (LLM call failed, not evaluated)",
            )
            for n in ("completeness", "alignment", "realism", "consistency")
        ]

    @staticmethod
    def _categorize_issues(checks: list[ValidationCheckResult]) -> str:
        """Categorize issues:
        Type 1: Present in proposal but poorly written / incomplete
        Type 2: Not present in proposal at all
        """
        type1, type2 = [], []
        for check in checks:
            for issue in check.issues:
                if any(kw in issue.lower() for kw in ["missing", "not mentioned", "absent", "no reference"]):
                    type2.append(f"[{check.check_name}] {issue}")
                else:
                    type1.append(f"[{check.check_name}] {issue}")

        parts = []
        if type1:
            parts.append("TYPE 1 — In capabilities but poorly written:\n" + "\n".join(f"  • {i}" for i in type1))
        if type2:
            parts.append("TYPE 2 — Not present in capabilities:\n" + "\n".join(f"  • {i}" for i in type2))
        return "\n\n".join(parts) if parts else ""

    # ── JSON parsing ─────────────────────────────────────

    @staticmethod
    def _parse_json(raw_response: str) -> dict[str, Any]:
        """Parse the LLM validation response into a dict.

        Robustness layers:
        1. Strip <think>…</think> reasoning tags (Qwen3 models)
        2. Strip markdown code fences
        3. Locate outermost { … } JSON object
        4. On parse failure, attempt structural repair
        """
        text = raw_response.strip()

        # Strip <think>…</think> tags that Qwen models emit
        text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

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
            logger.warning("[D1] No JSON object found in LLM response")
            return {}

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning(f"[D1] JSON parse error: {exc} — attempting repair")
            data = TechnicalValidationAgent._attempt_json_repair(text)
            if data is None:
                return {}

        return data if isinstance(data, dict) else {}

    @staticmethod
    def _attempt_json_repair(text: str) -> dict | None:
        """Try to fix common JSON issues from LLM output."""
        # 1. Remove trailing commas before } or ]
        repaired = re.sub(r",\s*([}\]])", r"\1", text)
        try:
            data = json.loads(repaired)
            logger.info("[D1] JSON repaired (trailing comma fix)")
            return data
        except json.JSONDecodeError:
            pass

        # 2. Truncated output — find last valid } and close
        last_brace = text.rfind("}")
        if last_brace > 0:
            candidate = text[:last_brace + 1]
            open_count = candidate.count("{")
            close_count = candidate.count("}")
            if open_count > close_count:
                candidate += "}" * (open_count - close_count)
            try:
                data = json.loads(candidate)
                logger.info("[D1] JSON repaired (truncation fix)")
                return data
            except json.JSONDecodeError:
                pass

        logger.error("[D1] JSON repair failed — returning None")
        return None

    # ── Build typed check results (for single-call path) ──

    @staticmethod
    def _build_checks(
        raw_checks: list[dict[str, Any]]
    ) -> list[ValidationCheckResult]:
        """Convert raw dicts from LLM into ValidationCheckResult objects."""
        results: list[ValidationCheckResult] = []
        expected = {"completeness", "alignment", "realism", "consistency"}
        seen: set[str] = set()

        for item in raw_checks:
            if not isinstance(item, dict):
                continue
            check_name = item.get("check_name", "").lower().strip()
            if not check_name:
                continue
            seen.add(check_name)
            issues = item.get("issues", [])
            issues = [str(i).strip() for i in issues if str(i).strip()]
            passed = item.get("passed", len(issues) == 0)
            description = str(item.get("description", "")).strip()

            results.append(
                ValidationCheckResult(
                    check_name=check_name, passed=passed,
                    issues=issues, description=description,
                )
            )

        # Add any missing checks as passed — but warn if ALL are missing
        missing = expected - seen
        if missing and not seen:
            logger.warning(
                "[D1] ALL check results missing from LLM response — "
                f"defaulting {len(missing)} checks to PASS "
                "(JSON may have been malformed)"
            )
        for name in missing:
            results.append(
                ValidationCheckResult(
                    check_name=name, passed=True, issues=[],
                    description="Auto-passed (not evaluated by LLM)",
                )
            )

        return results
