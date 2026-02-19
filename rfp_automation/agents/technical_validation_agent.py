"""
D1 — Technical Validation Agent
Responsibility: Validate assembled proposal against original requirements.
                Check completeness, alignment, realism, consistency.
                REJECT loops back to C3 (max 3 retries).
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class TechnicalValidationAgent(BaseAgent):
    name = AgentName.D1_TECHNICAL_VALIDATION

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: LLM validation + MCP rule checks
        raise NotImplementedError(f"{self.name.value} not yet implemented")
