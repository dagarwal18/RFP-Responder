"""
E2 — Legal Agent
Responsibility: Analyse contract clauses for risk, check compliance
                certifications.  Has VETO authority (BLOCK → pipeline ends).
                Runs in parallel with E1 Commercial.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class LegalAgent(BaseAgent):
    name = AgentName.E2_LEGAL

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: LLM clause analysis + MCP legal templates
        raise NotImplementedError(f"{self.name.value} not yet implemented")
