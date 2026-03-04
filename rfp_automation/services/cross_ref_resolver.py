"""
Cross-Reference Resolver — detect and resolve section references within chunks.

Post-processing pass that runs after semantic chunking but before MCP storage.
Scans for patterns like:
  - "see Section 5", "as specified in Section 3.2"
  - "refer to Appendix A/B/C"
  - "per Table 7", "see Table 3"
  - "see Figure 4"

When a reference is found, the referenced content is injected inline so
that each chunk is self-contained for retrieval.

Does NOT: call any LLM. Pure regex + text processing.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Maximum characters to inject per cross-reference
_MAX_INJECT_CHARS = 2000

# ── Cross-reference patterns ────────────────────────────

# "see Section 5", "as specified in Section 3.2.1", "per Section 5"
_SECTION_REF_RE = re.compile(
    r"(?:see|as\s+specified\s+in|per\s+the?|refer\s+to|in\s+accordance\s+with|"
    r"described\s+in|defined\s+in|outlined\s+in|detailed\s+in)"
    r"\s+Section\s+(\d+(?:\.\d+)*)",
    re.IGNORECASE,
)

# "see Appendix A", "refer to Appendix B"
_APPENDIX_REF_RE = re.compile(
    r"(?:see|refer\s+to|as\s+per|in)\s+Appendix\s+([A-Z])",
    re.IGNORECASE,
)

# "see Table 7", "per Table 3", "in Table 11"
_TABLE_REF_RE = re.compile(
    r"(?:see|per|in|refer\s+to)\s+Table\s+(\d+)",
    re.IGNORECASE,
)

# "see Figure 4", "refer to Figure 2"
_FIGURE_REF_RE = re.compile(
    r"(?:see|refer\s+to|in)\s+Figure\s+(\d+)",
    re.IGNORECASE,
)


class CrossRefResolver:
    """
    Detect and resolve cross-references within document chunks.

    Builds an index of sections, appendices, tables, and figures from
    chunk metadata + content, then injects referenced text inline.
    """

    def resolve(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Scan chunks for cross-references and inject referenced content inline.

        Returns a new list of enriched chunks (originals are not mutated).
        """
        if not chunks:
            return chunks

        # Build lookup indices
        section_index = self._build_section_index(chunks)
        table_index = self._build_table_index(chunks)

        logger.debug(
            f"[CrossRef] Built indices: {len(section_index)} sections, "
            f"{len(table_index)} tables"
        )

        enriched: list[dict[str, Any]] = []
        total_injections = 0

        for chunk in chunks:
            text = chunk.get("text", "")
            refs = self._find_references(text)

            if not refs:
                enriched.append(chunk)
                continue

            injection_parts: list[str] = []
            seen_refs: set[str] = set()

            for ref_type, ref_key in refs:
                # Avoid duplicating injections
                dedup_key = f"{ref_type}:{ref_key}"
                if dedup_key in seen_refs:
                    continue
                seen_refs.add(dedup_key)

                content = self._lookup_reference(
                    ref_type, ref_key, section_index, table_index
                )
                if content:
                    # Truncate to max inject size
                    truncated = content[:_MAX_INJECT_CHARS]
                    if len(content) > _MAX_INJECT_CHARS:
                        truncated += " [...]"

                    label = f"{ref_type} {ref_key}"
                    injection_parts.append(f"[Referenced {label}]: {truncated}")
                    total_injections += 1

            if injection_parts:
                enriched_text = text + "\n\n" + "\n\n".join(injection_parts)
                enriched.append({**chunk, "text": enriched_text})
            else:
                enriched.append(chunk)

        logger.info(
            f"[CrossRef] Resolved {total_injections} cross-references "
            f"across {len(chunks)} chunks"
        )
        return enriched

    # ── Index builders ───────────────────────────────────

    def _build_section_index(
        self, chunks: list[dict[str, Any]]
    ) -> dict[str, str]:
        """
        Build mapping:  section_key → full text content.

        Keys are normalized section numbers: "5", "3.2", "3.2.1"
        Also maps appendix letters: "appendix_a", "appendix_b"
        """
        index: dict[str, str] = {}

        # Pattern to detect section numbers in headings / section_hints
        section_num_re = re.compile(r"^(\d+(?:\.\d+)*)")

        for chunk in chunks:
            text = chunk.get("text", "")
            hint = chunk.get("section_hint", "")

            # Try to extract section number from section_hint
            hint_parts = hint.split(" > ")
            for part in hint_parts:
                m = section_num_re.match(part.strip())
                if m:
                    sec_num = m.group(1)
                    # Store the full chunk text under this section number
                    if sec_num not in index:
                        index[sec_num] = text
                    else:
                        # Append if multiple chunks share the same section
                        index[sec_num] += "\n\n" + text

            # Also try extracting from the text itself (first line)
            first_line = text.split("\n")[0].strip() if text else ""
            m = section_num_re.match(first_line)
            if m:
                sec_num = m.group(1)
                if sec_num not in index:
                    index[sec_num] = text

            # Detect appendix references
            appendix_re = re.compile(
                r"(?:^|\n)\s*Appendix\s+([A-Z])\b", re.IGNORECASE
            )
            for am in appendix_re.finditer(text):
                key = f"appendix_{am.group(1).upper()}"
                if key not in index:
                    index[key] = text

        return index

    def _build_table_index(
        self, chunks: list[dict[str, Any]]
    ) -> dict[str, str]:
        """
        Build mapping:  table_key → table text content.

        Keys: "table_1", "table_7", "figure_4", etc.
        """
        index: dict[str, str] = {}

        table_num_re = re.compile(r"Table\s+(\d+)", re.IGNORECASE)
        figure_num_re = re.compile(r"Figure\s+(\d+)", re.IGNORECASE)

        for chunk in chunks:
            text = chunk.get("text", "")
            content_type = chunk.get("content_type", "")

            # Index table chunks
            if content_type == "table":
                for m in table_num_re.finditer(text):
                    key = f"table_{m.group(1)}"
                    if key not in index:
                        index[key] = text

            # Also check section_hint for table/figure references
            hint = chunk.get("section_hint", "")
            for m in table_num_re.finditer(hint):
                key = f"table_{m.group(1)}"
                if key not in index:
                    index[key] = text

            for m in figure_num_re.finditer(hint + "\n" + text[:200]):
                key = f"figure_{m.group(1)}"
                if key not in index:
                    index[key] = text

        return index

    # ── Reference detection ──────────────────────────────

    @staticmethod
    def _find_references(text: str) -> list[tuple[str, str]]:
        """
        Find cross-reference patterns in text.

        Returns list of (ref_type, ref_key) tuples:
          ("Section", "5"), ("Appendix", "A"), ("Table", "7"), ("Figure", "4")
        """
        refs: list[tuple[str, str]] = []

        for m in _SECTION_REF_RE.finditer(text):
            refs.append(("Section", m.group(1)))

        for m in _APPENDIX_REF_RE.finditer(text):
            refs.append(("Appendix", m.group(1).upper()))

        for m in _TABLE_REF_RE.finditer(text):
            refs.append(("Table", m.group(1)))

        for m in _FIGURE_REF_RE.finditer(text):
            refs.append(("Figure", m.group(1)))

        return refs

    # ── Reference lookup ─────────────────────────────────

    @staticmethod
    def _lookup_reference(
        ref_type: str,
        ref_key: str,
        section_index: dict[str, str],
        table_index: dict[str, str],
    ) -> str | None:
        """Look up a reference in the indices. Returns content or None."""
        if ref_type == "Section":
            return section_index.get(ref_key)

        if ref_type == "Appendix":
            return section_index.get(f"appendix_{ref_key}")

        if ref_type == "Table":
            return table_index.get(f"table_{ref_key}")

        if ref_type == "Figure":
            return table_index.get(f"figure_{ref_key}")

        return None
