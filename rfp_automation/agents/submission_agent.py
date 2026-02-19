"""
F2 — Submission & Archive Agent
Responsibility: Apply final formatting, package deliverables, archive to
                storage with file hashes for auditability.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class SubmissionAgent(BaseAgent):
    name = AgentName.F2_SUBMISSION

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: Packaging + hashing + archiving
        raise NotImplementedError(f"{self.name.value} not yet implemented")
