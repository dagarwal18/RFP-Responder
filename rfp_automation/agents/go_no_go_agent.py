"""
A3 — Go / No-Go Agent
Responsibility: Score strategic fit, technical feasibility, regulatory risk.
                Apply MCP policy rules for hard disqualification.
                Produce GO or NO_GO with justification.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, PipelineStatus, GoNoGoDecision
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import GoNoGoResult


class GoNoGoAgent(BaseAgent):
    name = AgentName.A3_GO_NO_GO

    def _mock_process(self, state: RFPGraphState) -> RFPGraphState:
        state.go_no_go_result = GoNoGoResult(
            decision=GoNoGoDecision.GO,
            strategic_fit_score=8.5,
            technical_feasibility_score=9.0,
            regulatory_risk_score=7.5,
            policy_violations=[],
            red_flags=[],
            justification=(
                "Strong strategic fit — cloud migration aligns with our core competency. "
                "We hold both SOC 2 Type II and ISO 27001 certifications. "
                "5+ years of multi-cloud experience demonstrated across 12 enterprise engagements. "
                "No policy rule violations detected. Recommendation: GO."
            ),
        )
        state.status = PipelineStatus.GO_NO_GO
        return state
