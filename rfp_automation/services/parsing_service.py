"""
Parsing Service — structured block extraction from PDF documents.

Extracts text preserving:
  • Headings (detected via font-size / bold)
  • Paragraphs, bullet lists, numbered sections
  • Line breaks, number formatting, units (Mbps, %, INR, ms, etc.)
  • Page numbers per block

Does NOT:
  • Summarize or interpret content
  • Parse table cells (returns mock placeholder)
  • Merge content across headings
  • Deduplicate blocks
  • Call any LLM
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Regex patterns for metadata extraction ───────────────

_RFP_NUMBER_RE = re.compile(
    r"(?:RFP\s*(?:Number|No\.?|#|Ref(?:erence)?)?[\s:]*)(RFP[-\s]?\S+)",
    re.IGNORECASE,
)
_ORGANIZATION_RE = re.compile(
    r"(?:Issuing\s+Organization|Issued\s+by|Company|Organisation)[\s:]+(.+)",
    re.IGNORECASE,
)
_ISSUE_DATE_RE = re.compile(
    r"(?:Issue\s+Date|Date\s+of\s+Issue|Published|Release\s+Date)[\s:]+(.+)",
    re.IGNORECASE,
)
_DEADLINE_RE = re.compile(
    r"(?:Submission\s+Deadline|Due\s+Date|Closing\s+Date|Deadline)[\s:]+(.+)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(
    r"(?:Phone|Tel|Contact)[\s:]*([+\d][\d \t\-().]{7,})", re.IGNORECASE
)


class ParsingService:
    """
    Extract structured blocks from PDF documents.

    Primary interface for Stage 1 (Intake):
        blocks   = ParsingService.parse_pdf_blocks(path)
        metadata = ParsingService.extract_metadata(blocks)
        chunks   = ParsingService.prepare_chunks(blocks)
    """

    # ── Block extraction ─────────────────────────────────

    @staticmethod
    def parse_pdf_blocks(file_path: str) -> list[dict[str, Any]]:
        """
        Extract structured blocks from a PDF using PyMuPDF dict mode.

        Each block: {block_id, type, text, page_number}
        Types: "heading" | "paragraph" | "list" | "table_mock"
        """
        import fitz  # PyMuPDF

        doc = fitz.open(file_path)

        # ── First pass: determine body font size (most common) ──
        font_sizes: list[float] = []
        for page in doc:
            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:  # text blocks only
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if span.get("text", "").strip():
                            font_sizes.append(round(span.get("size", 0), 1))

        body_font_size = 0.0
        if font_sizes:
            body_font_size = Counter(font_sizes).most_common(1)[0][0]

        # ── Second pass: extract and classify blocks ─────
        blocks: list[dict[str, Any]] = []
        blk_counter = 0
        tbl_counter = 0

        for page_idx, page in enumerate(doc):
            page_number = page_idx + 1
            page_dict = page.get_text("dict")

            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:  # skip image blocks
                    continue

                # Gather text and font info from all spans
                line_texts: list[str] = []
                span_positions: list[list[float]] = []  # x-positions per line
                max_font_size = 0.0
                has_bold = False

                for line in block.get("lines", []):
                    parts: list[str] = []
                    x_positions: list[float] = []
                    for span in line.get("spans", []):
                        text = span.get("text", "")
                        if text.strip():
                            parts.append(text)
                            x_positions.append(round(span["bbox"][0], 1))
                            size = span.get("size", 0)
                            if size > max_font_size:
                                max_font_size = size
                            # Bit 4 (value 16) = bold in PyMuPDF flags
                            if span.get("flags", 0) & 16:
                                has_bold = True
                    if parts:
                        line_texts.append("".join(parts))
                        span_positions.append(x_positions)

                if not line_texts:
                    continue

                full_text = "\n".join(line_texts)

                # ── Table detection ──────────────────────
                if _is_tabular(span_positions, line_texts):
                    tbl_counter += 1
                    blocks.append({
                        "block_id": f"tbl-{tbl_counter:03d}",
                        "type": "table_mock",
                        "text": "[TABLE DETECTED — STRUCTURE TO BE IMPLEMENTED LATER]",
                        "page_number": page_number,
                    })
                    continue

                # ── Block classification ─────────────────
                block_type = _classify_block(
                    full_text, max_font_size, has_bold, body_font_size
                )

                blk_counter += 1
                blocks.append({
                    "block_id": f"blk-{blk_counter:03d}",
                    "type": block_type,
                    "text": full_text,
                    "page_number": page_number,
                })

        doc.close()
        logger.info(
            f"Extracted {len(blocks)} blocks from {Path(file_path).name} "
            f"({blk_counter} text, {tbl_counter} table mocks)"
        )
        return blocks

    # ── Metadata extraction ──────────────────────────────

    @staticmethod
    def extract_metadata(blocks: list[dict[str, Any]]) -> dict[str, str | None]:
        """
        Extract RFP metadata from blocks using regex.

        Returns dict with keys:
          rfp_number, organization, issue_date, deadline,
          contact_email, contact_phone

        Values are None when not found.
        """
        # Concatenate text blocks (skip table mocks)
        full_text = "\n".join(
            b["text"] for b in blocks if b["type"] != "table_mock"
        )

        metadata: dict[str, str | None] = {
            "rfp_number": None,
            "organization": None,
            "issue_date": None,
            "deadline": None,
            "contact_email": None,
            "contact_phone": None,
        }

        m = _RFP_NUMBER_RE.search(full_text)
        if m:
            metadata["rfp_number"] = m.group(1).strip()

        m = _ORGANIZATION_RE.search(full_text)
        if m:
            metadata["organization"] = m.group(1).strip()

        m = _ISSUE_DATE_RE.search(full_text)
        if m:
            metadata["issue_date"] = m.group(1).strip()

        m = _DEADLINE_RE.search(full_text)
        if m:
            metadata["deadline"] = m.group(1).strip()

        m = _EMAIL_RE.search(full_text)
        if m:
            metadata["contact_email"] = m.group(0).strip()

        m = _PHONE_RE.search(full_text)
        if m:
            metadata["contact_phone"] = m.group(1).strip()

        return metadata

    # ── Chunk preparation ────────────────────────────────

    @staticmethod
    def prepare_chunks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Convert parsed blocks into structured chunk objects.

        Each chunk:
          {chunk_id, content_type, section_hint, text, page_start, page_end}

        section_hint tracks the last detected heading.
        """
        chunks: list[dict[str, Any]] = []
        last_heading = "Untitled Section"

        for block in blocks:
            if block["type"] == "heading":
                last_heading = block["text"].strip()

            content_type = (
                "table_mock" if block["type"] == "table_mock" else "text"
            )
            text = (
                "[TABLE DETECTED]"
                if block["type"] == "table_mock"
                else block["text"]
            )

            chunks.append({
                "chunk_id": block["block_id"],
                "content_type": content_type,
                "section_hint": last_heading,
                "text": text,
                "page_start": block["page_number"],
                "page_end": block["page_number"],
            })

        return chunks

    # ── Legacy interface (backward compatibility) ────────

    @staticmethod
    def parse(file_path: str) -> str:
        """
        Parse a document and return raw concatenated text.
        Kept for backward compatibility with RFPVectorStore.
        """
        ext = Path(file_path).suffix.lower()
        if ext == ".pdf":
            blocks = ParsingService.parse_pdf_blocks(file_path)
            return "\n".join(b["text"] for b in blocks)
        elif ext == ".docx":
            return ParsingService._parse_docx(file_path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")

    @staticmethod
    def _parse_docx(file_path: str) -> str:
        """Extract text from DOCX using python-docx."""
        try:
            from docx import Document

            doc = Document(file_path)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            logger.warning("python-docx not installed — returning mock text")
            return f"[Mock DOCX text extracted from {file_path}]"

    @staticmethod
    def chunk_text(
        text: str,
        chunk_size: int = 1000,
        overlap: int = 200,
    ) -> list[str]:
        """
        Split text into overlapping chunks for embedding/retrieval.
        Kept for backward compatibility (used by RFPVectorStore).
        """
        if not text:
            return []

        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk.strip())
            start += chunk_size - overlap
        return chunks


