"""
E2 — Legal Agent
Responsibility: Analyse contract clauses for risk, check compliance
                certifications.  Has VETO authority (BLOCK → pipeline ends).
                Runs in parallel with E1 Commercial.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, PipelineStatus, LegalDecision, RiskLevel
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import LegalResult, ContractClauseRisk


class LegalAgent(BaseAgent):
    name = AgentName.E2_LEGAL

    def _mock_process(self, state: RFPGraphState) -> RFPGraphState:
        clause_risks = [
            ContractClauseRisk(
                clause_id="CL-01",
                clause_text="Vendor liability shall be limited to 2x annual contract value.",
                risk_level=RiskLevel.LOW,
                concern="Liability cap is within acceptable range.",
                recommendation="Accept as-is.",
            ),
            ContractClauseRisk(
                clause_id="CL-02",
                clause_text="All intellectual property developed during engagement belongs to Client.",
                risk_level=RiskLevel.MEDIUM,
                concern="Broad IP assignment could affect reuse of internal tooling.",
                recommendation="Negotiate carve-out for pre-existing IP and general-purpose tools.",
            ),
            ContractClauseRisk(
                clause_id="CL-03",
                clause_text="Vendor shall indemnify Client against all third-party claims.",
                risk_level=RiskLevel.MEDIUM,
                concern="Unlimited indemnification scope.",
                recommendation="Limit indemnification to claims arising from vendor's negligence.",
            ),
        ]

        state.legal_result = LegalResult(
            decision=LegalDecision.CONDITIONAL,
            clause_risks=clause_risks,
            compliance_status={
                "SOC 2 Type II": True,
                "ISO 27001": True,
                "GDPR DPA": True,
            },
            block_reasons=[],
            risk_register_summary=(
                "No critical risk items. Two medium-risk clauses identified (IP ownership, "
                "indemnification scope) — recommend negotiation during contracting phase. "
                "All required certifications are held. Decision: CONDITIONAL (proceed with caveats)."
            ),
        )
        state.status = PipelineStatus.COMMERCIAL_LEGAL_REVIEW
        return state
