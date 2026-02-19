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
from rfp_automation.services.parsing_service import ParsingService

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

        # ── 1. Retrieve chunks using strategy based on retry count ───
        mcp = MCPService()
        chunks = self._retrieve_chunks(mcp, rfp_id, retry_count, state.raw_text)

        if not chunks:
            logger.warning(f"[A2] No chunks retrieved for {rfp_id}")
            state.structuring_result = StructuringResult(
                sections=[],
                overall_confidence=0.0,
                retry_count=retry_count + 1,
            )
            state.status = PipelineStatus.STRUCTURING
            return state

        # ── 2. Build prompt ──────────────────────────────────────────
        prompt = self._build_prompt(chunks, retry_count, state.structuring_result)

        # ── 3. Call LLM ──────────────────────────────────────────────
        logger.info(f"[A2] Calling LLM with {len(chunks)} chunks")
        sections = self._call_llm_and_parse(prompt)

        # ── 4. Compute confidence ────────────────────────────────────
        if sections:
            overall_confidence = sum(s.confidence for s in sections) / len(sections)
        else:
            overall_confidence = 0.0

        logger.info(
            f"[A2] Got {len(sections)} sections, "
            f"overall_confidence={overall_confidence:.3f}"
        )

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

    # ── Chunking strategies ──────────────────────────────────────

    def _retrieve_chunks(
        self,
        mcp: MCPService,
        rfp_id: str,
        retry_count: int,
        raw_text: str,
    ) -> list[dict[str, Any]]:
        """
        Pick retrieval strategy based on retry count:
          0 → all stored chunks (broad retrieval)
          1 → category-specific targeted queries
          2+ → re-chunk raw text with smaller windows
        """
        if retry_count == 0:
            return self._strategy_all_chunks(mcp, rfp_id)
        elif retry_count == 1:
            return self._strategy_category_queries(mcp, rfp_id)
        else:
            return self._strategy_rechunk(raw_text)

    def _strategy_all_chunks(
        self, mcp: MCPService, rfp_id: str
    ) -> list[dict[str, Any]]:
        """Attempt 0: retrieve all stored chunks in document order."""
        logger.info("[A2] Strategy 0: retrieving all stored chunks")
        return mcp.query_rfp_all_chunks(rfp_id, top_k=100)

    def _strategy_category_queries(
        self, mcp: MCPService, rfp_id: str
    ) -> list[dict[str, Any]]:
        """Attempt 1: run 6 category-specific queries and deduplicate."""
        logger.info("[A2] Strategy 1: category-specific targeted queries")
        category_queries = {
            "scope": "project scope objectives deliverables background overview",
            "technical": "technical requirements specifications architecture system design",
            "compliance": "compliance regulatory standards certifications requirements",
            "legal": "legal terms contract liability indemnification intellectual property",
            "submission": "submission instructions deadline format proposal delivery",
            "evaluation": "evaluation criteria scoring methodology selection process weighting",
        }

        seen_ids: set[str] = set()
        all_chunks: list[dict[str, Any]] = []

        for category, query in category_queries.items():
            results = mcp.query_rfp(query, rfp_id, top_k=10)
            for chunk in results:
                chunk_id = chunk.get("id", "")
                if chunk_id not in seen_ids:
                    seen_ids.add(chunk_id)
                    all_chunks.append(chunk)

        # Sort by chunk_index for document order
        all_chunks.sort(key=lambda c: c.get("chunk_index", -1))
        return all_chunks

    def _strategy_rechunk(self, raw_text: str) -> list[dict[str, Any]]:
        """Attempt 2+: re-chunk raw text with smaller windows for finer granularity."""
        logger.info("[A2] Strategy 2: re-chunking raw text with smaller windows")
        if not raw_text:
            logger.warning("[A2] No raw_text available for re-chunking")
            return []

        small_chunks = ParsingService.chunk_text(
            raw_text, chunk_size=500, overlap=100
        )
        return [
            {
                "id": f"rechunk_{i:04d}",
                "score": 1.0,
                "text": chunk,
                "chunk_index": i,
                "metadata": {"rechunked": True},
            }
            for i, chunk in enumerate(small_chunks)
        ]

    # ── Prompt building ──────────────────────────────────────────

    def _build_prompt(
        self,
        chunks: list[dict[str, Any]],
        retry_count: int,
        previous_result: StructuringResult,
    ) -> str:
        """Load the prompt template and fill placeholders."""
        template = _PROMPT_PATH.read_text(encoding="utf-8")

        # Format chunks as numbered text blocks
        chunk_texts = []
        for i, chunk in enumerate(chunks):
            text = chunk.get("text", "").strip()
            if text:
                chunk_texts.append(f"[Chunk {i + 1}]\n{text}")

        chunks_str = "\n\n".join(chunk_texts)

        # Build retry hint
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

        return template.format(chunks=chunks_str, retry_hint=retry_hint)

    # ── LLM call and response parsing ────────────────────────────

    def _call_llm_and_parse(self, prompt: str) -> list[RFPSection]:
        """Call LLM and parse JSON response into RFPSection objects."""
        try:
            raw_response = llm_text_call(prompt)
        except Exception as exc:
            logger.error(f"[A2] LLM call failed: {exc}")
            return []

        return self._parse_sections_json(raw_response)

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
