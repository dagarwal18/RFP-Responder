"""
A2 — RFP Structuring Agent
Responsibility: Query MCP RFP store, classify document into sections,
                assign confidence scores.  Retry up to 3x if confidence is low.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class StructuringAgent(BaseAgent):
    name = AgentName.A2_STRUCTURING

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: LLM section classification via MCP RFP store
        raise NotImplementedError(f"{self.name.value} not yet implemented")
