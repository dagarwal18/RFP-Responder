"""
B1 — Requirements Extraction Agent  (Overhauled)

Architecture:
  1. Deterministic full-document sweep via MCP fetch_all_rfp_chunks()
  2. Rule-based obligation candidate detection (Layer 1)
  3. Constrained LLM structuring/classification (Layer 2)
  4. Embedding-based deduplication (cosine > threshold)
  5. Coverage validation with obligation indicator counting
  6. Stable sequential IDs in document order (REQ-0001, REQ-0002, ...)
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.config import get_settings
from rfp_automation.mcp import MCPService
from rfp_automation.models.enums import (
    AgentName,
    PipelineStatus,
    RequirementType,
    RequirementClassification,
    RequirementCategory,
    ImpactLevel,
)
from rfp_automation.models.schemas import Requirement
from rfp_automation.models.state import RFPGraphState
from rfp_automation.services.llm_service import llm_deterministic_call
from rfp_automation.services.obligation_detector import (
    ObligationDetector,
    CandidateSentence,
)

logger = logging.getLogger(__name__)

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "extraction_prompt.txt"
)


class RequirementsExtractionAgent(BaseAgent):
    name = AgentName.B1_REQUIREMENTS_EXTRACTION

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        settings = get_settings()
        rfp_id = state.rfp_metadata.rfp_id
        if not rfp_id:
            raise ValueError("No rfp_id in state — A1 Intake must run first")

        logger.info(f"[B1] Starting requirements extraction for {rfp_id}")

        # ── 1. Deterministic full-document retrieval ─────────
        mcp = MCPService()
        all_chunks = mcp.fetch_all_rfp_chunks(rfp_id)

        if not all_chunks:
            logger.warning("[B1] No chunks found — producing 0 requirements")
            state.requirements = []
            state.status = PipelineStatus.VALIDATING_REQUIREMENTS
            return state

        logger.info(
            f"[B1] Retrieved {len(all_chunks)} chunks deterministically "
            f"(sorted by chunk_index)"
        )

        # ── 2. Group chunks by section_hint ──────────────────
        section_groups = self._group_by_section(all_chunks)
        logger.info(f"[B1] Grouped into {len(section_groups)} sections")

        # ── 3. Load prompt template ──────────────────────────
        template = _PROMPT_PATH.read_text(encoding="utf-8")

        # ── 4. Two-layer extraction per section ──────────────
        all_requirements: list[Requirement] = []
        total_indicator_count = 0
        global_id_counter = 1

        for section_name, chunks in section_groups.items():
            # Concatenate raw text in document order
            raw_text = "\n\n".join(
                c.get("text", "") for c in chunks if c.get("text")
            )
            if not raw_text.strip():
                continue

            chunk_indices = [
                c.get("chunk_index", -1) for c in chunks
            ]

            # Layer 1: Rule-based obligation candidate detection
            candidates = ObligationDetector.detect_candidates(
                raw_text, source_section=section_name
            )
            section_indicators = ObligationDetector.count_indicators(raw_text)
            total_indicator_count += section_indicators

            if not candidates:
                logger.debug(
                    f"[B1] No obligation candidates in '{section_name}' "
                    f"({section_indicators} indicator matches but 0 candidate sentences)"
                )
                continue

            logger.debug(
                f"[B1] {len(candidates)} candidate sentences in "
                f"'{section_name}' ({section_indicators} indicator matches)"
            )

            # Layer 2: LLM structuring/classification
            candidate_text = "\n".join(
                f"[{i+1}] {c.text}" for i, c in enumerate(candidates)
            )

            start_id = f"REQ-{global_id_counter:04d}"
            prompt = template.format(
                section_title=section_name,
                candidate_text=candidate_text[:6000],
                section_context=raw_text[:4000],
                start_id=start_id,
            )

            try:
                raw_response = llm_deterministic_call(prompt)
                logger.debug(
                    f"[B1] LLM response for '{section_name}': "
                    f"{len(raw_response)} chars"
                )
            except Exception as exc:
                logger.error(
                    f"[B1] LLM call failed for section '{section_name}': {exc}"
                )
                continue

            # Parse into Requirement objects
            parsed = self._parse_requirements_json(
                raw_response, section_name, global_id_counter
            )

            # Attach chunk traceability
            for req in parsed:
                req.source_chunk_indices = chunk_indices

            logger.info(
                f"[B1] Extracted {len(parsed)} requirements from "
                f"'{section_name}'"
            )

            global_id_counter += len(parsed)
            all_requirements.extend(parsed)

        # ── 5. Deduplication (embedding-based + text fallback) ─
        before_dedup = len(all_requirements)
        all_requirements = self._deduplicate(
            all_requirements,
            threshold=settings.extraction_dedup_similarity_threshold,
        )
        logger.info(
            f"[B1] Deduplicated: {before_dedup} → {len(all_requirements)} requirements"
        )

        # ── 6. Stable sequential ID re-assignment ────────────
        for i, req in enumerate(all_requirements, start=1):
            req.requirement_id = f"REQ-{i:04d}"

        # ── 7. Coverage validation ───────────────────────────
        self._validate_coverage(
            all_requirements,
            total_indicator_count,
            settings.extraction_coverage_warn_ratio,
        )

        # ── 8. Update state ──────────────────────────────────
        state.requirements = all_requirements
        state.status = PipelineStatus.VALIDATING_REQUIREMENTS

        func_count = sum(
            1 for r in all_requirements
            if r.classification == RequirementClassification.FUNCTIONAL
        )
        nonfunc_count = sum(
            1 for r in all_requirements
            if r.classification == RequirementClassification.NON_FUNCTIONAL
        )
        logger.info(
            f"[B1] Extraction complete: {len(all_requirements)} requirements "
            f"(Functional: {func_count}, Non-Functional: {nonfunc_count})"
        )
        return state

    # ── Section grouping ─────────────────────────────────────

    @staticmethod
    def _group_by_section(
        chunks: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Group chunks by section_hint, preserving document order.

        Returns an OrderedDict-like dict (insertion order) where each key
        is a section name and the value is the list of chunks in that section.
        """
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for chunk in chunks:
            section = chunk.get("section_hint", "Untitled Section")
            groups[section].append(chunk)
        return dict(groups)

    # ── JSON parsing ─────────────────────────────────────────

    def _parse_requirements_json(
        self,
        raw_response: str,
        source_section: str,
        start_id: int,
    ) -> list[Requirement]:
        """Parse LLM JSON response into a list of Requirement objects."""
        text = raw_response.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        # Extract JSON array
        try:
            start = text.index("[")
            end = text.rindex("]") + 1
            text = text[start:end]
        except ValueError:
            logger.warning("[B1] No JSON array found in LLM response")
            return []

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning(f"[B1] JSON parse error: {exc}")
            return []

        if not isinstance(data, list):
            logger.warning("[B1] LLM response is not a JSON array")
            return []

        # Build Requirement objects
        requirements: list[Requirement] = []
        for i, item in enumerate(data):
            try:
                req = Requirement(
                    requirement_id=item.get(
                        "requirement_id", f"REQ-{start_id + i:04d}"
                    ),
                    text=item.get("text", ""),
                    type=self._normalize_type(item.get("type", "MANDATORY")),
                    classification=self._normalize_classification(
                        item.get("classification", "FUNCTIONAL")
                    ),
                    category=self._normalize_category(
                        item.get("category", "TECHNICAL")
                    ),
                    impact=self._normalize_impact(item.get("impact", "MEDIUM")),
                    source_section=source_section,
                    keywords=item.get("keywords", []),
                )
                if req.text.strip():
                    requirements.append(req)
            except (ValueError, TypeError) as exc:
                logger.warning(f"[B1] Skipping invalid requirement {i}: {exc}")
                continue

        return requirements

    # ── Deduplication (embedding-based + text fallback) ──────

    @staticmethod
    def _deduplicate(
        requirements: list[Requirement],
        threshold: float = 0.95,
    ) -> list[Requirement]:
        """
        Remove duplicate requirements using embedding similarity.

        Strategy:
          1. Try embedding-based dedup (cosine similarity > threshold).
          2. Fall back to text normalization if embeddings unavailable.

        Keeps the first occurrence in document order.
        """
        if not requirements:
            return requirements

        # Try embedding-based dedup
        try:
            return RequirementsExtractionAgent._embedding_dedup(
                requirements, threshold
            )
        except Exception as exc:
            logger.warning(
                f"[B1] Embedding dedup failed, falling back to text: {exc}"
            )
            return RequirementsExtractionAgent._text_dedup(requirements)

    @staticmethod
    def _embedding_dedup(
        requirements: list[Requirement],
        threshold: float,
    ) -> list[Requirement]:
        """Deduplicate using cosine similarity on requirement embeddings."""
        from rfp_automation.mcp.embeddings.embedding_model import EmbeddingModel

        embedder = EmbeddingModel()
        texts = [req.text for req in requirements]
        embeddings = embedder.embed_batch(texts)

        if not embeddings or len(embeddings) != len(requirements):
            raise ValueError("Embedding batch size mismatch")

        # Mark duplicates (O(n²) but n is typically < 500)
        is_duplicate = [False] * len(requirements)
        for i in range(len(requirements)):
            if is_duplicate[i]:
                continue
            for j in range(i + 1, len(requirements)):
                if is_duplicate[j]:
                    continue
                sim = _cosine_similarity(embeddings[i], embeddings[j])
                if sim > threshold:
                    is_duplicate[j] = True
                    logger.debug(
                        f"[B1] Duplicate detected (sim={sim:.3f}): "
                        f"'{requirements[j].text[:60]}' ≈ "
                        f"'{requirements[i].text[:60]}'"
                    )

        unique = [r for r, dup in zip(requirements, is_duplicate) if not dup]
        return unique

    @staticmethod
    def _text_dedup(requirements: list[Requirement]) -> list[Requirement]:
        """Fallback: deduplicate by normalized text."""
        seen: set[str] = set()
        unique: list[Requirement] = []
        for req in requirements:
            normalized = re.sub(r"\s+", " ", req.text.strip().lower())
            if normalized not in seen:
                seen.add(normalized)
                unique.append(req)
        return unique

    # ── Coverage validation ──────────────────────────────────

    @staticmethod
    def _validate_coverage(
        requirements: list[Requirement],
        total_indicator_count: int,
        warn_ratio: float = 0.6,
    ) -> None:
        """
        Compare extracted requirement count against obligation indicators.

        If extracted_count < warn_ratio * indicator_count, log a warning.
        This catches situations where the extraction pipeline missed
        obligations present in the raw text.
        """
        mandatory_count = sum(
            1 for r in requirements if r.type == RequirementType.MANDATORY
        )
        total_count = len(requirements)

        logger.info(
            f"[B1] Coverage: {total_count} requirements extracted "
            f"({mandatory_count} mandatory) vs "
            f"{total_indicator_count} obligation indicators in raw text"
        )

        if total_indicator_count > 0:
            coverage_ratio = total_count / total_indicator_count
            logger.info(f"[B1] Coverage ratio: {coverage_ratio:.2f}")

            if total_count < warn_ratio * total_indicator_count:
                logger.warning(
                    f"[B1] ⚠ LOW COVERAGE: Only {total_count} requirements "
                    f"extracted from {total_indicator_count} obligation "
                    f"indicators (ratio={coverage_ratio:.2f}, "
                    f"threshold={warn_ratio}). Review may be needed."
                )

    # ── Enum normalization helpers ───────────────────────────

    @staticmethod
    def _normalize_type(value: str) -> RequirementType:
        v = value.strip().upper()
        try:
            return RequirementType(v)
        except ValueError:
            return RequirementType.MANDATORY

    @staticmethod
    def _normalize_classification(value: str) -> RequirementClassification:
        v = value.strip().upper().replace("-", "_").replace(" ", "_")
        try:
            return RequirementClassification(v)
        except ValueError:
            return RequirementClassification.FUNCTIONAL

    @staticmethod
    def _normalize_category(value: str) -> RequirementCategory:
        v = value.strip().upper()
        try:
            return RequirementCategory(v)
        except ValueError:
            return RequirementCategory.TECHNICAL

    @staticmethod
    def _normalize_impact(value: str) -> ImpactLevel:
        v = value.strip().upper()
        try:
            return ImpactLevel(v)
        except ValueError:
            return ImpactLevel.MEDIUM


# ── Utility ──────────────────────────────────────────────────

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
