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

from rfp_automation.utils.text import truncate_at_boundary

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


class ExtractionBatchError(Exception):
    """Raised when an LLM batch fails unrecoverably and must be retried with smaller context."""
    pass


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

        # ── 2. Group chunks by section ────────────
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

            # Density Sanity Check
            candidates_text_len = sum(len(c.text) for c in candidates)
            density = candidates_text_len / len(raw_text) if len(raw_text) > 0 else 1.0
            if density < settings.extraction_min_candidate_density:
                logger.warning(
                    f"[B1] Candidate density {density:.2%} is suspiciously low. "
                    f"Falling back to full text extraction for section '{section_name}'."
                )
                fallback_sentences = ObligationDetector.split_sentences(raw_text)
                candidates = [
                    CandidateSentence(
                        text=fs,
                        indicators_found=[],
                        sentence_index=fi,
                        source_section=section_name
                    ) for fi, fs in enumerate(fallback_sentences)
                ]

            # Layer 2: LLM structuring/classification (Batched Extraction)
            MAX_CONTEXT_LEN = 8000
            section_context = truncate_at_boundary(raw_text, MAX_CONTEXT_LEN)
            
            output_budget_tokens = int(settings.llm_max_tokens * settings.extraction_min_output_headroom_ratio)
            input_budget_tokens = settings.llm_max_tokens - output_budget_tokens
            overhead_tokens = len(section_context) // 4 + 400
            
            # Start with maximum safe candidate tokens
            available_candidate_tokens = max(500, input_budget_tokens - overhead_tokens)
            max_candidate_chars = available_candidate_tokens * 4
            
            before_section_reqs = len(all_requirements)
            
            i = 0
            while i < len(candidates):
                current_batch_text = ""
                batch_candidates_count = 0
                
                # Fill batch up to limit
                for j in range(i, len(candidates)):
                    cand_str = f"[{candidates[j].sentence_index}] {candidates[j].text}\n"
                    if current_batch_text and len(current_batch_text) + len(cand_str) > max_candidate_chars:
                        break
                    current_batch_text += cand_str
                    batch_candidates_count += 1
                
                start_id = f"REQ-{global_id_counter:04d}"
                prompt = template.format(
                    section_title=section_name,
                    candidate_text=current_batch_text,
                    section_context=section_context,
                    start_id=start_id,
                )
                
                try:
                    raw_response = llm_deterministic_call(prompt)
                    logger.debug(f"[B1] LLM batch response: {len(raw_response)} chars")
                    parsed = self._parse_requirements_json(raw_response, section_name, global_id_counter)
                    for req in parsed:
                        req.source_chunk_indices = chunk_indices
                    all_requirements.extend(parsed)
                    global_id_counter += len(parsed)
                    i += batch_candidates_count # move forward
                    
                except ExtractionBatchError as exc:
                    logger.error(f"[B1] Extraction batch failed: {exc}. Shrinking batch size.")
                    if batch_candidates_count == 1:
                        logger.error(f"[B1] Impossible to shrink single candidate. Skipping candidate: {candidates[i].text}")
                        i += 1
                    else:
                        # Shrink max_candidate_chars to half and retry (don't increment i)
                        max_candidate_chars = max(200, max_candidate_chars // 2)
                        
                except Exception as exc:
                    logger.error(f"[B1] LLM batch call failed unexpectedly: {exc}")
                    i += batch_candidates_count

            extracted_for_section = len(all_requirements) - before_section_reqs
            logger.info(
                f"[B1] Extracted {extracted_for_section} requirements from "
                f"'{section_name}'"
            )

        # ── 5. Deduplication (embedding-based + text fallback) ─
        before_dedup = len(all_requirements)
        all_requirements = self._deduplicate(
            all_requirements,
            threshold=settings.extraction_dedup_similarity_threshold,
        )
        logger.info(
            f"[B1] Deduplicated: {before_dedup} → {len(all_requirements)} requirements"
        )

        # ── 5b. Merge badly-split fragments ──────────────────
        before_merge = len(all_requirements)
        all_requirements = self._merge_fragments(all_requirements)
        if before_merge != len(all_requirements):
            logger.info(
                f"[B1] Fragment merging: {before_merge} → {len(all_requirements)} requirements"
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
        eval_count = sum(
            1 for r in all_requirements
            if r.classification == RequirementClassification.EVALUATION_CRITERIA
        )
        logger.info(
            f"[B1] Extraction complete: {len(all_requirements)} requirements "
            f"(Functional: {func_count}, Non-Functional: {nonfunc_count}, "
            f"Evaluation: {eval_count})"
        )
        return state

    # ── Section grouping ─────────────────────────────────────

    @staticmethod
    def _group_by_section(
        chunks: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Group chunks by their section boundary (section_hint/breadcrumb).
        This preserves semantic coherence for extraction context.
        """
        groups: dict[str, list[dict[str, Any]]] = {}
        for chunk in chunks:
            section_name = chunk.get("section_hint") or "Untitled Section"
            if section_name not in groups:
                groups[section_name] = []
            groups[section_name].append(chunk)
        return groups

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

        # ── Robust JSON array extraction ──────────────────────
        # The LLM may emit chain-of-thought reasoning before the JSON.
        # Naive text.find("[") fails because reasoning often contains
        # square brackets (e.g. "[Section: ...]", "[1]", "[B1]").
        # Strategy: try each '[' position until json.loads succeeds.
        data = None
        search_start = 0
        while True:
            bracket_start = text.find("[", search_start)
            if bracket_start == -1:
                break

            # Find matching ']' from the end
            bracket_end = text.rfind("]")
            if bracket_end != -1 and bracket_end > bracket_start:
                candidate = text[bracket_start:bracket_end + 1]
            else:
                # Truncated output: '[' found but no closing ']'
                candidate = text[bracket_start:]

            try:
                data = json.loads(candidate)
                if isinstance(data, list):
                    break  # Success — found valid JSON array
                data = None  # Not an array, keep searching
            except json.JSONDecodeError:
                pass  # This '[' wasn't the JSON start, try the next one

            search_start = bracket_start + 1

        # If no clean parse succeeded, attempt structured repair
        if data is None:
            # Find the last '[' that precedes a '{' (likely JSON array of objects)
            json_array_match = re.search(r'\[\s*\{', text)
            if json_array_match:
                fragment = text[json_array_match.start():]
                last_brace = fragment.rfind("}")
                if last_brace != -1:
                    repaired = fragment[:last_brace + 1] + "]"
                    try:
                        data = json.loads(repaired)
                        logger.warning(f"[B1] Recovered partial JSON array with {len(data)} items")
                    except json.JSONDecodeError as exc_inner:
                        logger.error(f"[B1] FATAL JSON PARSE FAIL after repair: {fragment[:300]}")
                        raise ExtractionBatchError("Unrecoverable JSON syntax") from exc_inner
                else:
                    logger.error(f"[B1] FATAL JSON PARSE FAIL: No objects to recover")
                    raise ExtractionBatchError("Unrecoverable JSON syntax")
            else:
                # No JSON array found at all
                if text.strip() == "[]" or "[]" in text:
                    return []
                logger.warning("[B1] No JSON array found in LLM response")
                return []

        if not isinstance(data, list):
            logger.warning("[B1] LLM response is not a JSON array")
            raise ExtractionBatchError("Expected JSON array")

        # Build Requirement objects
        requirements: list[Requirement] = []

        # Pattern to detect truncated/fragment requirement text
        _TRUNCATION_RE = re.compile(
            r"\b(?:with|and|or|the|a|an|to|for|of|in|by|from|"
            r"must be|will be|shall be|must|will|shall|"
            r"the following\b.*)\s*$",
            re.IGNORECASE
        )

        for i, item in enumerate(data):
            try:
                req_text = item.get("text", "").strip()

                # Skip empty text
                if not req_text:
                    continue

                # Skip truncated fragments
                if _TRUNCATION_RE.search(req_text):
                    logger.debug(
                        f"[B1] Skipping truncated fragment: '{req_text[:80]}'"
                    )
                    continue

                # Skip very short text (< 15 chars = not a real requirement)
                if len(req_text) < 15:
                    logger.debug(f"[B1] Skipping too-short text: '{req_text}'")
                    continue

                req = Requirement(
                    requirement_id=item.get(
                        "requirement_id", f"REQ-{start_id + i:04d}"
                    ),
                    text=req_text,
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
        embeddings = embedder.embed(texts)

        if not embeddings or len(embeddings) != len(requirements):
            raise ValueError("Embedding batch size mismatch")

        # Mark duplicates using 3-tier similarity (O(n²) but n is typically < 500)
        is_duplicate = [False] * len(requirements)

        # Regex to strip everything but alphanumeric for strict structural diffing
        norm_re = re.compile(r"[^\w\s]")

        for i in range(len(requirements)):
            if is_duplicate[i]:
                continue
            for j in range(i + 1, len(requirements)):
                if is_duplicate[j]:
                    continue

                sim = _cosine_similarity(embeddings[i], embeddings[j])

                # Tier 1: Exact duplicate (sim ≥ 0.99 + identical normalized text)
                if sim >= 0.99:
                    text_i = norm_re.sub("", requirements[i].text.strip().lower())
                    text_j = norm_re.sub("", requirements[j].text.strip().lower())
                    if text_i == text_j:
                        is_duplicate[j] = True
                        logger.debug(
                            f"[B1] Tier 1 exact duplicate (sim={sim:.3f}): "
                            f"'{requirements[j].text[:60]}'"
                        )
                        continue

                # Tier 2: Same-section semantic duplicate (sim ≥ 0.92)
                if sim >= 0.92 and requirements[i].source_section == requirements[j].source_section:
                    # Keep the longer (more complete) version
                    if len(requirements[j].text) > len(requirements[i].text):
                        is_duplicate[i] = True
                        logger.debug(
                            f"[B1] Tier 2 same-section dedup (sim={sim:.3f}): "
                            f"keeping longer '{requirements[j].text[:60]}'"
                        )
                        break  # i is now duplicate, skip rest of j loop
                    else:
                        is_duplicate[j] = True
                        logger.debug(
                            f"[B1] Tier 2 same-section dedup (sim={sim:.3f}): "
                            f"removing '{requirements[j].text[:60]}'"
                        )
                    continue

                # Tier 3: Cross-section keyword overlap (sim ≥ 0.95 + 60% keyword overlap)
                if sim >= 0.95:
                    kw_i = set(k.lower() for k in requirements[i].keywords)
                    kw_j = set(k.lower() for k in requirements[j].keywords)
                    if kw_i and kw_j:
                        overlap = len(kw_i & kw_j) / max(len(kw_i), len(kw_j))
                        if overlap >= 0.6:
                            if len(requirements[j].text) > len(requirements[i].text):
                                is_duplicate[i] = True
                                logger.debug(
                                    f"[B1] Tier 3 cross-section dedup (sim={sim:.3f}, overlap={overlap:.0%}): "
                                    f"keeping '{requirements[j].text[:60]}'"
                                )
                                break
                            else:
                                is_duplicate[j] = True
                                logger.debug(
                                    f"[B1] Tier 3 cross-section dedup (sim={sim:.3f}, overlap={overlap:.0%}): "
                                    f"removing '{requirements[j].text[:60]}'"
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

    # ── Fragment merging ─────────────────────────────────────

    @staticmethod
    def _merge_fragments(requirements: list[Requirement]) -> list[Requirement]:
        """
        Merge sequential requirements that were split at bad boundaries.

        Detects pairs where requirement N ends without terminal punctuation
        and requirement N+1 starts with a comparator, lowercase letter, or
        continuation pattern — indicating they were one sentence split poorly.
        """
        if len(requirements) < 2:
            return requirements

        # Pattern: starts with <, >, ≤, ≥, or lowercase letter
        _CONTINUATION_START = re.compile(r"^[<>≤≥a-z]")
        # Terminal punctuation that indicates a complete sentence
        _TERMINAL_PUNCT = re.compile(r"[.!?\)\]]\s*$")

        merged: list[Requirement] = []
        skip_next = False

        for i in range(len(requirements)):
            if skip_next:
                skip_next = False
                continue

            req = requirements[i]

            # Check if this req should merge with the next one
            if i + 1 < len(requirements):
                next_req = requirements[i + 1]

                # Only merge if same source section
                if req.source_section != next_req.source_section:
                    merged.append(req)
                    continue

                text_ends_incomplete = not _TERMINAL_PUNCT.search(req.text)
                next_starts_continuation = _CONTINUATION_START.match(
                    next_req.text.strip()
                )

                if text_ends_incomplete and next_starts_continuation:
                    # Merge: combine text with a space
                    combined_text = req.text.rstrip() + " " + next_req.text.lstrip()
                    combined_keywords = list(
                        dict.fromkeys(req.keywords + next_req.keywords)
                    )
                    combined_chunks = list(
                        dict.fromkeys(
                            req.source_chunk_indices + next_req.source_chunk_indices
                        )
                    )

                    merged_req = Requirement(
                        requirement_id=req.requirement_id,
                        text=combined_text,
                        type=req.type,
                        classification=req.classification,
                        category=req.category,
                        impact=max(req.impact, next_req.impact, key=lambda x: x.value),
                        source_section=req.source_section,
                        keywords=combined_keywords,
                        source_chunk_indices=combined_chunks,
                    )
                    merged.append(merged_req)
                    skip_next = True

                    logger.warning(
                        f"[B1] Merged fragment pair: "
                        f"'{req.text[:50]}' + '{next_req.text[:50]}' → "
                        f"'{combined_text[:80]}'"
                    )
                    continue

            merged.append(req)

        return merged

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
