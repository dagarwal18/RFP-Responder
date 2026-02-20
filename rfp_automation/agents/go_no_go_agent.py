"""
A3 — Go / No-Go Agent
Responsibility: Extract requirements from RFP, map them against pre-extracted
                company policies, score strategic fit / feasibility / risk,
                produce GO or NO_GO with detailed requirement mappings.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, PipelineStatus, GoNoGoDecision
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import GoNoGoResult, RequirementMapping
from rfp_automation.mcp import MCPService
from rfp_automation.services.llm_service import llm_text_call

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "go_no_go_prompt.txt"


class GoNoGoAgent(BaseAgent):
    name = AgentName.A3_GO_NO_GO

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # ── 1. Validate rfp_id ──────────────────────────
        rfp_id = state.rfp_metadata.rfp_id
        if not rfp_id:
            raise ValueError("No rfp_id in state — A1 Intake must run first")

        logger.info(f"[A3] Starting Go/No-Go analysis for {rfp_id}")

        # ── 2. Gather RFP sections from structuring result ──
        sections = state.structuring_result.sections
        logger.debug(f"[A3] Structuring result has {len(sections)} sections")
        rfp_sections_text = self._format_sections(sections)

        # If no structured sections, fall back to RFP store
        if not rfp_sections_text.strip():
            logger.debug("[A3] No structured sections — falling back to MCP RFP store")
            mcp = MCPService()
            chunks = mcp.query_rfp_all_chunks(rfp_id, top_k=50)
            logger.debug(f"[A3] Retrieved {len(chunks)} chunks from MCP")
            rfp_sections_text = "\n\n".join(
                c.get("text", "") for c in chunks if c.get("text")
            )

        if not rfp_sections_text.strip():
            logger.warning("[A3] No RFP content available — defaulting to GO")
            state.go_no_go_result = GoNoGoResult(
                decision=GoNoGoDecision.GO,
                justification="No RFP content available for analysis. Defaulting to GO.",
            )
            state.status = PipelineStatus.EXTRACTING_REQUIREMENTS
            return state

        # ── 3. Load pre-extracted company policies ──────
        mcp = MCPService()
        policies = mcp.get_extracted_policies()
        logger.debug(f"[A3] Loaded {len(policies)} pre-extracted policies")
        policies_text = json.dumps(policies, indent=2) if policies else "No company policies extracted yet."

        # ── 4. Load company capabilities for enrichment ─
        capabilities = mcp.query_knowledge("company capabilities services", top_k=10)
        logger.debug(f"[A3] Loaded {len(capabilities)} capability chunks")
        capabilities_text = "\n".join(
            c.get("text", "") for c in capabilities if c.get("text")
        )
        if not capabilities_text.strip():
            capabilities_text = "No capability data available."

        # ── 5. Build prompt ─────────────────────────────
        prompt = self._build_prompt(rfp_sections_text, policies_text, capabilities_text)
        logger.debug(
            f"[A3] Prompt built — {len(prompt)} chars "
            f"(RFP: {len(rfp_sections_text)} | Policies: {len(policies_text)} | Capabilities: {len(capabilities_text)})"
        )

        # ── 6. Call LLM ─────────────────────────────────
        logger.info("[A3] Calling LLM for Go/No-Go analysis…")
        raw_response = llm_text_call(prompt)
        logger.debug(f"[A3] Raw LLM response ({len(raw_response)} chars):\n{raw_response[:2000]}")

        # ── 7. Parse response ───────────────────────────
        result = self._parse_response(raw_response)

        # ── 8. Update state ─────────────────────────────
        state.go_no_go_result = result

        if result.decision == GoNoGoDecision.NO_GO:
            state.status = PipelineStatus.NO_GO
            logger.info(f"[A3] Decision: NO_GO — {result.justification}")
        else:
            state.status = PipelineStatus.EXTRACTING_REQUIREMENTS
            logger.info(f"[A3] Decision: GO — {result.justification}")

        # ── Detailed decision dump (INFO for visibility) ──
        self._log_mapping_table(result)

        return state

    # ── Helpers ──────────────────────────────────────────

    def _format_sections(self, sections: list) -> str:
        """Format structuring result sections into readable text."""
        if not sections:
            return ""
        parts = []
        for s in sections:
            title = getattr(s, "title", str(s)) if not isinstance(s, dict) else s.get("title", "")
            category = getattr(s, "category", "") if not isinstance(s, dict) else s.get("category", "")
            summary = getattr(s, "content_summary", "") if not isinstance(s, dict) else s.get("content_summary", "")
            parts.append(f"### {title} [{category}]\n{summary}")
        return "\n\n".join(parts)

    def _log_mapping_table(self, result: GoNoGoResult) -> None:
        """Log a formatted requirement-mapping table at INFO level."""
        # ── Scores summary ──
        logger.info(
            f"[A3] Scores → strategic_fit={result.strategic_fit_score:.1f}/10, "
            f"technical_feasibility={result.technical_feasibility_score:.1f}/10, "
            f"regulatory_risk={result.regulatory_risk_score:.1f}/10"
        )

        # ── Counts ──
        logger.info(
            f"[A3] Mappings → total={result.total_requirements}, "
            f"aligned={result.aligned_count}, violated={result.violated_count}, "
            f"risk={result.risk_count}, no_match={result.no_match_count}"
        )

        if result.policy_violations:
            logger.info(f"[A3] Policy violations: {result.policy_violations}")
        if result.red_flags:
            logger.info(f"[A3] Red flags: {result.red_flags}")

        # ── Formatted table ──
        if not result.requirement_mappings:
            logger.info("[A3] No requirement mappings produced.")
            return

        # Column widths
        id_w, status_w, conf_w = 14, 10, 6
        req_w, policy_w, reason_w = 40, 30, 30

        sep = f"╠{'═'*id_w}╬{'═'*status_w}╬{'═'*conf_w}╬{'═'*req_w}╬{'═'*policy_w}╬{'═'*reason_w}╣"
        top = f"╔{'═'*id_w}╦{'═'*status_w}╦{'═'*conf_w}╦{'═'*req_w}╦{'═'*policy_w}╦{'═'*reason_w}╗"
        bot = f"╚{'═'*id_w}╩{'═'*status_w}╩{'═'*conf_w}╩{'═'*req_w}╩{'═'*policy_w}╩{'═'*reason_w}╝"

        def pad(text: str, width: int) -> str:
            return (text[:width-1] + "…" if len(text) >= width else text).ljust(width)

        header = (
            f"║{pad('Requirement ID', id_w)}║{pad('Status', status_w)}║{pad('Conf.', conf_w)}"
            f"║{pad('Requirement Text', req_w)}║{pad('Matched Policy', policy_w)}║{pad('Reasoning', reason_w)}║"
        )

        lines = [
            f"[A3] ╔{'═' * (id_w + status_w + conf_w + req_w + policy_w + reason_w + 5)}╗",
            f"[A3] ║  REQUIREMENT MAPPING RESULTS — {result.total_requirements} requirements{' ' * max(0, id_w + status_w + conf_w + req_w + policy_w + reason_w + 5 - 35 - len(str(result.total_requirements)))}║",
            f"[A3] {top}",
            f"[A3] {header}",
            f"[A3] {sep}",
        ]

        for m in result.requirement_mappings:
            row = (
                f"║{pad(m.requirement_id, id_w)}"
                f"║{pad(m.mapping_status, status_w)}"
                f"║{pad(f'{m.confidence:.2f}', conf_w)}"
                f"║{pad(m.requirement_text, req_w)}"
                f"║{pad(m.matched_policy or '—', policy_w)}"
                f"║{pad(m.reasoning or '—', reason_w)}║"
            )
            lines.append(f"[A3] {row}")

        lines.append(f"[A3] {bot}")

        logger.info("\n".join(lines))

    def _build_prompt(
        self, rfp_sections: str, policies: str, capabilities: str
    ) -> str:
        template = _PROMPT_PATH.read_text(encoding="utf-8")
        return (
            template
            .replace("{rfp_sections}", rfp_sections[:12_000])
            .replace("{company_policies}", policies[:8_000])
            .replace("{capabilities}", capabilities[:5_000])
        )

    def _parse_response(self, raw: str) -> GoNoGoResult:
        """Parse the LLM JSON response into a GoNoGoResult."""
        # Strip markdown fencing
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        data: dict[str, Any] = {}
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Fallback: find first { ... } block
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        if not data:
            logger.error("[A3] Failed to parse LLM response — defaulting to GO")
            return GoNoGoResult(
                decision=GoNoGoDecision.GO,
                justification="LLM response parsing failed. Defaulting to GO for manual review.",
            )

        # Parse requirement mappings
        mappings: list[RequirementMapping] = []
        for m in data.get("requirement_mappings", []):
            if isinstance(m, dict):
                mappings.append(RequirementMapping(
                    requirement_id=m.get("requirement_id", ""),
                    requirement_text=m.get("requirement_text", ""),
                    source_section=m.get("source_section", ""),
                    mapping_status=m.get("mapping_status", "NO_MATCH").upper(),
                    matched_policy=m.get("matched_policy", ""),
                    matched_policy_id=m.get("matched_policy_id", ""),
                    confidence=float(m.get("confidence", 0.0)),
                    reasoning=m.get("reasoning", ""),
                ))

        # Compute counts
        aligned = sum(1 for m in mappings if m.mapping_status == "ALIGNS")
        violated = sum(1 for m in mappings if m.mapping_status == "VIOLATES")
        risk = sum(1 for m in mappings if m.mapping_status == "RISK")
        no_match = sum(1 for m in mappings if m.mapping_status == "NO_MATCH")

        # Determine decision
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
