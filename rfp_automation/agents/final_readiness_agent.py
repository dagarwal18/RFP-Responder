"""
F1 — Final Readiness Agent
Responsibility: Compile the approval package (proposal, pricing, legal risk
                register, coverage matrix, decision brief) and trigger the
                human approval gate.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class FinalReadinessAgent(BaseAgent):
    name = AgentName.F1_FINAL_READINESS

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: Compile approval package from state fields
        raise NotImplementedError(f"{self.name.value} not yet implemented")
