"""
A2 — RFP Structuring Agent
Responsibility: Query MCP RFP store, classify document into sections,
                assign confidence scores.  Retry up to 3x if confidence is low.

Chunking strategies (one per retry):
  Attempt 0 — retrieve all stored chunks (broad retrieval)
  Attempt 1 — category-specific targeted queries (6 queries, deduplicated)
  Attempt 2 — re-chunk raw text with smaller windows (500 chars, 100 overlap)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.config import get_settings
from rfp_automation.mcp import MCPService
from rfp_automation.models.enums import AgentName, PipelineStatus
from rfp_automation.models.schemas import RFPSection, StructuringResult
from rfp_automation.models.state import RFPGraphState
from rfp_automation.services.llm_service import llm_text_call

logger = logging.getLogger(__name__)

# Section categories the agent classifies into
SECTION_CATEGORIES = [
    "scope",
    "technical",
    "compliance",
    "legal",
    "submission",
    "evaluation",
]

# Prompt template path
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "structuring_prompt.txt"


class StructuringAgent(BaseAgent):
    name = AgentName.A2_STRUCTURING

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        rfp_id = state.rfp_metadata.rfp_id
        if not rfp_id:
            raise ValueError("No rfp_id in state — A1 Intake must run first")

        retry_count = state.structuring_result.retry_count
        logger.info(f"[A2] Structuring attempt {retry_count} for {rfp_id}")
        logger.debug(f"[A2] Previous confidence: {state.structuring_result.overall_confidence:.4f}")
        logger.debug(f"[A2] Previous sections: {len(state.structuring_result.sections)}")

        # ── 1. Retrieve all chunks deterministically ────────────────
        mcp = MCPService()
        chunks = self._retrieve_chunks(mcp, rfp_id)
        logger.debug(f"[A2] Retrieved {len(chunks) if chunks else 0} chunks (attempt {retry_count})")

        if not chunks:
            logger.warning(f"[A2] No chunks retrieved for {rfp_id}")
            state.structuring_result = StructuringResult(
                sections=[],
                overall_confidence=0.0,
                retry_count=retry_count + 1,
            )
            state.status = PipelineStatus.STRUCTURING
            return state

        # ── 2. Build prompts in batches (token-aware) ────────────
        batches = self._batch_chunks(chunks)
        logger.info(f"[A2] Split {len(chunks)} chunks into {len(batches)} batch(es)")

        # ── 3. Call LLM on each batch and merge sections ─────────
        import time
        all_sections: list[RFPSection] = []

        for batch_idx, batch in enumerate(batches):
            prompt = self._build_prompt(batch, retry_count, state.structuring_result)
            logger.info(
                f"[A2] Calling LLM: batch {batch_idx + 1}/{len(batches)} "
                f"({len(batch)} chunks, {len(prompt)} char prompt)"
            )

            sections = self._call_llm_and_parse(prompt)
            all_sections.extend(sections)

            for s in sections:
                logger.debug(
                    f"[A2]   Section: {s.section_id} | {s.category} | "
                    f"confidence={s.confidence:.3f} | {s.title[:60]}"
                )

            # Rate-limit delay between batches
            if batch_idx < len(batches) - 1:
                time.sleep(2.0)

        # Deduplicate sections by title (batches may overlap)
        sections = self._deduplicate_sections(all_sections)

        # ── 4. Compute confidence ────────────────────────────────────
        if sections:
            overall_confidence = sum(s.confidence for s in sections) / len(sections)
        else:
            overall_confidence = 0.0

        logger.info(
            f"[A2] Got {len(sections)} sections, "
            f"overall_confidence={overall_confidence:.3f}"
        )
        if overall_confidence < 0.6:
            logger.debug(
                f"[A2] Confidence {overall_confidence:.3f} < 0.6 threshold — will retry "
                f"(attempt {retry_count + 1})"
            )
        else:
            logger.debug(f"[A2] Confidence {overall_confidence:.3f} >= 0.6 — proceeding to Go/No-Go")

        # ── 5. Build result and update state ─────────────────────────
        result = StructuringResult(
            sections=sections,
            overall_confidence=round(overall_confidence, 4),
            retry_count=retry_count + 1 if overall_confidence < 0.6 else retry_count,
        )
        state.structuring_result = result

        # Let the orchestration router decide next step based on confidence
        if overall_confidence >= 0.6:
            state.status = PipelineStatus.GO_NO_GO
        else:
            state.status = PipelineStatus.STRUCTURING

        return state

    # ── Chunk batching ────────────────────────────────────────

    @staticmethod
    def _batch_chunks(
        chunks: list[dict[str, Any]],
        max_batch_chars: int = 6000,
    ) -> list[list[dict[str, Any]]]:
        """
        Split chunks into token-aware batches.

        max_batch_chars ≈ 1500 tokens (at 4 chars/token).
        Each batch must fit within Groq's TPM limit when combined
        with the prompt overhead (~500 tokens).
        """
        batches: list[list[dict[str, Any]]] = []
        current_batch: list[dict[str, Any]] = []
        current_size = 0

        for chunk in chunks:
            text = chunk.get("text", "")
            chunk_size = len(text) + 30  # overhead for [Chunk N] header

            # If a single chunk exceeds limit, truncate and add alone
            if chunk_size > max_batch_chars:
                if current_batch:
                    batches.append(current_batch)
                    current_batch = []
                    current_size = 0
                truncated = {**chunk, "text": text[:max_batch_chars - 30]}
                batches.append([truncated])
                continue

            if current_size + chunk_size > max_batch_chars:
                batches.append(current_batch)
                current_batch = []
                current_size = 0

            current_batch.append(chunk)
            current_size += chunk_size

        if current_batch:
            batches.append(current_batch)

        return batches if batches else [[]]  # at least one empty batch

    @staticmethod
    def _deduplicate_sections(sections: list[RFPSection]) -> list[RFPSection]:
        """
        Remove duplicate sections from multi-batch results.
        Keeps the section with the highest confidence when titles match.
        """
        seen: dict[str, RFPSection] = {}
        for section in sections:
            key = section.title.strip().lower()
            if key not in seen or section.confidence > seen[key].confidence:
                seen[key] = section

        unique = list(seen.values())
        for i, sec in enumerate(unique, 1):
            sec.section_id = f"SEC-{i:02d}"
        return unique

    # ── Chunk retrieval ────────────────────────────────────────

    def _retrieve_chunks(
        self,
        mcp: MCPService,
        rfp_id: str,
    ) -> list[dict[str, Any]]:
        """
        Retrieve all stored chunks deterministically in document order.

        Since A1 uses section-aware semantic chunks, a single deterministic
        fetch is sufficient — the section structure is already embedded in the
        chunks themselves.  On retry, the LLM prompt includes a retry hint
        referencing low-confidence sections, giving the LLM a different
        perspective on the same complete chunk set.
        """
        logger.info("[A2] Retrieving all stored chunks (deterministic fetch)")
        return mcp.fetch_all_rfp_chunks(rfp_id)

    # ── Prompt building ──────────────────────────────────────────

    def _build_prompt(
        self,
        chunks: list[dict[str, Any]],
        retry_count: int,
        previous_result: StructuringResult,
    ) -> str:
        """Load the prompt template and fill placeholders."""
        template = _PROMPT_PATH.read_text(encoding="utf-8")

        # Build retry hint first (needed for budget calculation)
        retry_hint = ""
        if retry_count > 0 and previous_result.sections:
            low_conf_sections = [
                s.title for s in previous_result.sections if s.confidence < 0.6
            ]
            if low_conf_sections:
                retry_hint = (
                    f"NOTE: This is retry attempt {retry_count}. "
                    f"Previous classification had low confidence on these sections: "
                    f"{', '.join(low_conf_sections)}. "
                    f"Try a different grouping or re-examine chunk boundaries."
                )
            else:
                retry_hint = (
                    f"NOTE: This is retry attempt {retry_count}. "
                    f"Previous overall confidence was {previous_result.overall_confidence:.2f}. "
                    f"Be more precise in your classification."
                )

        # ── Token-aware chunk truncation ─────────────────────────
        # Reserve tokens: template (~500 tok) + retry hint + output (2K)
        chars_per_token = 4  # conservative estimate
        settings = get_settings()
        max_prompt_tokens = settings.llm_max_tokens  # model's token window
        reserved_output_tokens = 2000
        template_tokens = len(template) // chars_per_token + 100  # overhead
        retry_hint_tokens = len(retry_hint) // chars_per_token
        available_tokens = max_prompt_tokens - reserved_output_tokens - template_tokens - retry_hint_tokens
        available_chars = max(available_tokens * chars_per_token, 4000)  # floor

        # Format chunks as numbered text blocks
        chunk_texts = []
        for i, chunk in enumerate(chunks):
            text = chunk.get("text", "").strip()
            if text:
                chunk_texts.append(f"[Chunk {i + 1}]\n{text}")

        total_chars = sum(len(t) for t in chunk_texts)

        if total_chars > available_chars and chunk_texts:
            # Proportionally truncate each chunk's text
            # Keep at least 100 chars per chunk for context, header first
            overhead_per_chunk = 15  # "[Chunk NN]\n"
            usable_chars = available_chars - (overhead_per_chunk * len(chunk_texts))
            max_per_chunk = max(usable_chars // len(chunk_texts), 100)

            logger.info(
                f"[A2] Prompt too large ({total_chars} chars, ~{total_chars // chars_per_token} tokens). "
                f"Truncating {len(chunk_texts)} chunks to ~{max_per_chunk} chars each "
                f"(budget: {available_chars} chars)"
            )

            truncated = []
            for i, chunk in enumerate(chunks):
                text = chunk.get("text", "").strip()
                if text:
                    if len(text) > max_per_chunk:
                        text = text[:max_per_chunk] + "…"
                    truncated.append(f"[Chunk {i + 1}]\n{text}")
            chunk_texts = truncated

        chunks_str = "\n\n".join(chunk_texts)

        return template.format(chunks=chunks_str, retry_hint=retry_hint)

    # ── LLM call and response parsing ────────────────────────────

    def _call_llm_and_parse(self, prompt: str) -> list[RFPSection]:
        """Call LLM and parse JSON response into RFPSection objects."""
        try:
            raw_response = llm_text_call(prompt, deterministic=True)
            logger.debug(f"[A2] Raw LLM response ({len(raw_response)} chars):\n{raw_response[:2000]}")
        except Exception as exc:
            logger.error(f"[A2] LLM call failed: {exc}")
            return []

        parsed = self._parse_sections_json(raw_response)
        logger.debug(f"[A2] Parsed {len(parsed)} sections from LLM response")
        return parsed

    def _parse_sections_json(self, raw_response: str) -> list[RFPSection]:
        """
        Parse the LLM response into a list of RFPSection.
        Handles common issues: markdown fencing, extra text around JSON.
        Returns empty list on failure (triggers retry via low confidence).
        """
        text = raw_response.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (fences)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        # Try to extract JSON array from the response
        try:
            start = text.index("[")
            end = text.rindex("]") + 1
            text = text[start:end]
        except ValueError:
            logger.warning("[A2] No JSON array found in LLM response")
            return []

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning(f"[A2] JSON parse error: {exc}")
            return []

        if not isinstance(data, list):
            logger.warning("[A2] LLM response is not a JSON array")
            return []

        # Validate and build RFPSection objects
        sections: list[RFPSection] = []
        for i, item in enumerate(data):
            try:
                section = RFPSection(
                    section_id=item.get("section_id", f"SEC-{i + 1:02d}"),
                    title=item.get("title", "Untitled"),
                    category=self._normalize_category(
                        item.get("category", "scope")
                    ),
                    content_summary=item.get("content_summary", ""),
                    confidence=float(item.get("confidence", 0.0)),
                    page_range=item.get("page_range", ""),
                )
                sections.append(section)
            except (ValueError, TypeError) as exc:
                logger.warning(f"[A2] Skipping invalid section {i}: {exc}")
                continue

        return sections

    @staticmethod
    def _normalize_category(category: str) -> str:
        """Ensure category is one of the valid values."""
        normalized = category.strip().lower()
        if normalized in SECTION_CATEGORIES:
            return normalized
        # Fuzzy fallback
        for valid in SECTION_CATEGORIES:
            if valid in normalized or normalized in valid:
                return valid
        return "scope"  # default fallback
