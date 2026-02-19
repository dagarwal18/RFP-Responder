"""
A3 — Go / No-Go Agent
Responsibility: Score strategic fit, technical feasibility, regulatory risk.
                Apply MCP policy rules for hard disqualification.
                Produce GO or NO_GO with justification.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class GoNoGoAgent(BaseAgent):
    name = AgentName.A3_GO_NO_GO

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: LLM scoring + MCP policy rules
        raise NotImplementedError(f"{self.name.value} not yet implemented")
