"""
F2 — Submission & Archive Agent
Responsibility: Apply final formatting, package deliverables, archive to
                storage with file hashes for auditability.
"""

from __future__ import annotations

from datetime import datetime

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, PipelineStatus
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import SubmissionRecord
from rfp_automation.utils.hashing import sha256_hash


class SubmissionAgent(BaseAgent):
    name = AgentName.F2_SUBMISSION

    def _mock_process(self, state: RFPGraphState) -> RFPGraphState:
        rfp_id = state.rfp_metadata.rfp_id

        content_hash = sha256_hash(state.assembled_proposal.full_narrative)

        state.submission_record = SubmissionRecord(
            submitted_at=datetime.utcnow(),
            output_file_path=f"/outputs/{rfp_id}/proposal_final.pdf",
            archive_path=f"/archive/{rfp_id}/",
            file_hash=content_hash,
        )
        state.status = PipelineStatus.SUBMITTED
        return state
