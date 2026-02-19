"""
C2 — Requirement Writing Agent
Responsibility: Generate prose response per section using requirement context
                and capability evidence.  Build a coverage matrix.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class RequirementWritingAgent(BaseAgent):
    name = AgentName.C2_REQUIREMENT_WRITING

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: LLM prose generation per section
        raise NotImplementedError(f"{self.name.value} not yet implemented")
