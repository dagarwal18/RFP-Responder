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
    # Evaluation criteria patterns
    (re.compile(r"\b(?:will be evaluated|will be scored|evaluated favorably)\b", re.IGNORECASE), "evaluation"),
    (re.compile(r"\b(?:weighted|weighting|scoring criteria|assessment criteria)\b", re.IGNORECASE), "scoring"),
    (re.compile(r"\b(?:selection criteria|pass[/-]fail|minimum score)\b", re.IGNORECASE), "selection"),
]

# Sentence-splitting regex inside blocks: split on period/newline boundaries.
# Newlines are handled structurally first, so we only need to split inline sentence boundaries.
_SENTENCE_SPLIT_RE = re.compile(
    r"(?<=[.!?])\s+(?=[A-Z0-9])"  # standard sentence boundary
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
        """
        if not text or not text.strip():
            return []

        return ObligationDetector._group_structural_blocks(text)

    @staticmethod
    def _group_structural_blocks(text: str) -> list[str]:
        """
        Intelligently group parent phrases with bulleted/numbered children.

        Strategy:
          - Bullet children (-, •, *, etc.) → merge into parent as sub-clauses
          - Numbered children (1., 2., 3.) → each becomes an independent block
            with the parent sentence as a context prefix

        This distinction is universal across documents: numbered items are
        independent specifications, bullet items are sub-clauses of one statement.
        """
        lines = text.split('\n')
        blocks: list[str] = []

        list_item_re = re.compile(r"^\s*(?:[•●○◦▪▸\-\*]|\d+[.\):])\s*(.*)", re.IGNORECASE)
        numbered_re = re.compile(r"^\s*\d+[.\):]")
        parent_re = re.compile(
            r"(?:"
            r"[:]$"
            r"|\b(?:following|below|these)\s*[:]?\s*$"
            r"|,\s*$"
            r"|\b(?:including|such as)\s*[:]?\s*$"
            r")", re.IGNORECASE
        )

        def get_indent(s: str) -> int:
            return len(s) - len(s.lstrip(' \t'))

        i = 0
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                i += 1
                continue

            indent_i = get_indent(line)
            stripped_line = line.strip()

            children: list[str] = []
            children_raw: list[str] = []  # track raw lines to detect type
            j = i + 1

            is_parent = bool(parent_re.search(stripped_line))
            is_list_i = bool(list_item_re.match(line))

            while j < len(lines):
                next_line = lines[j]
                if not next_line.strip():
                    j += 1
                    continue

                indent_j = get_indent(next_line)
                is_list_j = bool(list_item_re.match(next_line))

                is_child = False
                if is_list_j:
                    if is_parent:
                        is_child = True
                    elif indent_j > indent_i:
                        is_child = True
                    elif not is_list_i:
                        is_child = True

                if is_child:
                    child_match = list_item_re.match(next_line)
                    child_content = child_match.group(1).strip() if child_match else next_line.strip()
                    if child_content:
                        children.append(child_content)
                    else:
                        children.append(next_line.strip())
                    children_raw.append(next_line)
                    j += 1
                else:
                    break

            if children:
                # Determine if children are numbered or bulleted
                numbered_count = sum(1 for raw in children_raw if numbered_re.match(raw.strip()))
                is_numbered_list = numbered_count > len(children_raw) / 2

                # Build clean parent prefix (strip trailing colon/comma)
                parent_prefix = stripped_line.rstrip(":,").strip()

                if is_numbered_list:
                    # Numbered: each child is an independent requirement
                    for child in children:
                        blocks.append(f"{parent_prefix}: {child}")
                    logger.debug(
                        f"Split numbered list into {len(children)} independent blocks"
                    )
                else:
                    # Bulleted: merge into parent as sub-clauses
                    merged = stripped_line
                    if not merged.endswith(" ") and not merged.endswith(":"):
                        merged += " "
                    elif merged.endswith(":"):
                        merged += " "
                    merged += ", ".join(children)
                    blocks.append(merged)
                    logger.debug(
                        f"Merged bullet list with {len(children)} children into parent"
                    )

                i = j
                continue

            blocks.append(stripped_line)
            i += 1

        # Filter out fragments: naked parent headers and truncated sentences.
        # Catches: trailing colons, "the following X", trailing commas,
        # and sentences ending with dangling prepositions/conjunctions/articles.
        _FRAGMENT_RE = re.compile(
            r"(?:"
            r":\s*$"                                                # ends with colon
            r"|\b(?:the following|as follows|these requirements|listed below)\b[^.!?]*$"  # "the following X" anywhere near end
            r"|,\s*$"                                               # trailing comma
            r"|\b(?:with|and|or|the|a|an|to|for|of|in|by|from|must be|will be|shall be)\s*$"  # dangling preposition/conjunction
            r")", re.IGNORECASE
        )
        blocks = [b for b in blocks if not _FRAGMENT_RE.search(b)]

        sentences: list[str] = []
        for block in blocks:
            parts = _SENTENCE_SPLIT_RE.split(block)
            for part in parts:
                p = part.strip()
                if p:
                    sentences.append(p)

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
