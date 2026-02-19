"""
E1 — Commercial Agent
Responsibility: Generate pricing breakdown using MCP knowledge base pricing
                rules.  Runs in parallel with E2 Legal.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class CommercialAgent(BaseAgent):
    name = AgentName.E1_COMMERCIAL

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: LLM pricing + MCP pricing rules
        raise NotImplementedError(f"{self.name.value} not yet implemented")