# ── Private helpers ──────────────────────────────────────


def _classify_block(
    text: str,
    max_font_size: float,
    has_bold: bool,
    body_font_size: float,
) -> str:
    """Classify a text block as heading, list, or paragraph."""
    stripped = text.strip()
    lines = stripped.split("\n")

    # List detection: bullet or numbered pattern
    list_pattern = re.compile(
        r"^\s*(?:[•●○◦▪▸\-\*]|\d+[\.\):]|[a-z][\.\)]|[ivxlc]+[\.\)])\s",
        re.IGNORECASE | re.MULTILINE,
    )
    list_line_count = sum(1 for ln in lines if list_pattern.match(ln))
    if list_line_count > 0 and list_line_count >= len(lines) * 0.5:
        return "list"

    # Heading detection: larger font or bold AND short text
    is_larger = body_font_size > 0 and max_font_size >= body_font_size + 1.5
    is_short = len(stripped) < 200 and len(lines) <= 3

    if is_short and (is_larger or has_bold):
        return "heading"

    # Numbered section heading: "1. Title" or "1.2.3 Title" — short line
    if is_short and re.match(r"^\d+(\.\d+)*\.?\s+\S", stripped):
        return "heading"

    return "paragraph"


def _is_tabular(
    span_positions: list[list[float]], line_texts: list[str]
) -> bool:
    """
    Heuristic: detect if a block looks like a table.

    Checks:
      - At least 3 lines
      - Most lines have 3+ spans at distinct x-positions
      - OR lines have multi-space separated column patterns
    """
    if len(line_texts) < 3:
        return False

    # Method 1: multiple distinct x-offsets per line
    multi_col_lines = 0
    for positions in span_positions:
        if len(positions) >= 3:
            distinct = _count_distinct(positions, tolerance=5.0)
            if distinct >= 3:
                multi_col_lines += 1

    if multi_col_lines >= len(line_texts) * 0.6:
        return True

    # Method 2: multi-space separated columns in text
    col_pattern = re.compile(r"\S+\s{3,}\S+\s{3,}\S+")
    col_lines = sum(1 for t in line_texts if col_pattern.search(t))
    if col_lines >= len(line_texts) * 0.6 and col_lines >= 3:
        return True

    return False


def _count_distinct(values: list[float], tolerance: float) -> int:
    """Count distinct values within a tolerance."""
    if not values:
        return 0
    sorted_vals = sorted(values)
    distinct = 1
    last = sorted_vals[0]
    for v in sorted_vals[1:]:
        if v - last > tolerance:
            distinct += 1
            last = v
    return distinct
