"""
B2 — Requirements Validation Agent
Responsibility: Cross-check extracted requirements for completeness,
                duplicates, contradictions, and ambiguities.
                Issues do NOT block the pipeline — they flow forward as context.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class RequirementsValidationAgent(BaseAgent):
    name = AgentName.B2_REQUIREMENTS_VALIDATION

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: LLM validation of extracted requirements
        raise NotImplementedError(f"{self.name.value} not yet implemented")
