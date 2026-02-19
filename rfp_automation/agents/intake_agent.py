"""
A1 — Intake Agent
Responsibility: Validate uploaded file, extract text, chunk & embed into MCP,
                initialise RFP metadata in state.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, PipelineStatus
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import RFPMetadata


class IntakeAgent(BaseAgent):
    name = AgentName.A1_INTAKE

    # ── Mock ─────────────────────────────────────────────

    def _mock_process(self, state: RFPGraphState) -> RFPGraphState:
        rfp_id = f"RFP-{uuid.uuid4().hex[:8].upper()}"

        state.rfp_metadata = RFPMetadata(
            rfp_id=rfp_id,
            client_name="Acme Corporation",
            rfp_title="Enterprise Cloud Migration Platform",
            deadline=datetime.utcnow() + timedelta(days=30),
            rfp_number="RFP-2026-0042",
            source_file_path=state.uploaded_file_path or "/uploads/acme_rfp.pdf",
            page_count=45,
            word_count=12500,
        )

        state.raw_text = (
            "This is a mock RFP document for an Enterprise Cloud Migration Platform. "
            "The system must support multi-cloud environments including AWS, Azure, and GCP. "
            "Security compliance with SOC 2 Type II and ISO 27001 is mandatory. "
            "The vendor must demonstrate at least 5 years of cloud migration experience. "
            "Response deadline: 30 days from issue date."
        )

        state.status = PipelineStatus.RECEIVED
        return state

    # ── Real (override later) ────────────────────────────

    # def _real_process(self, state: RFPGraphState) -> RFPGraphState:
    #     TODO: File validation, PDF/DOCX extraction, chunking, MCP embedding
    #     ...
