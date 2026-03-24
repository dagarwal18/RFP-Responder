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
            req_texts = []
            for rid in req_ids:
                req = req_map.get(rid)
                if req:
                    req_type = req.get("type", "MANDATORY")
                    req_text = req.get("text", "")[:300]
                    req_texts.append(f"- {rid} [{req_type}]: {req_text}")
                else:
                    req_texts.append(f"- {rid}: [requirement details not found]")

            requirements_block = (
                "\n".join(req_texts) if req_texts else "No specific requirements assigned."
            )

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
            _TABLE_SECTION_RE = re.compile(
                r'\b(?:compliance\s*matrix|requirements\s*matrix|response\s*table'
                r'|C/PC/NC|compliance\s*table|technical\s*matrix'
                r'|capability\s*matrix|conformance\s*matrix'
                r'|vendor\s*response|fill[\s-]*in|questionnaire'
                r'|checklist|self[\s-]*assessment|declaration\s*form)\b',
                re.IGNORECASE,
            )
            desc_and_guidance = (
                self._get_attr(section, "description", "") + " "
                + self._get_attr(section, "content_guidance", "")
            )
            table_mode = bool(_TABLE_SECTION_RE.search(desc_and_guidance))

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
                            if tbl_chunk:
                                original_table_text = tbl_chunk.get("text", "")
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
            else:
                # Also check if any mapped requirements come from table chunks
                for rid in req_ids:
                    req = req_map.get(rid)
                    if req:
                        src_indices = req.get("source_chunk_indices", [])
                        for si in src_indices:
                            if si in table_chunks_by_index:
                                table_mode = True
                                tbl_chunk = table_chunks_by_index[si]
                                original_table_text = tbl_chunk.get("text", "")
                                logger.info(
                                    f"[TABLE-TRACE][C2-WRITE] Auto-detected table_mode "
                                    f"for {section_id} via req {rid} → chunk_index={si}, "
                                    f"table_type={tbl_chunk.get('table_type', 'unknown')}"
                                )
                                break
                    if original_table_text:
                        break

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
                        if tci >= 0 and tci in table_chunks_by_index:
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
                                if si in table_chunks_by_index:
                                    first_tci = si
                                    break
                        if first_tci is not None:
                            break
                    if first_tci is not None:
                        table_groups[first_tci] = req_ids
                        ungrouped = []

                logger.info(
                    f"[TABLE-TRACE][C2-WRITE] Per-table processing for {section_id}: "
                    f"{len(table_groups)} table group(s), {len(ungrouped)} ungrouped reqs"
                )

                all_table_contents: list[str] = []
                all_table_addressed: list[str] = []
                total_table_wc = 0

                for tci, group_rids in sorted(table_groups.items()):
                    tbl_chunk = table_chunks_by_index[tci]
                    tbl_text = tbl_chunk.get("text", "")

                    # Extract and log headers for this specific table (must have at least 2 pipes)
                    pipe_lines = [l for l in tbl_text.split("\n") if l.count("|") >= 2]
                    if pipe_lines:
                        logger.info(
                            f"[TABLE-TRACE][C2-WRITE] these headers are extracted: "
                            f"{pipe_lines[0].strip()}"
                        )
                    else:
                        logger.warning(
                            f"[TABLE-TRACE][C2-WRITE] headers not extracted "
                            f"for table chunk {tci}"
                        )

                    logger.info(
                        f"[TABLE-TRACE][C2-WRITE] Processing table chunk {tci} "
                        f"with {len(group_rids)} reqs for {section_id}"
                    )

                    # Fill this one table independently
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
                        original_headers=pipe_lines,
                    )

                    logger.info(
                        f"[TABLE-TRACE][C2-WRITE] table is merged for chunk {tci}"
                    )

                    all_table_contents.append(filled_content)
                    all_table_addressed.extend(addrs)
                    total_table_wc += wc

                # Handle ungrouped requirements as normal prose
                if ungrouped:
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
                addressed = list(dict.fromkeys(all_table_addressed))
                word_count = total_table_wc
                logger.info(
                    f"[TABLE-TRACE][C2-WRITE] final table stored: "
                    f"{len(table_groups)} table(s) for '{section_id}'"
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
                addressed = list(dict.fromkeys(chunk_addressed_list))
                word_count = total_word_count

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
        coverage_matrix = self._build_coverage_matrix(
            req_map, all_addressed, c1_assignments,
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

        # Fetch from MCP
        for query in queries:
            try:
                results = mcp.query_knowledge(query, top_k=3)
                for r in results:
                    text = r.get("text", "").strip()
                    if text and text not in seen_texts:
                        seen_texts.add(text)
                        capability_texts.append(text)
            except Exception as exc:
                logger.warning(f"[C2] Knowledge query failed for '{query}': {exc}")

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

        if original_headers:
            header_block = "\n".join(original_headers)
            
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
                
            # Create a markdown separator
            separator = "|" + "|".join(["---"] * col_count) + "|"
            
            # Add separator if it's not already there
            if "---" not in last_line:
                table_header = header_block + "\n" + separator
            else:
                table_header = header_block
                
            all_content_parts.append(table_header)

        # Even for small tables, we run through the batch loop once to use consistent logic
        for batch_idx in range(0, max(1, len(req_ids)), batch_size):
            batch_rids = req_ids[batch_idx : batch_idx + batch_size]
            batch_num = batch_idx // batch_size + 1

            batch_req_texts = []
            for rid in batch_rids:
                req = req_map.get(rid)
                if req:
                    req_type = req.get("type", "MANDATORY")
                    req_text = req.get("text", "")[:300]
                    batch_req_texts.append(f"- {rid} [{req_type}]: {req_text}")
                else:
                    batch_req_texts.append(f"- {rid}: [requirement details not found]")
            batch_requirements_block = "\n".join(batch_req_texts)

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
                original_table_text=table_text,
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
            if batch_num * batch_size < len(req_ids):
                logger.info(
                    f"[C2] Batch {batch_num} complete. Pausing 65s to fully reset TPM limits..."
                )
                time.sleep(65)

            all_batch_addressed.extend(batch_addressed)
            total_word_count += batch_wc

            # Merge table rows, keeping only the first batch's header
            if batch_content.strip():
                lines = batch_content.strip().split("\n")
                table_lines = [line for line in lines if "|" in line]
                
                if table_lines:
                    if table_header is None:
                        # First batch with a table provides the overarching header
                        if len(table_lines) >= 2 and "---" in table_lines[1] and "|" in table_lines[0]:
                            table_header = table_lines[0] + "\n" + table_lines[1]
                            all_content_parts.append("\n".join(table_lines))
                        else:
                            all_content_parts.append(batch_content.strip())
                    else:
                        # Subsequent batches (or if we pre-populated table_header): 
                        # strip the header and separator rows generated by the LLM
                        data_lines = []
                        
                        start_idx = 0
                        if len(table_lines) >= 2 and "---" in table_lines[1]:
                            start_idx = 2
                        elif len(table_lines) >= 1 and "---" in table_lines[0]:
                            start_idx = 1
                            
                        for line in table_lines[start_idx:]:
                            if "---" in line:
                                continue
                            data_lines.append(line)
                            
                        if data_lines:
                            all_content_parts.append("\n".join(data_lines))
                else:
                    all_content_parts.append(batch_content.strip())

        content = "\n".join(all_content_parts)
        addressed = list(dict.fromkeys(all_batch_addressed))
        return content, addressed, total_word_count

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
                    "Keep the original requirement text, IDs, and descriptions unchanged.\n"
                    "Return the content as a populated markdown table matching the original layout.\n\n"
                    f"### ORIGINAL RFP TABLE:\n```\n{original_table_text[:6000]}\n```\n\n"
                    "The JSON output's 'content' field should contain this filled-in markdown table."
                )
                logger.info(
                    f"[TABLE-TRACE][C2-WRITE] Injected original table ({len(original_table_text)} chars) "
                    f"into prompt for section '{section_title}'"
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

        matrix: list[CoverageEntry] = []

        for req_id in sorted(req_map.keys()):
            section_ids = all_addressed.get(req_id, [])
            c1_section_ids = c1_assignments.get(req_id, [])

            if section_ids:
                # Fully addressed — LLM confirmed addressing it
                matrix.append(
                    CoverageEntry(
                        requirement_id=req_id,
                        addressed_in_section=section_ids[0],
                        coverage_quality="full",
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
