"""
C1 — Architecture Planning Agent
Responsibility: Group requirements into response sections, map each to
                company capabilities.  Verify every mandatory requirement
                appears in the plan.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class ArchitecturePlanningAgent(BaseAgent):
    name = AgentName.C1_ARCHITECTURE_PLANNING

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: LLM grouping + MCP capability matching
        raise NotImplementedError(f"{self.name.value} not yet implemented")
