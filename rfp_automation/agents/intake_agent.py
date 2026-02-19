"""
A1 — Intake Agent
Responsibility: Validate uploaded file, extract text, chunk & embed into MCP,
                initialise RFP metadata in state.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, PipelineStatus
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import RFPMetadata
from rfp_automation.services.parsing_service import ParsingService
from rfp_automation.mcp import MCPService

logger = logging.getLogger(__name__)


class IntakeAgent(BaseAgent):
    name = AgentName.A1_INTAKE

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        file_path = state.uploaded_file_path

        # ── 1. Validate file ─────────────────────────────
        if not file_path:
            raise ValueError("No file path provided in state")

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Uploaded file not found: {file_path}")

        supported = {".pdf", ".docx"}
        if path.suffix.lower() not in supported:
            raise ValueError(
                f"Unsupported file type: {path.suffix}. Supported: {supported}"
            )

        # ── 2. Parse document ────────────────────────────
        logger.info(f"Parsing file: {file_path}")
        raw_text = ParsingService.parse(file_path)

        if not raw_text or len(raw_text.strip()) < 50:
            raise ValueError("Parsed text is too short or empty — invalid document")

        # ── 3. Extract metadata ──────────────────────────
        rfp_id = f"RFP-{uuid.uuid4().hex[:8].upper()}"
        word_count = len(raw_text.split())

        # Rough page estimate: ~400 words per page
        page_count = max(1, word_count // 400)

        # Heuristic title extraction: first non-empty line
        lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
        title = lines[0][:200] if lines else "Untitled RFP"

        metadata = RFPMetadata(
            rfp_id=rfp_id,
            rfp_title=title,
            source_file_path=str(path),
            page_count=page_count,
            word_count=word_count,
        )

        # ── 4. Embed into vector store ───────────────────
        logger.info(f"Embedding {rfp_id} into vector store")
        mcp = MCPService()
        chunk_count = mcp.store_rfp_document(
            rfp_id=rfp_id,
            raw_text=raw_text,
            metadata={"source_file": path.name},
        )
        logger.info(f"Stored {chunk_count} chunks for {rfp_id}")

        # ── 5. Update state ──────────────────────────────
        state.rfp_metadata = metadata
        state.raw_text = raw_text
        state.status = PipelineStatus.STRUCTURING

        return state
