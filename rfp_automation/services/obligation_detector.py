"""
Obligation Detector — Rule-based candidate sentence detection (Layer 1).

Scans raw text for sentences containing obligation indicators (shall, must,
required to, etc.) and returns only those candidate sentences.  This runs
BEFORE the LLM so the LLM only classifies/structures — it does not discover.

Used by B1 Requirements Extraction Agent.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Obligation indicator patterns ────────────────────────
# Each tuple: (compiled regex, human label)
_OBLIGATION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bshall\b", re.IGNORECASE), "shall"),
    (re.compile(r"\bmust\b", re.IGNORECASE), "must"),
    (re.compile(r"\bshould\b", re.IGNORECASE), "should"),
    (re.compile(r"\brequired\s+to\b", re.IGNORECASE), "required to"),
    (re.compile(r"\bwill\s+be\s+required\b", re.IGNORECASE), "will be required"),
    (re.compile(r"\bresponsible\s+for\b", re.IGNORECASE), "responsible for"),
    (re.compile(r"\bdeliver\b", re.IGNORECASE), "deliver"),
    (re.compile(r"\bprovide\b", re.IGNORECASE), "provide"),
    (re.compile(r"\bensure\b", re.IGNORECASE), "ensure"),
    (re.compile(r"\bassume\s+responsibility\b", re.IGNORECASE), "assume responsibility"),
    (re.compile(r"\bcomply\s+with\b", re.IGNORECASE), "comply with"),
    (re.compile(r"\bobligated\s+to\b", re.IGNORECASE), "obligated to"),
    (re.compile(r"\bwill\s+provide\b", re.IGNORECASE), "will provide"),
    (re.compile(r"\bis\s+required\b", re.IGNORECASE), "is required"),
    (re.compile(r"\bneeds?\s+to\b", re.IGNORECASE), "needs to"),
    (re.compile(r"\bmandatory\b", re.IGNORECASE), "mandatory"),
    (re.compile(r"\bexpected\s+to\b", re.IGNORECASE), "expected to"),
    (re.compile(r"\bmust\s+not\b", re.IGNORECASE), "must not"),
    (re.compile(r"\bshall\s+not\b", re.IGNORECASE), "shall not"),
    (re.compile(r"\bshould\s+not\b", re.IGNORECASE), "should not"),
]

# ── Specification indicator patterns ───────────────────────
# Catch functional requirements, SLAs, and parameters that might lack a verb
_SPECIFICATION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b\d+(?:\.\d+)?\s*%\s*(?:uptime|availability)\b", re.IGNORECASE), "uptime %"),
    (re.compile(r"\b(?:SLA|service level agreement)s?\b", re.IGNORECASE), "SLA"),
    (re.compile(r"\b(?:RTO|RPO)\b", re.IGNORECASE), "RTO/RPO"),
    (re.compile(r"\b\d+\s*(?:ms|milliseconds|seconds|minutes|hours|days)\b", re.IGNORECASE), "time duration"),
    (re.compile(r"\bcapacity\s+of\b", re.IGNORECASE), "capacity"),
    (re.compile(r"\b(?:API|integration|webhook|SSO|SAML|OIDC)s?\b", re.IGNORECASE), "integration/auth"),
    (re.compile(r"\b(?:certified|certification|compliant|compliance|ISO|SOC|HIPAA|GDPR)\b", re.IGNORECASE), "compliance/cert"),
]

# Sentence-splitting regex: split on period/newline boundaries while
# keeping list items and numbered points as separate units.
_SENTENCE_SPLIT_RE = re.compile(
    r"(?<=[.!?])\s+(?=[A-Z])"  # standard sentence boundary
    r"|(?:\r?\n)+"             # newline boundaries
    r"|(?<=\n)\s*(?=[•●○◦▪▸\-\*])"  # bullet items
    r"|(?<=\n)\s*(?=\d+[.\):])"     # numbered items
)


@dataclass
class CandidateSentence:
    """A sentence flagged as potentially containing an obligation."""
    text: str
    indicators_found: list[str]
    sentence_index: int
    source_section: str = ""


class ObligationDetector:
    """
    Rule-based obligation candidate detection.

    Layer 1 of the two-layer extraction architecture:
      Layer 1 (this): find candidate sentences with obligation verbs
      Layer 2 (LLM):  structure/classify only those candidates
    """

    @staticmethod
    def split_sentences(text: str) -> list[str]:
        """
        Split text into sentences/items preserving list structure.

        Returns non-empty, stripped segments.
        """
        if not text or not text.strip():
            return []

        raw_parts = _SENTENCE_SPLIT_RE.split(text)
        sentences: list[str] = []
        for part in raw_parts:
            stripped = part.strip()
            if stripped:
                sentences.append(stripped)
        return sentences

    @staticmethod
    def detect_candidates(
        text: str,
        source_section: str = "",
    ) -> list[CandidateSentence]:
        """
        Scan text for sentences containing obligation indicators.

        Returns only sentences that contain at least one indicator,
        preserving their document order.
        """
        if not text or not text.strip():
            return []

        sentences = ObligationDetector.split_sentences(text)
        candidates: list[CandidateSentence] = []

        for idx, sentence in enumerate(sentences):
            matched_indicators: list[str] = []
            for pattern, label in _OBLIGATION_PATTERNS + _SPECIFICATION_PATTERNS:
                if pattern.search(sentence):
                    matched_indicators.append(label)

            if matched_indicators:
                candidates.append(CandidateSentence(
                    text=sentence,
                    indicators_found=matched_indicators,
                    sentence_index=idx,
                    source_section=source_section,
                ))

        logger.debug(
            f"[ObligationDetector] {len(candidates)}/{len(sentences)} "
            f"sentences flagged as candidates in section '{source_section}'"
        )
        return candidates

    @staticmethod
    def count_indicators(text: str) -> int:
        """
        Count total obligation indicator matches in raw text.

        Used for coverage validation:
          if extracted_count < threshold * indicator_count → warning.
        """
        if not text:
            return 0

        count = 0
        for pattern, _label in _OBLIGATION_PATTERNS + _SPECIFICATION_PATTERNS:
            count += len(pattern.findall(text))
        return count
