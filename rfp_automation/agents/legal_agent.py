"""
E2 — Legal Agent
Responsibility: Analyse contract clauses for risk, check compliance
                certifications.  Has VETO authority (BLOCK → pipeline ends).
                Runs in parallel with E1 Commercial.

Processing Flow:
  1. Extract contract clauses from RFP (MCP + structuring result)
  2. Load legal templates from knowledge base
  3. Load certification data (held vs required)
  4. Rule-based clause scoring (deterministic)
  5. LLM clause analysis + risk register narrative
  6. Compliance certification check
  7. Determine decision (APPROVED / CONDITIONAL / BLOCKED)
  8. Write LegalResult to state
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import (
    AgentName,
    LegalDecision,
    PipelineStatus,
    RiskLevel,
)
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import (
    ComplianceCheck,
    ContractClauseRisk,
    LegalResult,
)
from rfp_automation.mcp import MCPService
from rfp_automation.services.llm_service import llm_large_text_call

logger = logging.getLogger(__name__)

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "legal_prompt.txt"
)


class LegalAgent(BaseAgent):
    name = AgentName.E2_LEGAL

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        rfp_id = state.rfp_metadata.rfp_id
        logger.info(f"[E2] Starting legal analysis for {rfp_id}")

        mcp = MCPService()

        # ── Step 1: Extract Contract Clauses ─────────────
        clause_texts = self._extract_clauses(state, mcp, rfp_id)
        logger.info(f"[E2] Extracted {len(clause_texts)} contract clause(s)")

        # ── Step 2: Load Legal Templates ─────────────────
        templates = self._load_legal_templates(mcp)
        logger.info(f"[E2] Loaded {len(templates)} legal template(s)")

        # ── Step 3: Load Certifications ──────────────────
        held_certs = mcp.get_certifications_from_policies()
        required_certs = self._extract_required_certs(state, mcp, rfp_id)
        logger.info(
            f"[E2] Certifications — held: {len(held_certs)}, "
            f"required: {len(required_certs)}"
        )

        # ── Step 4: Rule-Based Clause Scoring ────────────
        rule_result = mcp.legal_rules.evaluate_clauses(clause_texts)
        rules_blocked = rule_result.get("blocked", False)
        rule_block_reasons = rule_result.get("block_reasons", [])
        logger.info(
            f"[E2] Rule scoring — aggregate_risk={rule_result.get('aggregate_risk')}, "
            f"blocked={rules_blocked}"
        )

        # ── Step 5: LLM Clause Analysis ──────────────────
        llm_clause_risks: list[dict] = []
        risk_narrative = ""
        llm_decision = "APPROVED"
        llm_block_reasons: list[str] = []
        llm_confidence = 0.8

        try:
            llm_data = self._run_llm_analysis(
                clause_texts, templates, required_certs,
                held_certs, rule_result,
            )
            llm_clause_risks = llm_data.get("clause_risks", [])
            risk_narrative = llm_data.get("risk_register_summary", "")
            llm_decision = llm_data.get("decision", "APPROVED").upper()
            llm_block_reasons = llm_data.get("block_reasons", [])
            llm_confidence = float(llm_data.get("confidence", 0.8))
        except Exception as exc:
            logger.warning(f"[E2] LLM analysis failed: {exc}")
            risk_narrative = (
                "LLM legal analysis unavailable. Manual legal review is required "
                "before the proposal can proceed."
            )
            llm_decision = "BLOCKED"
            llm_block_reasons = [
                "Legal analysis output could not be parsed. Manual legal review required."
            ]
            llm_confidence = 0.0

        # ── Step 6: Compliance Check ─────────────────────
        compliance_checks = self._check_compliance(
            required_certs, held_certs, mcp,
        )
        compliance_gaps = [
            c for c in compliance_checks if c.required and not c.held
        ]
        critical_gaps = [
            c for c in compliance_gaps if c.gap_severity == "critical"
        ]
        high_gaps = [
            c for c in compliance_gaps if c.gap_severity == "high"
        ]
        logger.info(
            f"[E2] Compliance — {len(compliance_gaps)} gap(s), "
            f"{len(critical_gaps)} critical, {len(high_gaps)} high"
        )

        # ── Step 7: Determine Decision ───────────────────
        decision, block_reasons = self._determine_decision(
            rules_blocked, rule_block_reasons,
            llm_decision, llm_block_reasons,
            llm_clause_risks, critical_gaps, high_gaps,
        )

        # Build ContractClauseRisk objects from LLM + rules
        clause_risk_objects = self._build_clause_risks(
            llm_clause_risks, clause_texts, rule_result,
        )

        # Compliance status dict for backward compatibility
        compliance_status = {c.certification: c.held for c in compliance_checks}

        confidence = llm_confidence if not rules_blocked else 0.95

        logger.info(f"[E2] Decision: {decision.value} (confidence={confidence:.2f})")
        if block_reasons:
            logger.warning(f"[E2] Block reasons: {block_reasons}")

        # ── Step 8: Write to State ───────────────────────
        state.legal_result = LegalResult(
            decision=decision,
            clause_risks=clause_risk_objects,
            compliance_checks=compliance_checks,
            compliance_status=compliance_status,
            block_reasons=block_reasons,
            risk_register_summary=risk_narrative,
            confidence=confidence,
        )
        state.status = PipelineStatus.COMMERCIAL_LEGAL_REVIEW

        return state

    # ── Helpers ──────────────────────────────────────────

    def _extract_clauses(
        self, state: RFPGraphState, mcp: MCPService, rfp_id: str,
    ) -> list[str]:
        """Extract contract/legal clauses from structuring result + MCP."""
        clauses: list[str] = []

        # From structuring result — sections categorised as "legal"
        for section in state.structuring_result.sections:
            cat = section.category.lower() if isinstance(section.category, str) else ""
            if cat in ("legal", "contract", "terms", "compliance"):
                if section.content_summary:
                    clauses.append(section.content_summary)

        # From MCP — semantic search for legal content
        if rfp_id:
            legal_chunks = mcp.query_rfp(
                "contract clauses terms conditions liability indemnification",
                rfp_id=rfp_id,
                top_k=10,
            )
            for chunk in legal_chunks:
                text = chunk.get("text", "")
                if text and text not in clauses:
                    clauses.append(text)

        # Fallback: if no clauses found, use a placeholder
        if not clauses:
            logger.warning("[E2] No contract clauses found in RFP")
            clauses = ["No explicit contract clauses found in the RFP document."]

        return clauses

    def _load_legal_templates(self, mcp: MCPService) -> list[dict]:
        """Load acceptable legal clause templates from knowledge base."""
        templates_raw = mcp.query_knowledge(
            "legal templates acceptable clauses", top_k=10,
            doc_type="legal",
        )

        templates: list[dict] = []
        for item in templates_raw:
            text = item.get("text", "")
            if text:
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        templates.extend(parsed)
                    elif isinstance(parsed, dict):
                        templates.append(parsed)
                except (json.JSONDecodeError, TypeError):
                    templates.append({"clause_type": "unknown", "text": text})

        # Fallback: load from file
        if not templates:
            try:
                templates_path = (
                    Path(__file__).resolve().parent.parent
                    / "mcp" / "knowledge_data" / "legal_templates.json"
                )
                raw = templates_path.read_text(encoding="utf-8")
                templates = json.loads(raw)
            except Exception as exc:
                logger.warning(f"[E2] Failed to load legal_templates.json: {exc}")

        return templates

    def _extract_required_certs(
        self, state: RFPGraphState, mcp: MCPService, rfp_id: str,
    ) -> list[str]:
        """Extract certifications required by the RFP."""
        certs: set[str] = set()

        # From requirements
        reqs = (
            state.requirements_validation.validated_requirements
            or state.requirements
        )
        cert_keywords = [
            "iso 27001", "soc 2", "soc2", "fedramp", "hipaa", "pci dss",
            "pci-dss", "gdpr", "ccpa", "iso 9001", "cmmi", "nist",
        ]
        for req in reqs:
            text_lower = req.text.lower()
            for kw in cert_keywords:
                if kw in text_lower:
                    certs.add(kw.upper().replace("-", " "))

        # From MCP — search for certification mentions
        if rfp_id:
            cert_chunks = mcp.query_rfp(
                "certifications compliance requirements ISO SOC",
                rfp_id=rfp_id, top_k=5,
            )
            for chunk in cert_chunks:
                text = chunk.get("text", "").lower()
                for kw in cert_keywords:
                    if kw in text:
                        certs.add(kw.upper().replace("-", " "))

        return list(certs)

    def _check_compliance(
        self,
        required_certs: list[str],
        held_certs: dict[str, bool],
        mcp: MCPService,
    ) -> list[ComplianceCheck]:
        """Build compliance checks for required vs held certifications."""
        # Get severity config from rules
        config = mcp.legal_rules._config_store.get_legal_config()
        # Get certification gap severity from policy rules config
        policy_config = mcp.policy_rules._config_store.get_policy_config()
        severity_map = policy_config.certification_gap_severity

        checks: list[ComplianceCheck] = []

        # Normalize held cert names for matching
        held_names_lower = {name.lower(): held for name, held in held_certs.items()}

        for cert in required_certs:
            cert_lower = cert.lower()
            is_held = any(
                cert_lower in k or k in cert_lower
                for k in held_names_lower.keys()
            )
            gap_severity = "low"
            if not is_held:
                # Look up severity from config
                for config_cert, sev in severity_map.items():
                    if config_cert.lower() in cert_lower or cert_lower in config_cert.lower():
                        gap_severity = sev
                        break
                else:
                    gap_severity = "medium"  # default for unknown certs

            checks.append(ComplianceCheck(
                certification=cert,
                held=is_held,
                required=True,
                gap_severity=gap_severity if not is_held else "low",
            ))

        return checks

    def _run_llm_analysis(
        self,
        clauses: list[str],
        templates: list[dict],
        required_certs: list[str],
        held_certs: dict[str, bool],
        rule_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Call LLM for clause analysis and risk narrative."""
        # Format inputs
        clauses_text = "\n\n".join(
            f"Clause {i+1}:\n{clause}" for i, clause in enumerate(clauses)
        )
        templates_text = json.dumps(templates, indent=2)[:6000]
        required_text = ", ".join(required_certs) if required_certs else "None specified"
        held_text = ", ".join(
            k for k, v in held_certs.items() if v
        ) if held_certs else "None on file"

        # Format rule scores
        clause_scores = rule_result.get("clause_scores", [])
        rule_scores_text = "\n".join(
            f"  Clause {i+1}: score={cs.get('score', 0)}, "
            f"risk={cs.get('risk_level', 'low')}, "
            f"blocked={cs.get('blocked', False)}, "
            f"triggers={cs.get('triggers', [])}"
            for i, cs in enumerate(clause_scores)
        )
        if not rule_scores_text:
            rule_scores_text = "No pre-computed scores available."

        # Build prompt
        template = _PROMPT_PATH.read_text(encoding="utf-8")
        prompt = (
            template
            .replace("{clauses}", clauses_text[:8000])
            .replace("{legal_templates}", templates_text)
            .replace("{required_certifications}", required_text)
            .replace("{held_certifications}", held_text)
            .replace("{rule_scores}", rule_scores_text)
        )

        logger.info(f"[E2] Calling LLM for legal analysis ({len(prompt)} chars)")
        raw = llm_large_text_call(prompt, deterministic=True)
        logger.debug(f"[E2] LLM legal response ({len(raw)} chars)")

        return self._parse_llm_response(raw)

    def _parse_llm_response(self, raw: str) -> dict[str, Any]:
        """Parse LLM JSON response."""
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        logger.warning(
            "[E2] Failed to parse LLM response as JSON | preview=%r",
            cleaned[:300],
        )
        raise ValueError("Failed to parse legal LLM response as JSON")

    def _build_clause_risks(
        self,
        llm_risks: list[dict],
        clause_texts: list[str],
        rule_result: dict[str, Any],
    ) -> list[ContractClauseRisk]:
        """Build ContractClauseRisk objects from LLM output + rule scores."""
        risks: list[ContractClauseRisk] = []

        if llm_risks:
            for item in llm_risks:
                risk_str = item.get("risk_level", "LOW").upper()
                try:
                    risk_level = RiskLevel(risk_str)
                except (ValueError, KeyError):
                    risk_level = RiskLevel.LOW

                risks.append(ContractClauseRisk(
                    clause_id=item.get("clause_id", f"CLAUSE-{len(risks)+1:03d}"),
                    clause_text=item.get("clause_text", "")[:500],
                    risk_level=risk_level,
                    concern=item.get("concern", ""),
                    recommendation=item.get("recommendation", "accept"),
                ))
        else:
            # Fallback to rule-based scores only
            clause_scores = rule_result.get("clause_scores", [])
            for i, (clause, score) in enumerate(
                zip(clause_texts, clause_scores), start=1
            ):
                risk_str = score.get("risk_level", "low").upper()
                try:
                    risk_level = RiskLevel(risk_str)
                except (ValueError, KeyError):
                    risk_level = RiskLevel.LOW

                risks.append(ContractClauseRisk(
                    clause_id=f"CLAUSE-{i:03d}",
                    clause_text=clause[:500],
                    risk_level=risk_level,
                    concern="; ".join(score.get("triggers", [])),
                    recommendation="reject" if score.get("blocked") else "accept",
                ))

        return risks

    def _determine_decision(
        self,
        rules_blocked: bool,
        rule_block_reasons: list[str],
        llm_decision: str,
        llm_block_reasons: list[str],
        llm_clause_risks: list[dict],
        critical_cert_gaps: list[ComplianceCheck],
        high_cert_gaps: list[ComplianceCheck] | None = None,
    ) -> tuple[LegalDecision, list[str]]:
        """Combine rule-based and LLM analysis to produce final decision."""
        block_reasons: list[str] = []
        high_cert_gaps = high_cert_gaps or []

        # Rule auto-block is authoritative
        if rules_blocked:
            block_reasons.extend(rule_block_reasons)

        # LLM block reasons
        if llm_decision == "BLOCKED":
            block_reasons.extend(llm_block_reasons)

        # Critical certification gaps → BLOCK
        for gap in critical_cert_gaps:
            block_reasons.append(
                f"Missing critical certification: {gap.certification}"
            )

        # Check for CRITICAL risks from LLM
        has_critical = any(
            r.get("risk_level", "").upper() == "CRITICAL"
            for r in llm_clause_risks
        )
        if has_critical and not block_reasons:
            block_reasons.append("CRITICAL risk clause(s) identified by analysis")

        # Final decision
        if block_reasons:
            return LegalDecision.BLOCKED, block_reasons

        # HIGH certification gaps → CONDITIONAL
        if high_cert_gaps:
            return LegalDecision.CONDITIONAL, [
                f"Missing high-severity certification: {g.certification}"
                for g in high_cert_gaps
            ]

        # Check for HIGH risks in clauses → CONDITIONAL
        has_high = any(
            r.get("risk_level", "").upper() == "HIGH"
            for r in llm_clause_risks
        )
        if has_high or llm_decision == "CONDITIONAL":
            return LegalDecision.CONDITIONAL, []

        return LegalDecision.APPROVED, []
