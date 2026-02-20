"""
A1 — Intake Agent

Responsibility:
  Validate uploaded PDF, compute SHA-256 hash, extract structured text blocks,
  extract metadata via regex, prepare chunks, send to MCP, update state.

Does NOT: summarize, interpret, extract requirements, call LLM, embed,
          vectorize, or parse table cells.
"""

from __future__ import annotations

import hashlib
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

        # ── 1. File validation ───────────────────────────
        if not file_path:
            raise ValueError("No file path provided in state")

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Uploaded file not found: {file_path}")

        if path.suffix.lower() != ".pdf":
            raise ValueError(
                f"Unsupported file type: {path.suffix}. Only .pdf supported."
            )

        # ── 1b. SHA-256 hash ─────────────────────────────
        file_bytes = path.read_bytes()
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        logger.info(f"[A1] File validated — size: {len(file_bytes):,} bytes, SHA-256: {file_hash}")

        # ── 2. Extract structured blocks ─────────────────
        logger.info(f"[A1] Parsing file: {file_path}")
        blocks = ParsingService.parse_pdf_blocks(file_path)

        if not blocks:
            raise ValueError("No text blocks extracted from document")

        logger.debug(f"[A1] Extracted {len(blocks)} raw blocks")
        block_types = {}
        for b in blocks:
            bt = b.get("type", "unknown")
            block_types[bt] = block_types.get(bt, 0) + 1
        logger.debug(f"[A1] Block type distribution: {block_types}")

        # ── 3. Extract metadata via regex ────────────────
        extracted_meta = ParsingService.extract_metadata(blocks)
        logger.info(f"[A1] Extracted metadata: {extracted_meta}")

        # ── 4. Prepare structured chunks ─────────────────
        chunks = ParsingService.prepare_chunks(blocks)
        logger.info(f"[A1] Prepared {len(chunks)} chunks")
        for i, c in enumerate(chunks[:5]):
            logger.debug(f"[A1]   Chunk {i}: type={c.get('content_type')} section={c.get('section_hint')} len={len(c.get('text',''))}")
        if len(chunks) > 5:
            logger.debug(f"[A1]   ... and {len(chunks) - 5} more chunks")

        # ── 5. Build concatenated raw text ───────────────
        raw_text = "\n".join(b["text"] for b in blocks)

        # ── 6. Build metadata object ─────────────────────
        rfp_id = (
            extracted_meta.get("rfp_number")
            or f"RFP-{uuid.uuid4().hex[:8].upper()}"
        )

        # ── 7. Send chunks to MCP (rfp_id must exist) ───
        mcp = MCPService()
        mcp.store_rfp_chunks(rfp_id, chunks, source_file=file_path)
        logger.info(f"[A1] Sent {len(chunks)} chunks to MCP for rfp_id={rfp_id}")
        word_count = len(raw_text.split())
        logger.debug(f"[A1] Raw text: {word_count} words, {len(raw_text)} chars")

        # ── 8. Page count, title, final metadata ────────
        # Real page count from extracted blocks
        page_numbers = {b["page_number"] for b in blocks}
        page_count = max(page_numbers) if page_numbers else 0

        # Title: first heading block, else first text line
        title = "Untitled RFP"
        for b in blocks:
            if b["type"] == "heading":
                title = b["text"][:200]
                break
        if title == "Untitled RFP":
            first_text = next(
                (b["text"] for b in blocks if b["type"] != "table_mock"), ""
            )
            if first_text:
                title = first_text.split("\n")[0][:200]

        metadata = RFPMetadata(
            rfp_id=rfp_id,
            rfp_title=title,
            rfp_number=extracted_meta.get("rfp_number") or "",
            client_name=extracted_meta.get("organization") or "",
            source_file_path=str(path.resolve()),
            page_count=page_count,
            word_count=word_count,
            file_hash=file_hash,
            contact_email=extracted_meta.get("contact_email"),
            contact_phone=extracted_meta.get("contact_phone"),
            issue_date=extracted_meta.get("issue_date"),
            deadline_text=extracted_meta.get("deadline"),
        )

        # ── 9. Update state ──────────────────────────────
        state.rfp_metadata = metadata
        state.uploaded_file_path = str(path.resolve())
        state.raw_text = raw_text
        state.status = PipelineStatus.INTAKE_COMPLETE

        logger.info(
            f"[A1] Intake complete — rfp_id={rfp_id}, title={metadata.rfp_title!r}, "
            f"pages={metadata.page_count}, words={word_count}"
        )
        logger.debug(f"[A1] Full metadata: {metadata.model_dump_json(indent=2)}")

        return state
