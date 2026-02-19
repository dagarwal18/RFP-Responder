"""
B1 — Requirements Extraction Agent
Responsibility: Extract every requirement from the RFP, classify by type,
                category, and impact, and assign unique IDs.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class RequirementsExtractionAgent(BaseAgent):
    name = AgentName.B1_REQUIREMENTS_EXTRACTION

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: LLM extraction per section via MCP
        raise NotImplementedError(f"{self.name.value} not yet implemented")
