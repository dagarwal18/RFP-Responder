"""
A1 — Intake Agent
Responsibility: Validate uploaded file, extract text, chunk & embed into MCP,
                initialise RFP metadata in state.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class IntakeAgent(BaseAgent):
    name = AgentName.A1_INTAKE

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: File validation, PDF/DOCX extraction, chunking, MCP embedding
        raise NotImplementedError(f"{self.name.value} not yet implemented")
