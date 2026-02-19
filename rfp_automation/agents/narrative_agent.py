"""
C3 — Narrative Assembly Agent
Responsibility: Combine section responses into a cohesive proposal with
                executive summary, transitions, and coverage appendix.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class NarrativeAssemblyAgent(BaseAgent):
    name = AgentName.C3_NARRATIVE_ASSEMBLY

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: LLM assembly + executive summary
        raise NotImplementedError(f"{self.name.value} not yet implemented")
