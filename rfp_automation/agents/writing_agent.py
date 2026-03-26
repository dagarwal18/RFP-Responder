"""
C2 — Requirement Writing Agent

Responsibility: Generate prose response per section using requirement context
               and capability evidence.  Build a coverage matrix.

Inputs:
  - architecture_plan.sections (from C1) — section blueprints
  - requirements_validation.validated_requirements (from B2)
  - Falls back to requirements (raw B1 output) if B2 returned empty
  - Company capabilities from MCP Knowledge Store
  - technical_validation.feedback_for_revision — D1 feedback on retry

Outputs:
  - writing_result: WritingResult with section_responses + coverage_matrix
  - status → ASSEMBLING_NARRATIVE
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.config import get_settings
from rfp_automation.models.enums import AgentName, PipelineStatus
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import (
    WritingResult,
    SectionResponse,
    CoverageEntry,
    ResponseSection,
)
from rfp_automation.mcp import MCPService
from rfp_automation.services.llm_service import llm_text_call, llm_large_text_call
from rfp_automation.services.review_service import ReviewService

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "writing_prompt.txt"

# Section types that C2 writes content for.
# commercial and legal are handled by E1 and E2 respectively.
_WRITABLE_SECTION_TYPES = {"requirement_driven", "knowledge_driven", "boilerplate"}

_PLACEHOLDER_RE = re.compile(
    r'\[(?:Insert|Vendor|Company|Client|Authorized|Name|Address|'
    r'Date|Digital Signature|TBD|TODO)[^\]]*\]', re.IGNORECASE,
)
_TABLE_FILL_HEADER_RE = re.compile(
    r'\b(?:'
    r'vendor\s*(?:response|remarks|comments|to\s*fill)'
    r'|compliance(?:\s*status)?'
    r'|c\s*/\s*pc\s*/\s*nc'
    r'|status'
    r'|remarks'
    r'|yes\s*/\s*no'
    r'|bidder'
    r'|offeror'
    r'|proposer'
    r')\b',
    re.IGNORECASE,
)
_TABLE_FILL_PLACEHOLDER_RE = re.compile(
    r'\[(?:'
    r'Vendor\s+to\s+fill[^\]]*'
    r'|C\s*/\s*PC\s*/\s*NC'
    r'|Name\s+OEM'
    r'|Name\s+SIEM'
    r'|Name\s+of\s+PM'
    r')\]',
    re.IGNORECASE,
)
_PRICING_REQ_ID_RE = re.compile(r'^\d+\.\d+$')
_TECHNICAL_REQ_ID_RE = re.compile(r'^TR-\d+$', re.IGNORECASE)
_COMPLIANCE_REQ_ID_RE = re.compile(r'^CM-\d+$', re.IGNORECASE)
_KPI_REQ_ID_RE = re.compile(r'^KPI-\d+$', re.IGNORECASE)
_INTERNAL_REQ_ID_RE = re.compile(r'^REQ-\d{4}$', re.IGNORECASE)
_CLIENT_ROW_ID_RE = re.compile(r'\b(?:TR|KPI|CM)-\d+\b', re.IGNORECASE)
_UNRESOLVED_CELL_RE = re.compile(
    r'\[(?:Vendor\s+to\s+fill|Proposing\s+Company|Name\s+OEM|Name\s+SIEM|Name\s+of\s+PM)[^\]]*\]'
    r'|TBD',
    re.IGNORECASE,
)
_MERMAID_BLOCK_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
_TABLE_ONLY_SECTION_TITLES = {
    "technical implementation",
    "technical implementation — technical compliance matrix",
    "technical solution — technical compliance matrix",
    "pricing schedule matrix",
    "appendix forms & declarations",
}

class RequirementWritingAgent(BaseAgent):
    name = AgentName.C2_REQUIREMENT_WRITING

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # ── 1. Validate prerequisites ───────────────────
        rfp_id = state.rfp_metadata.rfp_id
        if not rfp_id:
            raise ValueError("No rfp_id in state — A1 Intake must run first")

        sections = state.architecture_plan.sections
        if not sections:
            logger.warning("[C2] No sections in architecture plan — nothing to write")
            state.writing_result = WritingResult(
                section_responses=[], coverage_matrix=[]
            )
            state.status = PipelineStatus.ASSEMBLING_NARRATIVE
            return state

        logger.info(
            f"[C2] Starting requirement writing for {rfp_id} — "
            f"{len(sections)} sections in plan"
        )

        # ── 2. Gather requirements ──────────────────────
        requirements = state.requirements_validation.validated_requirements
        if not requirements:
            requirements = state.requirements
            logger.debug("[C2] Using raw B1 requirements (B2 validated list empty)")
        else:
            logger.debug(
                f"[C2] Using {len(requirements)} validated requirements from B2"
            )

        # ── 3. Build requirement lookup map ─────────────
        req_map: dict[str, dict[str, Any]] = {}
        for req in requirements:
            if hasattr(req, "model_dump"):
                d = req.model_dump()
            elif isinstance(req, dict):
                d = req
            else:
                d = {"text": str(req)}
            req_id = d.get("requirement_id", "")
            if req_id:
                existing = req_map.get(req_id)
                if existing is None:
                    req_map[req_id] = d
                    continue

                existing_table = int(existing.get("source_table_chunk_index", -1)) >= 0
                new_table = int(d.get("source_table_chunk_index", -1)) >= 0
                if new_table and not existing_table:
                    req_map[req_id] = d
                elif new_table == existing_table:
                    existing_trace = len(existing.get("source_chunk_indices", []) or [])
                    new_trace = len(d.get("source_chunk_indices", []) or [])
                    if new_trace >= existing_trace:
                        req_map[req_id] = d

        logger.debug(f"[C2] Requirement lookup: {len(req_map)} entries")

        # ── 4. Sort sections by priority ────────────────
        sorted_sections = sorted(
            sections,
            key=lambda s: (
                getattr(s, "priority", 99)
                if not isinstance(s, dict)
                else s.get("priority", 99)
            ),
        )

        # ── 5. Initialize MCP service ──────────────────
        mcp = MCPService()

        # ── 5b. Fetch all RFP chunks for table lookup ───
        all_rfp_chunks = mcp.fetch_all_rfp_chunks(rfp_id)
        table_chunks_by_index: dict[int, dict] = {}
        for ch in all_rfp_chunks:
            if ch.get("content_type") == "table":
                idx = ch.get("chunk_index", -1)
                if idx >= 0:
                    table_chunks_by_index[idx] = ch
        logger.info(
            f"[TABLE-TRACE][C2-WRITE] Loaded {len(table_chunks_by_index)} table chunks "
            f"from {len(all_rfp_chunks)} total RFP chunks"
        )

        # ── 6. RFP response instructions (from C1) ─────
        rfp_instructions = state.architecture_plan.rfp_response_instructions or ""

        # ── 6b. Check for D1 revision feedback ──────────
        revision_feedback = ""
        if state.technical_validation and state.technical_validation.feedback_for_revision:
            revision_feedback = state.technical_validation.feedback_for_revision
            logger.info(f"[C2] D1 revision feedback present ({len(revision_feedback)} chars) — will inject into prompts")
        human_review_feedback = ReviewService.build_global_feedback(state.review_package)

        # ── 7. Prepare RFP metadata for prompt injection ──
        rfp_meta = state.rfp_metadata

        # Resolve company name from KB → config
        company_name = ""
        try:
            kb_profile = mcp.knowledge_base.query_company_profile()
            company_name = kb_profile.get("company_name", "")
            if company_name:
                logger.info(f"[C2] Company profile loaded from MongoDB: {company_name}")
            else:
                logger.warning("[C2] Company profile exists in MongoDB but has no company_name")
        except Exception as e:
            logger.warning(f"[C2] KB company profile fetch failed: {e}", exc_info=True)
        if not company_name:
            company_name = get_settings().company_name or ""

        rfp_metadata_block = (
            f"Proposing Company: {company_name or 'Not configured'}\n"
            f"Client: {rfp_meta.client_name}\n"
            f"RFP Title: {rfp_meta.rfp_title}\n"
            f"RFP Number: {rfp_meta.rfp_number}\n"
            f"Issue Date: {rfp_meta.issue_date or 'Not specified'}\n"
            f"Deadline: {rfp_meta.deadline_text or 'Not specified'}\n"
        )

        # ── 8. Build C1 assignment map (for coverage matrix) ──
        c1_assignments: dict[str, list[str]] = {}  # req_id -> [section_ids]
        for section in sections:
            sid = self._get_attr(section, "section_id", "")
            for rid in self._get_attr(section, "requirement_ids", []):
                c1_assignments.setdefault(rid, []).append(sid)

        # ── 9. Process each section ─────────────────────
        section_responses: list[SectionResponse] = []
        all_addressed: dict[str, list[str]] = {}  # req_id -> [section_ids]

        for section in sorted_sections:
            section_id = self._get_attr(section, "section_id", "")
            section_type = self._get_attr(section, "section_type", "requirement_driven")
            title = self._get_attr(section, "title", "Untitled")

            # ── 7a. Filter writable types ───────────────
            if section_type not in _WRITABLE_SECTION_TYPES:
                logger.info(
                    f"[C2] Skipping section {section_id} ({title}) — "
                    f"type '{section_type}' handled by dedicated agent"
                )
                # Add a PIPELINE_STUB entry so C3 preserves it for E1/E2 injection
                section_responses.append(
                    SectionResponse(
                        section_id=section_id,
                        title=title,
                        content=f"*[PIPELINE_STUB: {title}]*",
                        requirements_addressed=[],
                        word_count=0,
                    )
                )
                continue

            # ── 7a2. Build neighboring section context ───
            idx = sorted_sections.index(section)
            prev_ctx = "This is the first section of the proposal."
            next_ctx = "This is the last section of the proposal."
            if idx > 0:
                prev_s = sorted_sections[idx - 1]
                prev_title = self._get_attr(prev_s, "title", "")
                prev_desc = self._get_attr(prev_s, "description", "")
                prev_ctx = f"{prev_title}: {prev_desc[:200]}" if prev_desc else prev_title
            if idx < len(sorted_sections) - 1:
                next_s = sorted_sections[idx + 1]
                next_title = self._get_attr(next_s, "title", "")
                next_desc = self._get_attr(next_s, "description", "")
                next_ctx = f"{next_title}: {next_desc[:200]}" if next_desc else next_title

            # ── 7b. Resolve requirements for this section ─
            req_ids = self._get_attr(section, "requirement_ids", [])
            requirements_block = self._build_requirements_block(req_ids, req_map)

            # ── 7c. Fetch capabilities from MCP ─────────
            capabilities = self._fetch_section_capabilities(
                mcp, title, req_ids, req_map,
                self._get_attr(section, "mapped_capabilities", []),
            )

            # ── 7d. Filter revision feedback for this section ─
            feedback_parts: list[str] = []
            if revision_feedback and req_ids:
                feedback_lines = []
                # Split feedback by common delimiters to isolate individual points
                parts = re.split(r'[;|\n]', revision_feedback)
                for part in parts:
                    part = part.strip()
                    if not part:
                        continue
                        
                    # CRITICAL FIX: Use strict word boundaries to prevent REQ-001 matching REQ-0011
                    # Keep feedback if it explicitly mentions a REQ belonging to this section
                    if any(re.search(rf'\b{re.escape(rid)}\b', part) for rid in req_ids):
                        # Clean up leading categories (e.g. "Completeness: REQ-001...")
                        clean_part = re.sub(r'^(Completeness|Alignment|Realism|Consistency):\s*', '', part)
                        feedback_lines.append(f"- {clean_part}")
                
                if feedback_lines:
                    feedback_parts.append(
                        "The Technical Validation Agent flagged these issues in your previous draft that MUST BE FIXED:\n"
                        + "\n".join(feedback_lines)
                    )
            elif revision_feedback and not req_ids:
                # If section has no mapped reqs but there is feedback (e.g. executive summary realism),
                # maybe pass general points. But for now, safer to just omit.
                pass

            review_section_feedback = ReviewService.build_section_feedback(
                state.review_package,
                section_id=section_id,
                source_section_title=self._get_attr(section, "source_rfp_section", ""),
            )
            if review_section_feedback:
                feedback_parts.append(review_section_feedback)
            elif human_review_feedback and section_type == "boilerplate":
                feedback_parts.append(human_review_feedback)

            section_feedback = "\n\n".join(part.strip() for part in feedback_parts if part.strip())

            # ── 7e. Detect table/matrix response mode ───
            # Only the dedicated matrix sections are allowed to emit tables.
            # This prevents stray vendor-fill-backed requirements from turning
            # normal narrative sections into malformed table dumps.
            table_mode = self._is_table_only_section(title)

            # ── 7e2. Find original table text from RFP chunks ──
            original_table_text = ""
            if table_mode and req_ids:
                # Look up source chunk indices from the requirements
                for rid in req_ids:
                    req = req_map.get(rid)
                    if req:
                        src_indices = req.get("source_chunk_indices", [])
                        for si in src_indices:
                            tbl_chunk = table_chunks_by_index.get(si)
                            if tbl_chunk and self._is_vendor_fill_table(
                                tbl_chunk.get("text", ""),
                                tbl_chunk.get("table_type", "unknown"),
                            ):
                                original_table_text = self._clean_source_table_text(
                                    tbl_chunk.get("text", "")
                                )
                                logger.info(
                                    f"[TABLE-TRACE][C2-WRITE] Found original table "
                                    f"for section {section_id} from chunk_index={si}, "
                                    f"table_type={tbl_chunk.get('table_type', 'unknown')}, "
                                    f"text_len={len(original_table_text)}"
                                )
                                break
                    if original_table_text:
                        break

            if table_mode:
                logger.info(
                    f"[TABLE-TRACE][C2-WRITE] Table mode ACTIVE for {section_id}: {title} | "
                    f"original_table_found={'YES' if original_table_text else 'NO'} | "
                    f"original_table_len={len(original_table_text)}"
                )
            # ── 7e3. Disable fabricated tables ──────────
            # If table_mode is active but we have no original table from the
            # RFP, turn it off to avoid generating a generic 4-column matrix.
            if table_mode and not original_table_text:
                logger.warning(
                    f"[TABLE-TRACE][C2-WRITE] headers not extracted for section '{section_id}' — "
                    f"preventing fabricated table generation"
                )
                table_mode = False

            # ── 7f. Build prompt & call LLM ────────────────
            # For table-mode sections, group requirements by their source
            # table chunk and process each table independently.  This prevents
            # different tables from being merged together randomly.
            _TABLE_BATCH_SIZE = 12

            if table_mode and original_table_text:
                # ── PER-TABLE ISOLATED PROCESSING ──
                # Group requirements by source_table_chunk_index
                table_groups: dict[int, list[str]] = {}  # chunk_index → [req_ids]
                ungrouped: list[str] = []

                for rid in req_ids:
                    req = req_map.get(rid)
                    if req:
                        tci = req.get("source_table_chunk_index", -1)
                        tbl_chunk = table_chunks_by_index.get(tci)
                        if (
                            tci >= 0
                            and tbl_chunk
                            and self._is_vendor_fill_table(
                                tbl_chunk.get("text", ""),
                                tbl_chunk.get("table_type", "unknown"),
                            )
                        ):
                            table_groups.setdefault(tci, []).append(rid)
                        else:
                            ungrouped.append(rid)
                    else:
                        ungrouped.append(rid)

                # If no requirements were tagged (legacy data), fall back to
                # treating all reqs under the first found table
                if not table_groups and req_ids:
                    first_tci = None
                    for rid in req_ids:
                        req = req_map.get(rid)
                        if req:
                            for si in req.get("source_chunk_indices", []):
                                tbl_chunk = table_chunks_by_index.get(si)
                                if tbl_chunk and self._is_vendor_fill_table(
                                    tbl_chunk.get("text", ""),
                                    tbl_chunk.get("table_type", "unknown"),
                                ):
                                    first_tci = si
                                    break
                        if first_tci is not None:
                            break
                    if first_tci is not None:
                        table_groups[first_tci] = req_ids
                        ungrouped = []

                filtered_groups: dict[int, list[str]] = {}
                for tci, group_rids in table_groups.items():
                    if self._table_group_matches_section(group_rids, section):
                        filtered_groups[tci] = group_rids
                    else:
                        logger.info(
                            f"[TABLE-TRACE][C2-WRITE] Skipping table chunk {tci} for "
                            f"{section_id} because its req IDs {group_rids[:6]} do not "
                            f"fit section '{title}'"
                        )
                        ungrouped.extend(group_rids)
                table_groups = filtered_groups

                logical_groups = self._build_logical_table_groups(
                    table_groups,
                    table_chunks_by_index,
                )

                logger.info(
                    f"[TABLE-TRACE][C2-WRITE] Per-table processing for {section_id}: "
                    f"{len(logical_groups)} logical table group(s), "
                    f"{len(ungrouped)} ungrouped reqs"
                )

                all_table_contents: list[str] = []
                all_table_addressed: list[str] = []
                total_table_wc = 0
                full_table_section = self._is_table_only_section(title)
                multi_table_section = len(logical_groups) > 1 or "appendix" in title.lower()

                for logical_group in logical_groups:
                    chunk_indices = logical_group["chunk_indices"]
                    group_rids = logical_group["req_ids"]
                    tbl_text, header_lines = self._merge_logical_table_chunks(
                        chunk_indices,
                        table_chunks_by_index,
                    )
                    group_rids = self._order_req_ids_by_table_text(
                        tbl_text,
                        group_rids,
                    )
                    if not full_table_section:
                        tbl_text = self._extract_relevant_table_text(tbl_text, group_rids)

                    if header_lines:
                        logger.info(
                            f"[TABLE-TRACE][C2-WRITE] these headers are extracted: "
                            f"{header_lines[0].strip()}"
                        )
                    else:
                        logger.warning(
                            f"[TABLE-TRACE][C2-WRITE] headers not extracted "
                            f"for table chunk {tci}"
                        )

                    logger.info(
                        f"[TABLE-TRACE][C2-WRITE] Processing logical table {chunk_indices} "
                        f"with {len(group_rids)} reqs for {section_id}"
                    )

                    filled_content, addrs, wc = self._fill_single_table(
                        table_text=tbl_text,
                        req_ids=group_rids,
                        req_map=req_map,
                        section=section,
                        capabilities=capabilities,
                        rfp_instructions=rfp_instructions,
                        rfp_metadata_block=rfp_metadata_block,
                        prev_ctx=prev_ctx,
                        next_ctx=next_ctx,
                        section_feedback=section_feedback,
                        section_id=section_id,
                        title=title,
                        section_type=section_type,
                        batch_size=_TABLE_BATCH_SIZE,
                        original_headers=header_lines,
                    )

                    logger.info(
                        f"[TABLE-TRACE][C2-WRITE] table is merged for chunks {chunk_indices}"
                    )

                    caption = self._table_caption(title, header_lines)
                    show_group_caption = caption and multi_table_section and not (
                        full_table_section and "technical compliance matrix" in title.lower()
                    )
                    if show_group_caption:
                        filled_content = f"### {caption}\n\n{filled_content}".strip()
                    all_table_contents.append(filled_content)
                    all_table_addressed.extend(addrs)
                    total_table_wc += wc

                lower_title = title.lower()
                appendix_like_section = any(
                    kw in lower_title for kw in ("appendix", "declaration", "forms")
                )
                if appendix_like_section:
                    for tci, tbl_chunk in sorted(table_chunks_by_index.items()):
                        if tci in table_groups:
                            continue
                        tbl_text = tbl_chunk.get("text", "")
                        if not self._is_vendor_fill_table(
                            tbl_text,
                            tbl_chunk.get("table_type", "unknown"),
                        ):
                            continue
                        if self._extract_table_row_id(tbl_text):
                            continue

                        header_lines = self._extract_table_header_lines(tbl_text)
                        caption = self._table_caption(title, header_lines)
                        if not caption:
                            continue
                        filled_content = self._normalize_markdown_table_output(
                            self._clean_source_table_text(tbl_text)
                        )
                        filled_content = self._clean_table_section_artifacts(
                            filled_content
                        )
                        filled_content = self._sanitize_markdown_tables(filled_content)
                        addrs = []
                        wc = len(filled_content.split())
                        filled_content = f"### {caption}\n\n{filled_content}".strip()
                        all_table_contents.append(filled_content)
                        all_table_addressed.extend(addrs)
                        total_table_wc += wc

                if ungrouped:
                    if self._is_table_only_section(title):
                        logger.warning(
                            f"[TABLE-TRACE][C2-WRITE] Skipping {len(ungrouped)} "
                            f"ungrouped requirement(s) for table-only section '{title}'"
                        )
                    else:
                        ungrouped_block = "\n".join(
                            f"- {rid} [{req_map.get(rid, {}).get('type', 'MANDATORY')}]: "
                            f"{req_map.get(rid, {}).get('text', '')[:300]}"
                            for rid in ungrouped
                        )
                        prose_prompt = self._build_prompt(
                            section_title=title,
                            section_type=section_type,
                            section_description=self._get_attr(section, "description", ""),
                            content_guidance=self._get_attr(section, "content_guidance", ""),
                            requirements=ungrouped_block,
                            capabilities=capabilities,
                            rfp_instructions=rfp_instructions,
                            rfp_metadata=rfp_metadata_block,
                            prev_section_context=prev_ctx,
                            next_section_context=next_ctx,
                            revision_feedback=section_feedback,
                            table_mode=False,
                            original_table_text="",
                        )
                        raw_resp = llm_large_text_call(prose_prompt, deterministic=True)
                        prose_content, prose_addrs, prose_wc = self._parse_response(
                            raw_resp, f"{section_id}_prose"
                        )
                        all_table_contents.append(prose_content)
                        all_table_addressed.extend(prose_addrs)
                        total_table_wc += prose_wc

                content = "\n\n".join(c for c in all_table_contents if c.strip())
                content = self._normalize_markdown_table_output(content)
                content = self._sanitize_markdown_tables(content)
                content = self._clean_table_section_artifacts(content)
                addressed = list(dict.fromkeys(all_table_addressed))
                word_count = total_table_wc
                logger.info(
                    f"[TABLE-TRACE][C2-WRITE] final table stored: "
                    f"{len(logical_groups)} table(s) for '{section_id}'"
                )

            else:
                # ── NORMAL (BATCHED) PROSE MODE ──
                all_content_parts = []
                chunk_addressed_list = []
                total_word_count = 0
                
                # We chunk the requirements into groups of 15 to prevent prompt overflow
                CHUNK_SIZE = 15
                req_chunks = [req_ids[i:i + CHUNK_SIZE] for i in range(0, max(1, len(req_ids)), CHUNK_SIZE)]
                
                logger.info(
                    f"[C2] Writing section {section_id}: {title} | "
                    f"type={section_type} | {len(req_ids)} requirements "
                    f"({len(req_chunks)} chunks)"
                )
                
                for i, chunk in enumerate(req_chunks):
                    # Build a specific requirements block for just this chunk
                    chunk_reqs_block = "\n".join(
                        f"- {rid} [{req_map.get(rid, {}).get('type', 'MANDATORY')}]: "
                        f"{req_map.get(rid, {}).get('text', '')[:300]}"
                        for rid in chunk
                    ) if chunk else "No specific RFP requirements mapped; write general response based on title and description."
                    
                    prompt = self._build_prompt(
                        section_title=title,
                        section_type=section_type,
                        section_description=self._get_attr(section, "description", ""),
                        content_guidance=self._get_attr(section, "content_guidance", ""),
                        requirements=chunk_reqs_block,
                        capabilities=capabilities,
                        rfp_instructions=rfp_instructions,
                        rfp_metadata=rfp_metadata_block,
                        prev_section_context=prev_ctx,
                        next_section_context=next_ctx,
                        revision_feedback=section_feedback,
                        table_mode=table_mode,
                        original_table_text=original_table_text,
                    )
                    
                    raw_response = llm_large_text_call(prompt, deterministic=True)
                    logger.debug(f"[C2] LLM response for {section_id} chunk {i+1}/{len(req_chunks)} ({len(raw_response)} chars)")
                    
                    part_content, part_addressed, part_wc = self._parse_response(
                        raw_response, f"{section_id}_part{i}"
                    )
                    all_content_parts.append(part_content)
                    chunk_addressed_list.extend(part_addressed)
                    total_word_count += part_wc
                
                content = "\n\n".join(c for c in all_content_parts if c.strip())
                content = self._sanitize_markdown_tables(content)
                if not self._is_table_only_section(title):
                    content = self._strip_markdown_tables(content)
                addressed = list(dict.fromkeys(chunk_addressed_list))
                word_count = total_word_count

            content = self._finalize_section_content(
                content=content,
                section_title=title,
                section_description=self._get_attr(section, "description", ""),
                content_guidance=self._get_attr(section, "content_guidance", ""),
            )

            # ── 7f2. Log filled tables ───────────────────
            if table_mode and original_table_text and content:
                try:
                    filled_dir = Path(r"d:\RFP-Responder-1\storage\filled table")
                    filled_dir.mkdir(parents=True, exist_ok=True)
                    filled_path = filled_dir / f"{section_id}.txt"
                    filled_path.write_text(content, encoding="utf-8")
                    logger.info(
                        f"[TABLE-TRACE][C2-WRITE] final table stored: {filled_path}"
                    )
                except Exception as exc:
                    logger.warning(f"[TABLE-TRACE][C2-WRITE] Failed to save filled table: {exc}")

            # ── 7g. Detect placeholders ─────────────────
            self._detect_placeholders(content, section_id)

            section_responses.append(
                SectionResponse(
                    section_id=section_id,
                    title=title,
                    content=content,
                    requirements_addressed=addressed,
                    word_count=word_count,
                )
            )

            # Track which requirements were addressed in which sections
            for rid in addressed:
                all_addressed.setdefault(rid, []).append(section_id)

            logger.info(
                f"[C2] Section {section_id}: {title} | "
                f"{word_count} words | {len(addressed)} reqs addressed"
            )

            # Word count validation
            min_words = {
                "knowledge_driven": 400,
                "requirement_driven": 100,
                "boilerplate": 50,
            }
            threshold = min_words.get(section_type, 100)
            if word_count < threshold and word_count > 0:
                logger.warning(
                    f"[C2] ⚠ LOW WORD COUNT: Section {section_id} ({title}) "
                    f"has only {word_count} words (minimum for "
                    f"{section_type}: {threshold})"
                )

        # ── 10. Build coverage matrix ───────────────────
        section_content_by_id = {
            sr.section_id: sr.content
            for sr in section_responses
        }
        coverage_matrix = self._build_coverage_matrix(
            req_map, all_addressed, c1_assignments, section_content_by_id,
        )

        # ── 9. Update state ─────────────────────────────
        state.writing_result = WritingResult(
            section_responses=section_responses,
            coverage_matrix=coverage_matrix,
        )
        state.status = PipelineStatus.ASSEMBLING_NARRATIVE

        # Log summary
        total_words = sum(sr.word_count for sr in section_responses)
        addressed_count = sum(
            1 for c in coverage_matrix if c.coverage_quality != "missing"
        )
        logger.info(
            f"[C2] Writing complete — {len(section_responses)} sections, "
            f"{total_words} total words, "
            f"{addressed_count}/{len(coverage_matrix)} requirements covered"
        )

        return state

    # ── Helpers ──────────────────────────────────────────

    @staticmethod
    def _get_attr(obj: Any, attr: str, default: Any) -> Any:
        """Get attribute from either a Pydantic model or a dict."""
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    @staticmethod
    def _extract_pipe_table_lines(table_text: str) -> list[str]:
        """Return normalized pipe-delimited lines from a table chunk."""
        return [
            line.strip()
            for line in table_text.splitlines()
            if line.count("|") >= 2 and line.strip()
        ]

    @classmethod
    def _extract_table_header_lines(cls, table_text: str) -> list[str]:
        """Extract only the actual header row(s), not all source rows."""
        pipe_lines = cls._extract_pipe_table_lines(table_text)
        if not pipe_lines:
            return []

        header_lines = [pipe_lines[0]]
        if len(pipe_lines) > 1:
            normalized = pipe_lines[1].replace(" ", "")
            if normalized and set(normalized) <= {"|", "-", ":"}:
                header_lines.append(pipe_lines[1])
        return header_lines

    @staticmethod
    def _extract_table_row_id(line: str) -> str:
        """Extract the first requirement or pricing ID from a table row."""
        match = re.search(
            r'\b(?:TR-\d{3}|CM-\d{2}|KPI-\d{2}|REQ-\d{4}|\d+\.\d{2})\b',
            line,
            re.IGNORECASE,
        )
        return match.group(0).upper() if match else ""

    @classmethod
    def _extract_relevant_table_text(
        cls,
        table_text: str,
        req_ids: list[str],
    ) -> str:
        """Keep only header lines and the rows relevant to this table group."""
        target_ids = {str(rid).strip().upper() for rid in req_ids if str(rid).strip()}
        if not target_ids:
            return table_text

        pipe_lines = cls._extract_pipe_table_lines(table_text)
        header_lines = cls._extract_table_header_lines(table_text)
        if not pipe_lines:
            return table_text

        filtered_lines = list(header_lines)
        seen_rows: set[str] = set()
        for line in pipe_lines[len(header_lines):]:
            row_id = cls._extract_table_row_id(line)
            if row_id and row_id in target_ids and row_id not in seen_rows:
                filtered_lines.append(line)
                seen_rows.add(row_id)

        if len(filtered_lines) > len(header_lines):
            return "\n".join(filtered_lines)
        return table_text

    @staticmethod
    def _is_table_only_section(title: str) -> bool:
        return title.strip().lower() in _TABLE_ONLY_SECTION_TITLES

    @staticmethod
    def _count_table_columns(line: str) -> int:
        stripped = line.strip()
        pipes = stripped.count("|")
        if stripped.startswith("|") and stripped.endswith("|"):
            return max(1, pipes - 1)
        if not stripped.startswith("|") and not stripped.endswith("|"):
            return max(1, pipes + 1)
        return max(1, pipes)

    @staticmethod
    def _split_table_cells(line: str) -> list[str]:
        stripped = line.strip().strip("|")
        if not stripped:
            return []
        return [cell.strip() for cell in stripped.split("|")]

    @classmethod
    def _clean_source_table_text(cls, table_text: str) -> str:
        """Remove source-chunk metadata before a table is merged or re-rendered."""
        if not table_text.strip():
            return table_text

        cleaned = _MERMAID_BLOCK_RE.sub("", table_text)
        lines: list[str] = []
        in_fence = False

        for raw_line in cleaned.splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            if stripped.startswith("[Section:") or stripped.startswith("RFP Ref:"):
                continue
            if stripped in {"]", "["}:
                continue
            lines.append(raw_line)

        return cls._collapse_blank_lines("\n".join(lines))

    @classmethod
    def _clean_table_section_artifacts(cls, content: str) -> str:
        """Keep table-only sections free of leaked metadata and misplaced Mermaid."""
        if not content.strip():
            return content

        cleaned = _MERMAID_BLOCK_RE.sub("", content)
        lines: list[str] = []
        in_fence = False

        for raw_line in cleaned.splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            if stripped.startswith("[Section:") or stripped.startswith("RFP Ref:"):
                continue
            if stripped in {"]", "["}:
                continue
            lines.append(raw_line)

        return cls._collapse_blank_lines("\n".join(lines))

    @classmethod
    def _extract_table_data_lines(cls, table_text: str) -> list[str]:
        pipe_lines = cls._extract_pipe_table_lines(table_text)
        header_lines = cls._extract_table_header_lines(table_text)
        return pipe_lines[len(header_lines):]

    @staticmethod
    def _normalize_table_header_label(label: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (label or "").lower()).strip()

    @classmethod
    def _table_header_role(
        cls,
        header: str,
        family: str,
        index: int,
        total: int,
    ) -> str:
        normalized = cls._normalize_table_header_label(header)
        if not normalized:
            return f"col_{index}"

        if index == 0 or normalized.endswith(" id") or normalized in {
            "ref",
            "ref.",
            "line #",
            "line number",
        }:
            return "id"

        if family == "technical":
            if normalized in {"requirement", "category", "module"} or "category" in normalized or "module" in normalized:
                return "category"
            if "description" in normalized:
                return "description"
            if normalized in {"priority", "compliance", "compliance status", "status"}:
                return "status"
            if "c pc nc" in normalized or "yes no" in normalized:
                return "choice"
            if "vendor remarks" in normalized or "vendor comments" in normalized or normalized in {"remarks", "comments"}:
                return "detail"
            if "vendor response" in normalized:
                if total >= 6 and index == total - 2:
                    return "choice"
                return "detail"
            if "vendor to fill" in normalized:
                return "detail"

        if family == "pricing":
            if "description" in normalized:
                return "description"
            if "category" in normalized or "service type" in normalized:
                return "category"
            if "unit" in normalized or "pricing model" in normalized:
                return "unit"
            if any(token in normalized for token in ("nrc", "mrc", "arc", "cost", "price", "vendor to fill")):
                return "price"

        if family == "compliance":
            if "requirement" in normalized:
                return "requirement"
            if "status" in normalized or "compliance" in normalized:
                return "status"
            if "reference" in normalized or "evidence" in normalized:
                return "reference"
            if "vendor" in normalized or "comments" in normalized or "response" in normalized:
                return "response"

        return normalized

    @classmethod
    def _table_header_signature(cls, table_text: str) -> tuple[str, ...]:
        header_lines = cls._extract_table_header_lines(table_text)
        if not header_lines:
            return ()

        header_cells = cls._split_table_cells(header_lines[-1])
        if not header_cells:
            return ()

        family = cls._table_family(table_text)
        total = len(header_cells)
        return tuple(
            cls._table_header_role(cell, family, index, total)
            for index, cell in enumerate(header_cells)
        )

    @classmethod
    def _table_family(cls, table_text: str) -> str:
        for line in cls._extract_table_data_lines(table_text):
            row_id = cls._extract_table_row_id(line)
            if not row_id:
                continue
            if _TECHNICAL_REQ_ID_RE.match(row_id):
                return "technical"
            if _PRICING_REQ_ID_RE.match(row_id):
                return "pricing"
            if _COMPLIANCE_REQ_ID_RE.match(row_id):
                return "compliance"
            if _KPI_REQ_ID_RE.match(row_id):
                return "kpi"
            return "other"
        return ""

    @classmethod
    def _should_merge_table_chunks(cls, left_chunk: dict[str, Any], right_chunk: dict[str, Any]) -> bool:
        if not left_chunk or not right_chunk:
            return False
        if right_chunk.get("chunk_index", -1) != left_chunk.get("chunk_index", -1) + 1:
            return False
        left_text = cls._clean_source_table_text(left_chunk.get("text", ""))
        right_text = cls._clean_source_table_text(right_chunk.get("text", ""))
        if not (
            cls._is_vendor_fill_table(left_text, left_chunk.get("table_type", "unknown"))
            and cls._is_vendor_fill_table(right_text, right_chunk.get("table_type", "unknown"))
        ):
            return False
        left_family = cls._table_family(left_text)
        right_family = cls._table_family(right_text)
        if not left_family or left_family != right_family:
            return False
        left_hint = (left_chunk.get("section_hint") or "").strip().lower()
        right_hint = (right_chunk.get("section_hint") or "").strip().lower()
        if left_hint and right_hint and left_hint != right_hint:
            return False
        left_signature = cls._table_header_signature(left_text)
        right_signature = cls._table_header_signature(right_text)
        if left_signature and right_signature:
            return left_signature == right_signature
        left_headers = cls._extract_table_header_lines(left_text)
        right_headers = cls._extract_table_header_lines(right_text)
        if left_headers and right_headers:
            return cls._count_table_columns(left_headers[-1]) == cls._count_table_columns(right_headers[-1])
        return True

    @classmethod
    def _build_logical_table_groups(
        cls,
        table_groups: dict[int, list[str]],
        table_chunks_by_index: dict[int, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not table_groups:
            return []

        logical_groups: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        for tci in sorted(table_groups):
            chunk = table_chunks_by_index.get(tci, {})
            req_ids = list(dict.fromkeys(table_groups.get(tci, [])))
            if current is None:
                current = {"chunk_indices": [tci], "req_ids": req_ids}
                continue

            prev_chunk = table_chunks_by_index.get(current["chunk_indices"][-1], {})
            if cls._should_merge_table_chunks(prev_chunk, chunk):
                current["chunk_indices"].append(tci)
                for rid in req_ids:
                    if rid not in current["req_ids"]:
                        current["req_ids"].append(rid)
            else:
                logical_groups.append(current)
                current = {"chunk_indices": [tci], "req_ids": req_ids}

        if current is not None:
            logical_groups.append(current)
        return logical_groups

    @classmethod
    def _coerce_table_line_to_columns(
        cls,
        line: str,
        expected_col_count: int,
    ) -> str:
        stripped = line.strip().strip("|")
        cells = [cell.strip() for cell in stripped.split("|")]
        if not expected_col_count or not cells:
            return line.strip()

        if len(cells) == expected_col_count - 1 and cells:
            split_tail = re.split(r"(?<=\])\s+(?=\[)", cells[-1], maxsplit=1)
            if len(split_tail) == 2:
                cells = cells[:-1] + split_tail

        if len(cells) > expected_col_count:
            cells = cells[:expected_col_count - 1] + [" | ".join(cells[expected_col_count - 1:])]
        elif len(cells) < expected_col_count:
            cells.extend([""] * (expected_col_count - len(cells)))

        return f"| {' | '.join(cells)} |"

    @classmethod
    def _merge_logical_table_chunks(
        cls,
        chunk_indices: list[int],
        table_chunks_by_index: dict[int, dict[str, Any]],
    ) -> tuple[str, list[str]]:
        header_candidates: list[list[str]] = []
        row_lines: list[str] = []
        family = ""

        for tci in chunk_indices:
            tbl_chunk = table_chunks_by_index.get(tci, {})
            tbl_text = cls._clean_source_table_text(tbl_chunk.get("text", ""))
            if not family:
                family = cls._table_family(tbl_text)
            header_lines = cls._extract_table_header_lines(tbl_text)
            if header_lines:
                header_candidates.append(header_lines)
            row_lines.extend(cls._extract_table_data_lines(tbl_text))

        if not header_candidates:
            merged_text = "\n".join(
                table_chunks_by_index.get(tci, {}).get("text", "").strip()
                for tci in chunk_indices
                if table_chunks_by_index.get(tci, {}).get("text", "").strip()
            )
            return merged_text, []

        if family == "compliance":
            chosen_headers = header_candidates[0]
        elif family == "technical":
            chosen_headers = next(
                (
                    headers
                    for headers in header_candidates
                    if cls._count_table_columns(headers[-1]) >= 6
                ),
                header_candidates[0],
            )
        else:
            chosen_headers = max(
                header_candidates,
                key=lambda headers: (
                    cls._count_table_columns(headers[-1]),
                    -chunk_indices[header_candidates.index(headers)],
                ),
            )
        expected_col_count = cls._count_table_columns(chosen_headers[-1])
        merged_lines: list[str] = list(chosen_headers)
        seen_keys: set[str] = set()

        for line in row_lines:
            cells = cls._split_table_cells(line)
            if family == "technical" and expected_col_count >= 6:
                if len(cells) == 4:
                    row_id, label, compliance_state, vendor_response = cells
                    priority = "Mandatory" if _TECHNICAL_REQ_ID_RE.match(row_id) else ""
                    cells = [
                        row_id,
                        label,
                        label or row_id,
                        priority,
                        compliance_state,
                        vendor_response,
                    ]
                elif len(cells) == 5:
                    row_id, label, description, compliance_state, vendor_response = cells
                    priority = "Mandatory" if _TECHNICAL_REQ_ID_RE.match(row_id) else ""
                    cells = [
                        row_id,
                        label,
                        description or label,
                        priority,
                        compliance_state,
                        vendor_response,
                    ]
                elif len(cells) >= 6 and not cells[2].strip() and cells[1].strip():
                    cells[2] = cells[1].strip()

            normalized_source = f"| {' | '.join(cells)} |" if cells else line.strip()
            normalized = cls._coerce_table_line_to_columns(
                normalized_source,
                expected_col_count,
            )
            row_id = cls._extract_table_row_id(normalized)
            key = row_id or normalized.strip()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            merged_lines.append(normalized)

        return "\n".join(merged_lines), chosen_headers

    @classmethod
    def _order_req_ids_by_table_text(
        cls,
        table_text: str,
        req_ids: list[str],
    ) -> list[str]:
        wanted = {str(rid).strip().upper() for rid in req_ids if str(rid).strip()}
        if not wanted:
            return []

        ordered: list[str] = []
        for line in cls._extract_table_data_lines(table_text):
            row_id = cls._extract_table_row_id(line)
            if row_id and row_id in wanted and row_id not in ordered:
                ordered.append(row_id)

        for rid in req_ids:
            normalized = str(rid).strip().upper()
            if normalized and normalized not in ordered:
                ordered.append(normalized)
        return ordered

    @classmethod
    def _extract_generated_table_rows(
        cls,
        batch_content: str,
        table_header_line: str,
        expected_col_count: int,
    ) -> list[str]:
        lines = batch_content.strip().split("\n")
        table_lines = [line for line in lines if "|" in line]
        if not table_lines:
            return []

        start_idx = 0
        if len(table_lines) >= 2 and "---" in table_lines[1]:
            start_idx = 2
        elif table_lines and "---" in table_lines[0]:
            start_idx = 1

        data_lines: list[str] = []
        for line in table_lines[start_idx:]:
            normalized_line = line.strip()
            if not normalized_line or "---" in normalized_line:
                continue
            if table_header_line and normalized_line == table_header_line:
                continue
            if expected_col_count:
                normalized_line = cls._coerce_table_line_to_columns(
                    normalized_line,
                    expected_col_count,
                ).strip()
                if cls._count_table_columns(normalized_line) != expected_col_count:
                    continue
            data_lines.append(normalized_line)
        return data_lines

    @classmethod
    def _order_generated_rows(
        cls,
        data_lines: list[str],
        batch_rids: list[str],
    ) -> list[str]:
        if not batch_rids:
            return data_lines

        by_id: dict[str, str] = {}
        extras: list[str] = []
        for line in data_lines:
            row_id = cls._extract_table_row_id(line)
            if row_id and row_id not in by_id:
                by_id[row_id] = line
            elif not row_id:
                extras.append(line)

        ordered = [by_id[rid] for rid in batch_rids if rid in by_id]
        for line in data_lines:
            row_id = cls._extract_table_row_id(line)
            if row_id and row_id not in batch_rids and line not in ordered:
                ordered.append(line)
        if not batch_rids:
            ordered.extend(line for line in extras if line not in ordered)
        return ordered

    @staticmethod
    def _normalize_markdown_table_output(content: str) -> str:
        """Normalize generated table rows so markdown renders consistently."""
        normalized_lines: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if "|" in stripped:
                if not stripped.startswith("|"):
                    stripped = f"| {stripped}"
                if not stripped.endswith("|"):
                    stripped = f"{stripped} |"
                normalized_lines.append(stripped)
            else:
                normalized_lines.append(line)
        return "\n".join(normalized_lines).strip()

    @classmethod
    def _sanitize_markdown_tables(cls, content: str) -> str:
        """Drop duplicate/orphan header rows so markdown tables render cleanly."""
        if not content.strip():
            return content

        lines = content.splitlines()
        rewritten: list[str] = []
        idx = 0

        while idx < len(lines):
            if cls._count_table_columns(lines[idx]) >= 2:
                block: list[str] = []
                while idx < len(lines) and cls._count_table_columns(lines[idx]) >= 2:
                    block.append(lines[idx].rstrip())
                    idx += 1
                rewritten.extend(cls._sanitize_table_block(block))
                continue

            rewritten.append(lines[idx])
            idx += 1

        return "\n".join(rewritten).strip()

    @classmethod
    def _strip_markdown_tables(cls, content: str) -> str:
        """Remove markdown table blocks from prose-only sections."""
        if not content.strip():
            return content

        lines = content.splitlines()
        rewritten: list[str] = []
        idx = 0

        while idx < len(lines):
            if cls._count_table_columns(lines[idx]) >= 2:
                while idx < len(lines) and cls._count_table_columns(lines[idx]) >= 2:
                    idx += 1
                if rewritten and rewritten[-1].strip():
                    rewritten.append("")
                continue

            rewritten.append(lines[idx])
            idx += 1

        return "\n".join(rewritten).strip()

    @classmethod
    def _sanitize_table_block(cls, block: list[str]) -> list[str]:
        if not block:
            return []

        header = block[0].strip()
        expected_cols = cls._count_table_columns(header)
        separator = "|" + "|".join(["---"] * expected_cols) + "|"
        sanitized = [header, separator]
        seen_rows: set[str] = set()

        for raw in block[1:]:
            line = raw.strip()
            if not line:
                continue
            if cls._is_separator_line(line):
                continue
            if line == header:
                continue
            normalized = cls._coerce_table_line_to_columns(line, expected_cols).strip()
            if cls._count_table_columns(normalized) != expected_cols:
                continue
            row_id = cls._extract_table_row_id(normalized)
            key = row_id or normalized
            if key in seen_rows:
                continue
            seen_rows.add(key)
            sanitized.append(normalized)

        if len(sanitized) <= 2:
            return []
        return sanitized + [""]

    @staticmethod
    def _is_separator_line(line: str) -> bool:
        normalized = line.strip().replace(" ", "")
        return bool(normalized) and set(normalized) <= {"|", "-", ":"}

    @classmethod
    def _table_caption(cls, section_title: str, header_lines: list[str] | None) -> str:
        title = section_title.strip().lower()
        header = (header_lines or [""])[0].lower()
        if "pricing schedule matrix" in title:
            return "Pricing Schedule Matrix"
        if "appendix forms" in title and "client name" in header:
            return "Client Reference Form"
        if "appendix forms" in title and ("cm-number" in header or "ref." in header):
            return "Compliance Matrix"
        if "technical" in title and ("req. id" in header or "tr-id" in header):
            return "Technical Compliance Matrix"
        return ""

    @classmethod
    def _is_vendor_fill_table(
        cls,
        table_text: str,
        table_type: str = "unknown",
    ) -> bool:
        """Detect whether a table is genuinely intended for vendor input."""
        pipe_lines = cls._extract_pipe_table_lines(table_text)
        header_line = pipe_lines[0] if pipe_lines else ""
        header_has_fill_signal = bool(_TABLE_FILL_HEADER_RE.search(header_line))
        placeholder_hits = len(_TABLE_FILL_PLACEHOLDER_RE.findall(table_text))

        if header_has_fill_signal:
            return True
        if placeholder_hits >= 2:
            return True
        if table_type == "fill_in_table" and placeholder_hits >= 1:
            return True
        return False

    @classmethod
    def _table_group_matches_section(cls, group_rids: list[str], section: Any) -> bool:
        """Keep clearly misplaced table groups out of unrelated sections."""
        if not group_rids:
            return False

        section_text = " ".join(
            [
                cls._get_attr(section, "title", ""),
                cls._get_attr(section, "description", ""),
                cls._get_attr(section, "content_guidance", ""),
            ]
        ).lower()
        rid_values = [str(rid).strip().upper() for rid in group_rids if str(rid).strip()]

        is_pricing_group = rid_values and all(_PRICING_REQ_ID_RE.match(rid) for rid in rid_values)
        is_compliance_group = rid_values and all(_COMPLIANCE_REQ_ID_RE.match(rid) for rid in rid_values)
        is_technical_group = rid_values and all(
            _TECHNICAL_REQ_ID_RE.match(rid) or _KPI_REQ_ID_RE.match(rid)
            for rid in rid_values
        )

        pricing_section = any(
            kw in section_text for kw in ("pricing", "commercial", "cost", "rate card", "opex", "financial")
        )
        compliance_section = any(
            kw in section_text for kw in ("compliance", "qualification", "certification", "declaration", "submission form")
        )
        matrix_section = any(
            kw in section_text for kw in ("matrix", "appendix", "checklist", "questionnaire")
        )
        technical_section = any(
            kw in section_text for kw in ("technical", "architecture", "solution", "interconnect", "soc", "support", "operations")
        )

        if is_pricing_group:
            return pricing_section
        if is_compliance_group:
            return compliance_section or matrix_section
        if is_technical_group:
            return technical_section or matrix_section
        return True

    def _fetch_section_capabilities(
        self,
        mcp: MCPService,
        section_title: str,
        req_ids: list[str],
        req_map: dict[str, dict[str, Any]],
        mapped_capabilities: list[str],
    ) -> str:
        """Fetch company capabilities relevant to this section from MCP Knowledge Store."""
        queries = [f"{section_title} capabilities solutions"]

        # Add queries based on requirement keywords
        for rid in req_ids[:5]:  # cap at 5 to avoid too many queries
            req = req_map.get(rid)
            if req:
                keywords = req.get("keywords", [])
                if keywords:
                    queries.append(f"{' '.join(keywords[:3])} capabilities")

        seen_texts: set[str] = set()
        capability_texts: list[str] = []

        # Add pre-mapped capabilities from C1
        for cap in mapped_capabilities:
            if cap and cap not in seen_texts:
                seen_texts.add(cap)
                capability_texts.append(f"- {cap}")

        unique_queries = list(dict.fromkeys(queries))
        try:
            result_sets = mcp.query_knowledge_batch(unique_queries, top_k=3)
            for query, results in zip(unique_queries, result_sets):
                for r in results:
                    text = r.get("text", "").strip()
                    if text and text not in seen_texts:
                        seen_texts.add(text)
                        capability_texts.append(text)
        except Exception as exc:
            logger.warning(f"[C2] Batched knowledge query failed: {exc}")
            for query in unique_queries:
                try:
                    results = mcp.query_knowledge(query, top_k=3)
                    for r in results:
                        text = r.get("text", "").strip()
                        if text and text not in seen_texts:
                            seen_texts.add(text)
                            capability_texts.append(text)
                except Exception as inner_exc:
                    logger.warning(f"[C2] Knowledge query failed for '{query}': {inner_exc}")

        if not capability_texts:
            return "No specific capabilities available for this section."

        return "\n\n".join(capability_texts)

    def _fill_single_table(
        self,
        table_text: str,
        req_ids: list[str],
        req_map: dict[str, dict[str, Any]],
        section: Any,
        capabilities: str,
        rfp_instructions: str,
        rfp_metadata_block: str,
        prev_ctx: str,
        next_ctx: str,
        section_feedback: str,
        section_id: str,
        title: str,
        section_type: str,
        batch_size: int = 12,
        original_headers: list[str] | None = None,
    ) -> tuple[str, list[str], int]:
        """
        Processes a single table by optionally batching its requirements,
        calling the LLM, and merging the resulting rows under a single header.
        """
        all_content_parts: list[str] = []
        all_batch_addressed: list[str] = []
        total_word_count = 0
        table_header: str | None = None
        table_header_line = ""
        expected_col_count = 0
        seen_row_ids: set[str] = set()
        ordered_req_ids = self._order_req_ids_by_table_text(table_text, req_ids)

        if original_headers:
            header_block = "\n".join(original_headers)
            table_header_line = original_headers[0].strip()
            
            # Count the columns in the actual column row (last header line)
            last_line = original_headers[-1]
            stripped = last_line.strip()
            pipes = stripped.count("|")
            
            if stripped.startswith("|") and stripped.endswith("|"):
                col_count = pipes - 1
            elif not stripped.startswith("|") and not stripped.endswith("|"):
                col_count = pipes + 1
            else:
                col_count = pipes

            if col_count < 1:
                col_count = 1
            expected_col_count = col_count
                
            # Create a markdown separator
            separator = "|" + "|".join(["---"] * col_count) + "|"
            
            # Add separator if it's not already there
            if "---" not in last_line:
                table_header = header_block + "\n" + separator
            else:
                table_header = header_block
                
            all_content_parts.append(table_header)

        batch_ranges = range(0, max(1, len(ordered_req_ids)), batch_size)
        for batch_idx in batch_ranges:
            batch_rids = ordered_req_ids[batch_idx : batch_idx + batch_size]
            batch_num = batch_idx // batch_size + 1

            batch_requirements_block = self._build_requirements_block(batch_rids, req_map)
            batch_table_text = (
                self._extract_relevant_table_text(table_text, batch_rids)
                if batch_rids
                else table_text
            )

            prompt = self._build_prompt(
                section_title=title,
                section_type=section_type,
                section_description=self._get_attr(section, "description", ""),
                content_guidance=self._get_attr(section, "content_guidance", ""),
                requirements=batch_requirements_block,
                capabilities=capabilities,
                rfp_instructions=rfp_instructions,
                rfp_metadata=rfp_metadata_block,
                prev_section_context=prev_ctx,
                next_section_context=next_ctx,
                revision_feedback=section_feedback,
                table_mode=True,
                original_table_text=batch_table_text,
            )

            logger.info(
                f"[C2] Writing table batch {batch_num} for {section_id}: "
                f"{len(batch_rids)} reqs in this batch"
            )
            raw_response = llm_large_text_call(prompt, deterministic=True)
            batch_content, batch_addressed, batch_wc = self._parse_response(
                raw_response, f"{section_id}_table_batch{batch_num}"
            )

            # --- API RATE LIMIT PROTECTION ---
            # To respect low TPM limits (e.g. Groq 6000 limit) when looping.
            # Using 65s wait guarantees the 1-minute tracking window fully resets
            # for these massive table prompts.
            if batch_num * batch_size < len(ordered_req_ids):
                logger.info(
                    f"[C2] Batch {batch_num} complete. Pausing 65s to fully reset TPM limits..."
                )
                time.sleep(65)

            all_batch_addressed.extend(batch_addressed)
            total_word_count += batch_wc

            # Merge table rows, keeping only the first batch's header
            if batch_content.strip():
                table_lines = [line for line in batch_content.strip().split("\n") if "|" in line]
                if table_lines:
                    if table_header is None:
                        inferred_header = table_lines[0].strip()
                        inferred_cols = self._count_table_columns(inferred_header)
                        if inferred_cols >= 2:
                            table_header_line = inferred_header
                            expected_col_count = inferred_cols
                            separator = "|" + "|".join(["---"] * inferred_cols) + "|"
                            table_header = f"{inferred_header}\n{separator}"
                            all_content_parts.append(table_header)

                            data_lines = self._extract_generated_table_rows(
                                batch_content,
                                table_header_line,
                                expected_col_count,
                            )
                            data_lines = self._order_generated_rows(data_lines, batch_rids)
                            filtered_lines: list[str] = []
                            for line in data_lines:
                                row_id = self._extract_table_row_id(line)
                                if row_id:
                                    if row_id in seen_row_ids:
                                        continue
                                    seen_row_ids.add(row_id)
                                filtered_lines.append(line)

                            if filtered_lines:
                                all_content_parts.append("\n".join(filtered_lines))
                        else:
                            all_content_parts.append(batch_content.strip())
                    else:
                        data_lines = self._extract_generated_table_rows(
                            batch_content,
                            table_header_line,
                            expected_col_count,
                        )
                        data_lines = self._order_generated_rows(data_lines, batch_rids)
                        filtered_lines: list[str] = []
                        for line in data_lines:
                            row_id = self._extract_table_row_id(line)
                            if row_id:
                                if row_id in seen_row_ids:
                                    continue
                                seen_row_ids.add(row_id)
                            filtered_lines.append(line)

                        data_lines = filtered_lines
                        if data_lines:
                            all_content_parts.append("\n".join(data_lines))
                else:
                    all_content_parts.append(batch_content.strip())

        content = self._normalize_markdown_table_output(
            "\n".join(all_content_parts)
        )
        content = self._sanitize_markdown_tables(content)
        addressed = list(dict.fromkeys(all_batch_addressed))
        return content, addressed, total_word_count

    @classmethod
    def _build_requirements_block(
        cls,
        req_ids: list[str],
        req_map: dict[str, dict[str, Any]],
    ) -> str:
        if not req_ids:
            return "No specific requirements assigned."

        return "\n".join(
            cls._format_requirement_for_prompt(rid, req_map.get(rid))
            for rid in req_ids
        )

    @classmethod
    def _format_requirement_for_prompt(
        cls,
        requirement_id: str,
        requirement: dict[str, Any] | None,
    ) -> str:
        if not requirement:
            return f"- Requirement: [details unavailable] (Internal ID: {requirement_id}; do not cite)"

        req_type = requirement.get("type", "MANDATORY")
        req_text = (requirement.get("text", "") or "").strip()
        req_text = re.sub(r"\s+", " ", req_text)[:300] or "[requirement details unavailable]"
        client_ref = cls._extract_client_reference(requirement_id, req_text)

        if _INTERNAL_REQ_ID_RE.match(requirement_id):
            if client_ref:
                return (
                    f"- Requirement [{req_type}] — {req_text} "
                    f"(RFP row: {client_ref}; internal tracking ID {requirement_id} — do not cite the internal ID)"
                )
            return (
                f"- Requirement [{req_type}] — {req_text} "
                f"(Internal tracking ID {requirement_id} — do not cite in client-facing prose)"
            )

        return f"- {requirement_id} [{req_type}] — {req_text}"

    @staticmethod
    def _extract_client_reference(requirement_id: str, requirement_text: str) -> str:
        if requirement_id and not _INTERNAL_REQ_ID_RE.match(requirement_id):
            return requirement_id

        match = _CLIENT_ROW_ID_RE.search(requirement_text or "")
        return match.group(0) if match else ""

    @classmethod
    def _finalize_section_content(
        cls,
        content: str,
        section_title: str,
        section_description: str,
        content_guidance: str,
    ) -> str:
        """Apply deterministic cleanup after the LLM returns section content.

        Mermaid is intentionally stripped here. Section visuals are generated in
        a later document-level pass where we can enforce section-specific types,
        document-wide de-duplication, and consistent styling.
        """
        if not content.strip():
            return content.strip()

        content = cls._strip_mermaid_blocks(content)
        content = cls._ensure_markdown_block_spacing(content)
        return content.strip()

    @classmethod
    def _ensure_markdown_block_spacing(cls, content: str) -> str:
        """Keep headings outside table and fenced-code blocks."""
        if not content.strip():
            return content

        lines = content.splitlines()
        rewritten: list[str] = []
        for line in lines:
            stripped = line.strip()
            is_heading = bool(re.match(r"^#{1,6}\s+", stripped))
            prev_line = rewritten[-1].strip() if rewritten else ""
            prev_is_table = bool(rewritten and cls._count_table_columns(rewritten[-1]) >= 2)
            prev_is_fence = prev_line == "```"

            if is_heading and rewritten and rewritten[-1] != "" and (prev_is_table or prev_is_fence):
                rewritten.append("")

            rewritten.append(line)

        return "\n".join(rewritten).strip()

    @staticmethod
    def _collapse_blank_lines(content: str) -> str:
        return re.sub(r"\n{3,}", "\n\n", content).strip()

    @classmethod
    def _strip_mermaid_blocks(cls, content: str) -> str:
        return cls._collapse_blank_lines(_MERMAID_BLOCK_RE.sub("", content))

    def _build_prompt(
        self,
        section_title: str,
        section_type: str,
        section_description: str,
        content_guidance: str,
        requirements: str,
        capabilities: str,
        rfp_instructions: str,
        rfp_metadata: str = "",
        prev_section_context: str = "",
        next_section_context: str = "",
        revision_feedback: str = "",
        table_mode: bool = False,
        original_table_text: str = "",
    ) -> str:
        """Load the prompt template and inject context with token-aware truncation."""
        template = _PROMPT_PATH.read_text(encoding="utf-8")

        # ── Token-aware budget ────────────────────────────
        # This agent calls llm_large_text_call → Llama 4 Scout
        # with 131K context window and 30K TPM per key.
        # Budget: ~25K tokens input (~100K chars) with 8K reserved for output.
        chars_per_token = 4
        input_budget_tokens = 25_000
        available_chars = max(
            input_budget_tokens * chars_per_token,
            4000,
        )

        # Budget: requirements 40%, capabilities 35%, instructions 15%, guidance 10%
        budget_reqs = int(available_chars * 0.40)
        budget_caps = int(available_chars * 0.35)
        budget_inst = int(available_chars * 0.15)
        budget_guide = int(available_chars * 0.10)

        # Build revision feedback block
        feedback_block = (
            revision_feedback[:2000]
            if revision_feedback
            else "No revision feedback — this is the initial writing pass."
        )

        # ── Table mode injection ──────────────────────
        table_instruction = ""
        if table_mode:
            if original_table_text:
                # Use the exact columns from the original RFP table
                table_instruction = (
                    "\n\n## TABLE RESPONSE MODE\n"
                    "This section requires a TABLE-FORMAT response, NOT prose.\n"
                    "Below is the ORIGINAL TABLE from the RFP that you must fill in.\n"
                    "You MUST preserve the EXACT same column structure and headers.\n"
                    "Fill in ONLY the columns that are meant for vendor responses "
                    "(e.g. Compliance, Vendor Response, Remarks, Status, Yes/No columns).\n"
                    "Replace placeholder cells such as [Vendor to fill], [Name OEM], "
                    "[Name SIEM], [Name of PM], and [C / PC / NC] with concrete values "
                    "in the returned table.\n"
                    "Keep each completed table cell concise and single-line where possible. "
                    "Vendor Response should usually be one short sentence (max ~20 words). "
                    "Vendor Remarks must stay very brief (max ~10 words) and should not become paragraph-length.\n"
                    "Keep the original requirement text, IDs, and descriptions unchanged.\n"
                    "Return the content as a populated markdown table matching the original layout.\n\n"
                    f"### ORIGINAL RFP TABLE:\n```\n{original_table_text[:6000]}\n```\n\n"
                    "The JSON output's 'content' field should contain this filled-in markdown table."
                )
                logger.info(
                    f"[TABLE-TRACE][C2-WRITE] Injected original table ({len(original_table_text)} chars) "
                    f"into prompt for section '{section_title}'"
                )
        else:
            table_instruction = (
                "\n\n## OUTPUT FORMAT GUARDRAIL\n"
                "Return narrative prose for this section.\n"
                "Do NOT output markdown tables, requirement matrices, KPI grids, or pricing schedules here.\n"
                "Use short paragraphs and bullets only when they improve readability.\n"
            )

        prompt = (
            template
            .replace("{section_title}", section_title)
            .replace("{section_type}", section_type)
            .replace("{section_description}", section_description[:500])
            .replace("{content_guidance}", (content_guidance or "None specified.")[:budget_guide])
            .replace("{requirements}", requirements[:budget_reqs])
            .replace("{capabilities}", capabilities[:budget_caps])
            .replace("{rfp_instructions}", (rfp_instructions or "No specific response instructions.")[:budget_inst])
            .replace("{rfp_metadata}", rfp_metadata or "No metadata available.")
            .replace("{prev_section_context}", prev_section_context or "No previous section.")
            .replace("{next_section_context}", next_section_context or "No next section.")
            .replace("{revision_feedback}", feedback_block)
        )
        return prompt + table_instruction

    def _parse_response(
        self, raw_response: str, section_id: str
    ) -> tuple[str, list[str], int]:
        """
        Parse LLM response into (content, requirements_addressed, word_count).
        Falls back to using raw text as content on parse failure.
        """
        text = raw_response.strip()
        if not text:
            logger.warning(f"[C2] Empty LLM response for section {section_id}")
            return "", [], 0

        # Strip <think>...</think> tags that Qwen models emit
        text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.DOTALL).strip()

        # Strip markdown code fences — try lazy match first, then greedy
        # to handle nested ```mermaid blocks inside JSON content
        fence_match = re.search(
            r"```(?:json)?\s*(.*?)\s*```",
            text,
            re.DOTALL,
        )
        json_extracted = None
        if fence_match:
            candidate_text = fence_match.group(1).strip()
            # Verify it's actually valid JSON before committing
            try:
                json_extracted = json.loads(candidate_text, strict=False)
            except json.JSONDecodeError:
                # Lazy match may have stopped at an inner ``` (e.g. mermaid block)
                # Try greedy: find LAST ``` close
                greedy_match = re.search(
                    r"```(?:json)?\s*(.*)\s*```",
                    text,
                    re.DOTALL,
                )
                if greedy_match:
                    candidate_text = greedy_match.group(1).strip()

            if json_extracted is None:
                text = candidate_text

        # Try JSON parse
        data = json_extracted  # may already be parsed from fence
        if data is None:
            try:
                data = json.loads(text, strict=False)
            except json.JSONDecodeError:
                # Try extracting JSON object from mixed content
                obj_start = text.find("{")
                obj_end = text.rfind("}")
                if obj_start != -1 and obj_end > obj_start:
                    try:
                        candidate = text[obj_start : obj_end + 1]
                        # Fix trailing commas
                        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
                        data = json.loads(candidate, strict=False)
                    except json.JSONDecodeError:
                        # Attempt JSON repair for truncated output
                        data = self._attempt_json_repair(
                            text[obj_start : obj_end + 1], section_id
                        )
                else:
                    data = None

        if not data:
            data = self._fallback_regex_parse(text, section_id)

        if isinstance(data, dict):
            content = data.get("content", "")
            addressed = data.get("requirements_addressed", [])
            word_count = data.get("word_count", 0)

            # Ensure types
            if not isinstance(addressed, list):
                addressed = []
            addressed = [str(rid) for rid in addressed]

            # Always use actual word count — LLM self-reported counts
            # are systematically inflated by 18-95%.
            actual_word_count = len(content.split()) if content else 0

            # ── Strip duplicate code blocks from parsed content ──
            # Even after successful JSON parse, the "content" field may
            # contain the LLM's own format echoes (```json / ```markdown blocks)
            content = self._strip_echo_blocks(content)

            # ── Strip internal headers to ensure clean batched merging ──
            # Remove any Markdown header (# Title) that appears at the very beginning of the output.
            content = re.sub(r'^\s*(?:#+)\s+[^\n]+\n+', '', content).strip()

            return content, addressed, actual_word_count

        # Fallback: treat entire response as content, but recover REQ-IDs
        logger.warning(
            f"[C2] Could not parse JSON for section {section_id} — "
            f"using raw text as content (recovering REQ-IDs from text)"
        )
        fallback_content = raw_response.strip()

        # ── Strip JSON wrapper artifacts that bleed into prose ──
        # If the LLM returned a JSON wrapper but we couldn't parse it,
        # strip the structural keys so they don't appear in the proposal.
        fallback_content = re.sub(
            r'^```(?:json)?\s*', '', fallback_content
        )
        fallback_content = re.sub(
            r'^\s*\{\s*"content"\s*:\s*"', '', fallback_content
        )
        # Remove trailing JSON metadata: ", "requirements_addressed": [...], "word_count": N }
        fallback_content = re.sub(
            r'",\s*"requirements_addressed"\s*:\s*\[.*?\]\s*,?\s*"word_count"\s*:\s*\d+\s*\}\s*```?\s*$',
            '', fallback_content, flags=re.DOTALL,
        )
        
        # Clean up escaped newlines first, then quotes
        fallback_content = fallback_content.replace('\\n', '\n').replace('\\"', '"')

        # ── Strip echo blocks (```json, ```markdown, ### Content, ### JSON Output) ──
        fallback_content = self._strip_echo_blocks(fallback_content)

        fallback_content = fallback_content.strip()

        # Auto-recover requirements_addressed from REQ-XXXX patterns
        recovered_ids = list(dict.fromkeys(
            re.findall(r'\bREQ-\d{4}\b', fallback_content)
        ))
        if recovered_ids:
            logger.info(
                f"[C2] Recovered {len(recovered_ids)} requirement IDs "
                f"from prose for {section_id}: {recovered_ids}"
            )
        return fallback_content, recovered_ids, len(fallback_content.split())

    @staticmethod
    def _strip_echo_blocks(content: str) -> str:
        """Strip LLM echo blocks — ```json, ```markdown and similar fences
        that duplicate already-rendered content, plus spurious labels like
        '### Content' and '### JSON Output'.

        Preserves ```mermaid blocks which are intentional diagram content.
        """
        if not content:
            return content

        # Remove ```json { "content": "..." ... } ``` blocks (full JSON echoes)
        content = re.sub(
            r'```json\s*\n\s*\{[^`]*?"content"\s*:.*?\}\s*\n\s*```',
            '', content, flags=re.DOTALL,
        )

        # Remove ```markdown ... ``` blocks (content echoed in markdown fence)
        content = re.sub(
            r'```markdown\s*\n.*?```',
            '', content, flags=re.DOTALL,
        )

        # Remove spurious LLM section labels that prefix echo blocks
        content = re.sub(
            r'^###\s*(?:Content|JSON Output|Markdown Output)\s*$',
            '', content, flags=re.MULTILINE,
        )

        content = re.sub(
            r'"\s*,\s*"requirements_addressed"\s*:\s*\[.*?\]\s*,\s*"word_count"\s*:\s*\d+\s*\}',
            '',
            content,
            flags=re.DOTALL,
        )
        content = re.sub(
            r'^\s*\}\s*$',
            '',
            content,
            flags=re.MULTILINE,
        )

        # Collapse 3+ consecutive blank lines into 2
        content = re.sub(r'\n{3,}', '\n\n', content)

        return content.strip()

    @staticmethod
    def _detect_placeholders(content: str, section_id: str) -> list[str]:
        """Detect unfilled placeholder brackets in generated content."""
        found = _PLACEHOLDER_RE.findall(content)
        if found:
            logger.warning(f"[C2] {len(found)} placeholder(s) in {section_id}: {found}")
        return found

    @staticmethod
    def _attempt_json_repair(text: str, section_id: str) -> dict | None:
        """Try to fix common JSON issues from truncated LLM output."""
        tag = f"[C2] JSON repair ({section_id})"
        # Strip trailing commas
        repaired = re.sub(r",\s*([}\]])", r"\1", text)
        # Close unclosed strings
        if repaired.count('"') % 2 != 0:
            repaired += '"'
        # Close unclosed arrays
        open_brackets = repaired.count("[") - repaired.count("]")
        repaired += "]" * max(open_brackets, 0)
        # Close unclosed braces
        open_braces = repaired.count("{") - repaired.count("}")
        repaired += "}" * max(open_braces, 0)
        try:
            data = json.loads(repaired, strict=False)
            logger.info(f"{tag} Repair succeeded")
            return data
        except json.JSONDecodeError:
            logger.debug(f"{tag} Repair failed")
            return None

    def _fallback_regex_parse(self, text: str, section_id: str) -> dict | None:
        """Fallback to regex extraction when JSON parsing fails (e.g. unescaped newlines)."""
        tag = f"[C2] Regex fallback ({section_id})"
        content = ""
        reqs = []
        word_count = 0

        # Extract content (allow unescaped newlines inside the quotes)
        content_match = re.search(
            r'"content"\s*:\s*"(.*?)"\s*(?:,\s*"requirements_addressed"|,\s*"word_count"|})',
            text, re.DOTALL
        )
        if content_match:
            content = content_match.group(1)
            # Unescape quotes
            content = content.replace('\\"', '"').replace('\\n', '\n')

        # Extract requirements
        req_match = re.search(
            r'"requirements_addressed"\s*:\s*\[(.*?)\]',
            text, re.DOTALL
        )
        if req_match:
            req_str = req_match.group(1)
            reqs = re.findall(r'"([^"]+)"', req_str)

        # Extract word count
        wc_match = re.search(r'"word_count"\s*:\s*(\d+)', text)
        if wc_match:
            word_count = int(wc_match.group(1))

        if content or reqs:
            logger.info(f"{tag} Extracted {len(content)} chars and {len(reqs)} reqs via regex")
            return {
                "content": content,
                "requirements_addressed": reqs,
                "word_count": word_count
            }
        return None

    def _build_coverage_matrix(
        self,
        req_map: dict[str, dict[str, Any]],
        all_addressed: dict[str, list[str]],
        c1_assignments: dict[str, list[str]] | None = None,
        section_content_by_id: dict[str, str] | None = None,
    ) -> list[CoverageEntry]:
        """
        Build the coverage matrix comparing requirements to sections that address them.

        Coverage quality:
          - "full"    — requirement addressed in at least one section
          - "partial" — requirement assigned by C1 but not confirmed addressed by C2
          - "missing" — requirement not assigned to or addressed by any section
        """
        if c1_assignments is None:
            c1_assignments = {}
        if section_content_by_id is None:
            section_content_by_id = {}

        matrix: list[CoverageEntry] = []

        for req_id in sorted(req_map.keys()):
            section_ids = all_addressed.get(req_id, [])
            c1_section_ids = c1_assignments.get(req_id, [])

            if section_ids:
                addressed_section = section_ids[0]
                coverage_quality = "full"
                section_content = section_content_by_id.get(addressed_section, "")
                if not self._is_requirement_fully_rendered(
                    req_id,
                    req_map.get(req_id, {}),
                    section_content,
                ):
                    coverage_quality = "partial"

                matrix.append(
                    CoverageEntry(
                        requirement_id=req_id,
                        addressed_in_section=addressed_section,
                        coverage_quality=coverage_quality,
                    )
                )
            elif c1_section_ids:
                # Assigned by C1 architecture plan but not addressed by C2 LLM
                matrix.append(
                    CoverageEntry(
                        requirement_id=req_id,
                        addressed_in_section=c1_section_ids[0],
                        coverage_quality="partial",
                    )
                )
            else:
                # Not assigned or addressed anywhere
                matrix.append(
                    CoverageEntry(
                        requirement_id=req_id,
                        addressed_in_section="",
                        coverage_quality="missing",
                    )
                )

        return matrix

    @staticmethod
    def _is_requirement_fully_rendered(
        req_id: str,
        req: dict[str, Any],
        section_content: str,
    ) -> bool:
        """Downgrade claimed coverage when the rendered row is missing or unresolved."""
        if not section_content:
            return False

        source_table_chunk_index = req.get("source_table_chunk_index", -1)
        is_table_backed = source_table_chunk_index >= 0 or bool(
            _PRICING_REQ_ID_RE.match(req_id)
            or _TECHNICAL_REQ_ID_RE.match(req_id)
            or _KPI_REQ_ID_RE.match(req_id)
            or _COMPLIANCE_REQ_ID_RE.match(req_id)
        )
        if not is_table_backed:
            return True

        for line in section_content.splitlines():
            if req_id in line:
                return not bool(_UNRESOLVED_CELL_RE.search(line))
        return False
