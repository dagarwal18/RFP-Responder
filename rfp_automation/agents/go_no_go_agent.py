"""
A3 - Go / No-Go Agent
Responsibility: Extract requirements from the RFP, map them against
company policies/capabilities, score fit/risk, and produce GO or NO_GO.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.config import get_settings
from rfp_automation.models.enums import AgentName, GoNoGoDecision, PipelineStatus
from rfp_automation.models.schemas import GoNoGoResult, RequirementMapping
from rfp_automation.models.state import RFPGraphState
from rfp_automation.mcp import MCPService
from rfp_automation.services.llm_service import llm_text_call

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "go_no_go_prompt.txt"
_A3_TOTAL_TOKEN_BUDGET = 4_200
_A3_OUTPUT_TOKEN_RESERVE = 900
_A3_CHARS_PER_TOKEN = 3
_A3_MIN_INPUT_CHARS = 3_600
_A3_MAX_SECTIONS = 18
_A3_MAX_POLICIES = 12
_A3_MAX_CAPABILITIES = 5
_COMMON_WORDS = {
    "about", "across", "after", "all", "and", "any", "are", "authority", "available",
    "basis", "between", "branch", "capability", "capabilities", "certification", "cloud",
    "company", "compliance", "contract", "current", "customer", "customers", "data",
    "delivery", "direct", "document", "edge", "ensure", "enterprise", "for", "from",
    "have", "include", "including", "india", "infrastructure", "into", "limited",
    "management", "managed", "must", "network", "operations", "platform", "programme",
    "proposal", "provide", "required", "requirement", "requirements", "response",
    "section", "security", "service", "services", "shall", "should", "sites", "solution",
    "support", "system", "technical", "that", "the", "their", "this", "those", "vendor",
    "with", "within", "workstream",
}


class GoNoGoAgent(BaseAgent):
    name = AgentName.A3_GO_NO_GO

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        rfp_id = state.rfp_metadata.rfp_id
        if not rfp_id:
            raise ValueError("No rfp_id in state - A1 Intake must run first")

        logger.info(f"[A3] Starting Go/No-Go analysis for {rfp_id}")

        mcp = MCPService()

        sections = state.structuring_result.sections
        logger.debug(f"[A3] Structuring result has {len(sections)} sections")
        rfp_sections_text = self._format_sections(sections)

        if not rfp_sections_text.strip():
            logger.debug("[A3] No structured sections - falling back to MCP RFP store")
            chunks = mcp.query_rfp_all_chunks(rfp_id, top_k=50)
            logger.debug(f"[A3] Retrieved {len(chunks)} chunks from MCP")
            rfp_sections_text = self._format_chunk_fallback(chunks)

        if not rfp_sections_text.strip():
            logger.warning("[A3] No RFP content available - defaulting to GO")
            state.go_no_go_result = GoNoGoResult(
                decision=GoNoGoDecision.GO,
                justification="No RFP content available for analysis. Defaulting to GO.",
            )
            state.status = PipelineStatus.EXTRACTING_REQUIREMENTS
            return state

        policies = mcp.get_extracted_policies()
        logger.debug(f"[A3] Loaded {len(policies)} pre-extracted policies")
        policies_text = self._format_relevant_policies(policies, rfp_sections_text)

        capability_query = self._build_capability_query(rfp_sections_text)
        capabilities = mcp.query_knowledge(capability_query, top_k=10)
        logger.debug(f"[A3] Loaded {len(capabilities)} capability chunks")
        capabilities_text = self._format_capabilities(capabilities)

        prompt = self._build_prompt(rfp_sections_text, policies_text, capabilities_text)
        logger.debug(
            f"[A3] Prompt built - {len(prompt)} chars "
            f"(RFP: {len(rfp_sections_text)} | Policies: {len(policies_text)} | Capabilities: {len(capabilities_text)})"
        )

        logger.info("[A3] Calling LLM for Go/No-Go analysis...")
        raw_response = llm_text_call(prompt, deterministic=True)
        logger.debug(f"[A3] Raw LLM response ({len(raw_response)} chars):\n{raw_response[:2000]}")

        result = self._parse_response(raw_response)

        state.go_no_go_result = result
        state.status = PipelineStatus.EXTRACTING_REQUIREMENTS

        if result.decision == GoNoGoDecision.NO_GO:
            logger.warning("[A3 TEST BYPASS] Continuing pipeline downstream despite NO_GO decision.")
            logger.info(f"[A3] Decision: NO_GO - {result.justification}")
        else:
            logger.info(f"[A3] Decision: GO - {result.justification}")

        self._log_mapping_table(result)
        return state

    def _format_sections(self, sections: list[Any]) -> str:
        """Format the highest-signal structured sections into a compact prompt block."""
        if not sections:
            return ""

        candidates: list[tuple[int, int, str]] = []
        for idx, section in enumerate(sections):
            if isinstance(section, dict):
                section_id = section.get("section_id", "")
                title = section.get("title", "")
                category = section.get("category", "")
                summary = section.get("content_summary", "")
            else:
                section_id = getattr(section, "section_id", "")
                title = getattr(section, "title", "")
                category = getattr(section, "category", "")
                summary = getattr(section, "content_summary", "")

            line = (
                f"{section_id} | {self._truncate_at_word(title, 90)} [{category}] | "
                f"{self._truncate_at_word(summary, 180)}"
            ).strip(" |")
            if not line:
                continue
            score = self._score_section(idx, title, category, summary)
            candidates.append((score, idx, line))

        selected = self._select_scored_lines(
            candidates,
            max_chars=3_400,
            max_items=_A3_MAX_SECTIONS,
        )
        return "\n".join(selected)

    def _format_chunk_fallback(self, chunks: list[dict[str, Any]]) -> str:
        """Compact fallback when A2 produced no structured sections."""
        if not chunks:
            return ""
        lines: list[str] = []
        for idx, chunk in enumerate(chunks[:18], start=1):
            text = self._truncate_at_word(chunk.get("text", ""), 220)
            if text:
                lines.append(f"Chunk {idx}: {text}")
        return "\n".join(lines)

    def _format_relevant_policies(
        self,
        policies: list[dict[str, Any]],
        rfp_sections_text: str,
    ) -> str:
        """Pick a small, relevant subset of policies instead of dumping the full corpus."""
        if not policies:
            return "No company policies extracted yet."

        keywords = self._extract_keywords(rfp_sections_text)
        candidates: list[tuple[int, int, str]] = []
        for idx, policy in enumerate(policies):
            policy_id = policy.get("policy_id", "")
            category = policy.get("category", "")
            text = policy.get("policy_text", "") or policy.get("text", "")
            if not text:
                continue
            formatted = (
                f"{policy_id or f'POL-{idx + 1:04d}'} "
                f"[{category or 'general'}] "
                f"{self._truncate_at_word(text, 220)}"
            )
            score = self._score_policy(text, category, keywords)
            candidates.append((score, idx, formatted))

        selected = self._select_scored_lines(
            candidates,
            max_chars=2_200,
            max_items=_A3_MAX_POLICIES,
        )
        return "\n".join(selected) if selected else "No company policies extracted yet."

    def _build_capability_query(self, rfp_sections_text: str) -> str:
        keywords = self._extract_keywords(rfp_sections_text)
        suffix = " ".join(keywords[:8])
        if not suffix:
            return "company capabilities services"
        return f"company capabilities services {suffix}"

    def _format_capabilities(self, capabilities: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for idx, capability in enumerate(capabilities[:_A3_MAX_CAPABILITIES], start=1):
            text = self._truncate_at_word(capability.get("text", ""), 180)
            if text:
                lines.append(f"Capability {idx}: {text}")
        return "\n".join(lines) if lines else "No capability data available."

    def _score_section(self, idx: int, title: str, category: str, summary: str) -> int:
        text = f"{title} {summary}".lower()
        category_l = (category or "").lower()
        score = 0
        if idx < 8:
            score += 8
        if category_l in {"technical", "compliance", "legal", "evaluation", "submission"}:
            score += 10
        if category_l in {"scope", "commercial"}:
            score += 6
        for needle in (
            "mandatory", "must", "security", "compliance", "cert", "pricing",
            "commercial", "sla", "submission", "deadline", "technical",
            "network", "cloud", "soc", "data", "evaluation", "eligibility",
        ):
            if needle in text:
                score += 2
        return score

    def _score_policy(self, text: str, category: str, keywords: list[str]) -> int:
        haystack = f"{category} {text}".lower()
        score = 0
        for keyword in keywords:
            if keyword in haystack:
                score += 4
        for needle in (
            "iso", "soc", "security", "compliance", "privacy", "support",
            "service", "availability", "india", "data", "cloud",
        ):
            if needle in haystack:
                score += 1
        return score

    def _extract_keywords(self, text: str, limit: int = 20) -> list[str]:
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9\\-]{3,}", text.lower())
        filtered = [word for word in words if word not in _COMMON_WORDS and not word.isdigit()]
        counts = Counter(filtered)
        return [word for word, _count in counts.most_common(limit)]

    def _select_scored_lines(
        self,
        candidates: list[tuple[int, int, str]],
        *,
        max_chars: int,
        max_items: int,
    ) -> list[str]:
        """Select highest-scoring entries while preserving source order."""
        if not candidates:
            return []

        ranked = sorted(candidates, key=lambda item: (-item[0], item[1]))
        selected: list[tuple[int, str]] = []
        used_chars = 0

        for _score, idx, line in ranked:
            extra = len(line) + (1 if selected else 0)
            if selected and (len(selected) >= max_items or used_chars + extra > max_chars):
                continue
            if not selected and extra > max_chars:
                selected.append((idx, self._truncate_at_word(line, max_chars)))
                break
            selected.append((idx, line))
            used_chars += extra
            if len(selected) >= max_items:
                break

        selected.sort(key=lambda item: item[0])
        return [line for _, line in selected]

    def _log_mapping_table(self, result: GoNoGoResult) -> None:
        """Log a formatted requirement-mapping table at INFO level."""
        logger.info(
            f"[A3] Scores -> strategic_fit={result.strategic_fit_score:.1f}/10, "
            f"technical_feasibility={result.technical_feasibility_score:.1f}/10, "
            f"regulatory_risk={result.regulatory_risk_score:.1f}/10"
        )
        logger.info(
            f"[A3] Mappings -> total={result.total_requirements}, "
            f"aligned={result.aligned_count}, violated={result.violated_count}, "
            f"risk={result.risk_count}, no_match={result.no_match_count}"
        )

        if result.policy_violations:
            logger.info(f"[A3] Policy violations: {result.policy_violations}")
        if result.red_flags:
            logger.info(f"[A3] Red flags: {result.red_flags}")

        if not result.requirement_mappings:
            logger.info("[A3] No requirement mappings produced.")
            return

        id_w, status_w, conf_w = 14, 10, 6
        req_w, policy_w, reason_w = 40, 30, 30

        sep = f"+{'-' * id_w}+{'-' * status_w}+{'-' * conf_w}+{'-' * req_w}+{'-' * policy_w}+{'-' * reason_w}+"

        def pad(text: str, width: int) -> str:
            return (text[: width - 1] + "...") if len(text) >= width else text.ljust(width)

        lines = [
            "[A3] Requirement mapping results",
            f"[A3] {sep}",
            (
                f"[A3] |{pad('Requirement ID', id_w)}|{pad('Status', status_w)}|{pad('Conf.', conf_w)}|"
                f"{pad('Requirement Text', req_w)}|{pad('Matched Policy', policy_w)}|{pad('Reasoning', reason_w)}|"
            ),
            f"[A3] {sep}",
        ]

        for mapping in result.requirement_mappings:
            lines.append(
                f"[A3] |{pad(mapping.requirement_id, id_w)}|"
                f"{pad(mapping.mapping_status, status_w)}|"
                f"{pad(f'{mapping.confidence:.2f}', conf_w)}|"
                f"{pad(mapping.requirement_text, req_w)}|"
                f"{pad(mapping.matched_policy or '-', policy_w)}|"
                f"{pad(mapping.reasoning or '-', reason_w)}|"
            )

        lines.append(f"[A3] {sep}")
        logger.info("\n".join(lines))

    def _build_prompt(self, rfp_sections: str, policies: str, capabilities: str) -> str:
        template = _PROMPT_PATH.read_text(encoding="utf-8")
        settings = get_settings()
        total_token_budget = min(settings.llm_max_tokens, _A3_TOTAL_TOKEN_BUDGET)
        template_tokens = len(template) // _A3_CHARS_PER_TOKEN + 200
        data_budget_tokens = total_token_budget - _A3_OUTPUT_TOKEN_RESERVE - template_tokens
        data_budget_chars = max(data_budget_tokens * _A3_CHARS_PER_TOKEN, _A3_MIN_INPUT_CHARS)

        budget_sections = int(data_budget_chars * 0.46)
        budget_policies = int(data_budget_chars * 0.36)
        budget_capabilities = int(data_budget_chars * 0.18)

        total_input = len(rfp_sections) + len(policies) + len(capabilities)
        if total_input > data_budget_chars:
            logger.info(
                f"[A3] Truncating prompt inputs ({total_input} chars, "
                f"~{total_input // _A3_CHARS_PER_TOKEN} tokens) to fit budget "
                f"({data_budget_chars} chars, ~{data_budget_tokens} tokens)"
            )

        return (
            template
            .replace("{rfp_sections}", self._truncate_at_word(rfp_sections, budget_sections))
            .replace("{company_policies}", self._truncate_at_word(policies, budget_policies))
            .replace("{capabilities}", self._truncate_at_word(capabilities, budget_capabilities))
        )

    @staticmethod
    def _truncate_at_word(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        cut = text.rfind(" ", 0, max_chars)
        if cut <= 0:
            cut = max_chars
        return text[:cut]

    def _parse_response(self, raw: str) -> GoNoGoResult:
        """Parse the LLM JSON response into a GoNoGoResult."""
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        data: dict[str, Any] = {}
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        if not data:
            logger.error("[A3] Failed to parse LLM response - defaulting to GO")
            return GoNoGoResult(
                decision=GoNoGoDecision.GO,
                justification="LLM response parsing failed. Defaulting to GO for manual review.",
            )

        mappings: list[RequirementMapping] = []
        for mapping in data.get("requirement_mappings", []):
            if isinstance(mapping, dict):
                mappings.append(
                    RequirementMapping(
                        requirement_id=mapping.get("requirement_id", ""),
                        requirement_text=mapping.get("requirement_text", ""),
                        source_section=mapping.get("source_section", ""),
                        mapping_status=mapping.get("mapping_status", "NO_MATCH").upper(),
                        matched_policy=mapping.get("matched_policy", ""),
                        matched_policy_id=mapping.get("matched_policy_id", ""),
                        confidence=float(mapping.get("confidence", 0.0)),
                        reasoning=mapping.get("reasoning", ""),
                    )
                )

        aligned = sum(1 for mapping in mappings if mapping.mapping_status == "ALIGNS")
        violated = sum(1 for mapping in mappings if mapping.mapping_status == "VIOLATES")
        risk = sum(1 for mapping in mappings if mapping.mapping_status == "RISK")
        no_match = sum(1 for mapping in mappings if mapping.mapping_status == "NO_MATCH")

        decision_str = data.get("decision", "GO").upper()
        decision = GoNoGoDecision.NO_GO if decision_str == "NO_GO" else GoNoGoDecision.GO

        return GoNoGoResult(
            decision=decision,
            strategic_fit_score=float(data.get("strategic_fit_score", 0.0)),
            technical_feasibility_score=float(data.get("technical_feasibility_score", 0.0)),
            regulatory_risk_score=float(data.get("regulatory_risk_score", 0.0)),
            policy_violations=data.get("policy_violations", []),
            red_flags=data.get("red_flags", []),
            justification=data.get("justification", ""),
            requirement_mappings=mappings,
            total_requirements=len(mappings),
            aligned_count=aligned,
            violated_count=violated,
            risk_count=risk,
            no_match_count=no_match,
        )
