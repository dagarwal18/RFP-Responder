"""
Parsing Service — structured block extraction from PDF documents.

Extracts text preserving:
  • Headings (detected via font-size / bold)
  • Paragraphs, bullet lists, numbered sections
  • Line breaks, number formatting, units (Mbps, %, INR, ms, etc.)
  • Page numbers per block
  • Table content (extracted via PyMuPDF table API with text fallback)

Does NOT:
  • Summarize or interpret content
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
_CLIENT_NAME_RE = re.compile(
    r"(?:Prepared\s+for|Client\s+Name|Client|Proposal\s+for|Submitted\s+to)[\s:]+(.{3,60}?)(?:\s*[-\u2013\u2014\n]|$)",
    re.IGNORECASE,
)
_RFP_FOR_RE = re.compile(
    r"Request\s+for\s+Proposal.*?(?:for|from)\s+(.+?)(?:\s*[-–—]|\n|$)",
    re.IGNORECASE,
)
_HEADER_ORG_RE = re.compile(
    r"(?:^|\n)\s*(.{3,50}?)\s*\|\s*(?:RFP|REQUEST\s+FOR\s+PROPOSAL)",
    re.IGNORECASE,
)

# Names that are obviously section headings, not client names
_REJECTED_CLIENT_NAMES = {
    "background", "introduction", "overview", "scope", "purpose",
    "objective", "objectives", "summary", "context", "general",
    "requirements", "technical", "specifications", "submission",
    "instructions", "guidelines", "terms", "conditions",
    "evaluation", "criteria", "annexure", "appendix",
}
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
        diag_counter = 0
        extracted_tables_debug = []  # To store structured table extraction output for debugging

        # ── VLM setup (if enabled) ───────────────────────
        vlm_enabled = False
        vision_svc = None
        try:
            from rfp_automation.config import get_settings
            vlm_enabled = get_settings().vlm_enabled
            if vlm_enabled:
                from rfp_automation.services.vision_service import VisionService
                vision_svc = VisionService()
        except Exception as e:
            logger.warning(f"VLM initialization failed, using heuristic fallback: {e}")
            vlm_enabled = False

        vlm_processed_pages: dict[int, list[dict[str, Any]]] = {}  # page_num → VLM tables

        for page_idx, page in enumerate(doc):
            page_number = page_idx + 1
            page_dict = page.get_text("dict")

            for block in page_dict.get("blocks", []):
                # ── Image blocks → diagram description ───
                if block.get("type") == 1 and vlm_enabled and vision_svc:
                    try:
                        # Render image block region
                        import fitz as _fitz_inner
                        bbox = block.get("bbox", block.get("ext", None))
                        if bbox:
                            clip = _fitz_inner.Rect(bbox)
                            pix = page.get_pixmap(clip=clip, dpi=150)
                        else:
                            pix = page.get_pixmap(dpi=150)
                        img_bytes = pix.tobytes("png")
                        desc = vision_svc.extract_diagram_description(
                            img_bytes, page_number
                        )
                        if desc:
                            diag_counter += 1
                            blocks.append({
                                "block_id": f"diag-{diag_counter:03d}",
                                "type": "diagram",
                                "text": desc,
                                "page_number": page_number,
                            })
                    except Exception as e:
                        logger.debug(
                            f"Diagram extraction failed on page {page_number}: {e}"
                        )
                    continue

                if block.get("type") != 0:  # skip non-text blocks
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
                # Try DETR + VLM first, fall back to heuristic
                if vlm_enabled and vision_svc and page_number not in vlm_processed_pages:
                    try:
                        pix = page.get_pixmap(dpi=150)
                        page_img_bytes = pix.tobytes("png")
                        vlm_tables = vision_svc.extract_tables_from_page(
                            page_img_bytes, page_number
                        )
                        vlm_processed_pages[page_number] = vlm_tables
                    except Exception as e:
                        logger.warning(
                            f"VLM table extraction failed on page {page_number}: {e}"
                        )
                        vlm_processed_pages[page_number] = []

                # Check if this block is a table
                if _is_tabular(span_positions, line_texts):
                    tbl_counter += 1

                    # Track table extraction variants for debugging and verification
                    table_debug_info = {
                        "page_number": page_number,
                        "table_id": f"tbl-{tbl_counter:03d}",
                        "heuristic_extraction": _extract_table_text(line_texts),
                        "vlm_extraction": None,
                        "final_extraction_used": "heuristic",
                        "table_type": "unknown",
                    }

                    # Use VLM-extracted tables if available for this page
                    page_vlm_tables = vlm_processed_pages.get(page_number, [])
                    table_type = "unknown"
                    if page_vlm_tables:
                        # Take the first unused VLM table for this page
                        from rfp_automation.services.vision_service import VisionService as _VS
                        vlm_tbl = page_vlm_tables.pop(0)
                        table_debug_info["vlm_extraction"] = vlm_tbl
                        table_type = vlm_tbl.get("table_type", "unknown")
                        table_debug_info["table_type"] = table_type
                        table_text = _VS.format_table_as_text(vlm_tbl)
                        if not table_text:
                            # VLM returned empty → fallback to heuristic
                            table_text = table_debug_info["heuristic_extraction"]
                        else:
                            table_debug_info["final_extraction_used"] = "vlm"
                    else:
                        # No VLM tables → use heuristic extraction
                        table_text = table_debug_info["heuristic_extraction"]

                    extracted_tables_debug.append(table_debug_info)

                    logger.info(
                        f"[TABLE-TRACE][PARSE] Block created: "
                        f"id=tbl-{tbl_counter:03d}, page={page_number}, "
                        f"table_type={table_type}, "
                        f"source={table_debug_info['final_extraction_used']}, "
                        f"text_len={len(table_text)}, "
                        f"preview='{table_text[:80]}...'"
                    )

                    blocks.append({
                        "block_id": f"tbl-{tbl_counter:03d}",
                        "type": "table",
                        "text": table_text,
                        "page_number": page_number,
                        "table_type": table_type,
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
            f"({blk_counter} text, {tbl_counter} tables, {diag_counter} diagrams)"
        )
        
        # Collect any leftover VLM tables that heuristic didn't match
        # These are tables DETR + VLM detected but no heuristic block matched.
        # Inject them as proper blocks so they aren't lost.
        for page_num, vlm_tables in vlm_processed_pages.items():
            for v_tbl in vlm_tables:
                tbl_counter += 1
                from rfp_automation.services.vision_service import VisionService as _VS
                table_text = _VS.format_table_as_text(v_tbl)
                table_type = v_tbl.get("table_type", "unknown")

                if table_text:
                    logger.info(
                        f"[TABLE-TRACE][PARSE] Injecting unmatched VLM table as block: "
                        f"id=tbl-{tbl_counter:03d}, page={page_num}, "
                        f"table_type={table_type}, "
                        f"headers={v_tbl.get('headers', [])}, "
                        f"rows={len(v_tbl.get('rows', []))}"
                    )
                    blocks.append({
                        "block_id": f"tbl-{tbl_counter:03d}",
                        "type": "table",
                        "text": table_text,
                        "page_number": page_num,
                        "table_type": table_type,
                    })

                extracted_tables_debug.append({
                    "page_number": page_num,
                    "table_id": f"tbl-{tbl_counter:03d}",
                    "heuristic_extraction": None,
                    "vlm_extraction": v_tbl,
                    "final_extraction_used": "vlm_only",
                    "table_type": table_type,
                })
        
        # Write extracted tables structured output for verification
        if extracted_tables_debug:
            import json
            pdf_path = Path(file_path)
            json_filename = f"{pdf_path.stem}_tables.json"
            json_filepath = pdf_path.parent / json_filename
            try:
                with open(json_filepath, "w", encoding="utf-8") as f:
                    json.dump(extracted_tables_debug, f, indent=2)
                logger.info(f"Wrote extracted tables debug JSON to {json_filepath}")
            except Exception as e:
                logger.error(f"Failed to write extracted tables debug JSON: {e}")

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

        # Fallback: try additional client-name patterns if organization wasn't found
        if not metadata["organization"] or _is_rejected_name(metadata["organization"]):
            found_valid = False
            for pattern in [_CLIENT_NAME_RE, _RFP_FOR_RE, _HEADER_ORG_RE]:
                m2 = pattern.search(full_text)
                if m2:
                    candidate = m2.group(1).strip().rstrip(".,;:")
                    if candidate and not _is_rejected_name(candidate):
                        metadata["organization"] = candidate
                        found_valid = True
                        break
            if not found_valid and metadata.get("organization") and _is_rejected_name(metadata["organization"]):
                metadata["organization"] = None

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
        Tables now carry actual text content instead of a placeholder.
        """
        chunks: list[dict[str, Any]] = []
        last_heading = "Untitled Section"

        for block in blocks:
            if block["type"] == "heading":
                last_heading = block["text"].strip()

            content_type = "table" if block["type"] == "table" else "text"

            chunks.append({
                "chunk_id": block["block_id"],
                "content_type": content_type,
                "section_hint": last_heading,
                "text": block["text"],
                "page_start": block["page_number"],
                "page_end": block["page_number"],
            })

        return chunks

    @staticmethod
    def prepare_semantic_chunks(
        blocks: list[dict[str, Any]],
        max_chunk_size: int = 8000,
    ) -> list[dict[str, Any]]:
        """
        Group blocks into semantically coherent chunks.

        Rules:
          - Headings are grouped with their body content.
          - Lists are never split across chunks.
          - Chunks are split only at block boundaries.
          - Max chunk size is enforced (but a single block is never split).
          - Tables are included as their own chunks to preserve structure.
          - Breadcrumbs are tracked and prepended to the chunk text.

        Returns list of chunks with:
          {chunk_id, chunk_index, content_type, section_hint, text,
           page_start, page_end}
        """
        if not blocks:
            return []

        import re

        def _get_heading_level(text: str) -> int:
            m = re.match(r'^(\d+(?:\.\d+)*)', text)
            if m:
                return len(m.group(1).split('.'))
            return 0  # 0 means no explicit number

        chunks: list[dict[str, Any]] = []
        current_text_parts: list[str] = []
        heading_stack: list[tuple[int, str]] = [(0, "Untitled Section")]
        current_heading = "Untitled Section"
        current_page_start = blocks[0].get("page_number", 1)
        current_page_end = current_page_start
        current_size = 0
        chunk_counter = 0

        def _flush():
            nonlocal chunk_counter, current_text_parts, current_size
            nonlocal current_page_start, current_page_end
            if not current_text_parts:
                return
            raw_text = "\n\n".join(current_text_parts)
            
            # Inject breadcrumb
            final_text = raw_text
            if current_heading and current_heading != "Untitled Section":
                final_text = f"[Section: {current_heading}]\n\n{raw_text}"

            chunks.append({
                "chunk_id": f"sc-{chunk_counter:04d}",
                "chunk_index": chunk_counter,
                "content_type": "text",
                "section_hint": current_heading,
                "text": final_text,
                "page_start": current_page_start,
                "page_end": current_page_end,
            })
            chunk_counter += 1
            current_text_parts = []
            current_size = 0

        for block in blocks:
            block_text = block.get("text", "")
            block_type = block.get("type", "paragraph")
            block_page = block.get("page_number", 1)
            block_len = len(block_text)

            # Tables are always their own chunk
            if block_type == "table":
                _flush()
                # Inject breadcrumb into table chunk too
                table_text = block_text
                if current_heading and current_heading != "Untitled Section":
                    table_text = f"[Section: {current_heading}]\n\n{block_text}"

                table_type = block.get("table_type", "unknown")

                logger.info(
                    f"[TABLE-TRACE][CHUNK] Table chunk created: "
                    f"chunk_id=sc-{chunk_counter:04d}, "
                    f"table_type={table_type}, "
                    f"section='{current_heading}', "
                    f"page={block_page}, "
                    f"text_len={len(table_text)}"
                )

                chunks.append({
                    "chunk_id": f"sc-{chunk_counter:04d}",
                    "chunk_index": chunk_counter,
                    "content_type": "table",
                    "table_type": table_type,
                    "section_hint": current_heading,
                    "text": table_text,
                    "page_start": block_page,
                    "page_end": block_page,
                })
                chunk_counter += 1
                current_page_start = block_page
                current_page_end = block_page
                continue

            # New heading → flush current buffer, start fresh
            if block_type == "heading":
                heading_text = block_text.strip()

                # ── Reject false-positive headings ────────
                # Spec-lines like "8 medium rooms (8-12 person capacity)\n–"
                # are sometimes classified as headings by font/bold heuristics
                # but corrupt the breadcrumb for all subsequent chunks.
                _is_false_heading = False
                if re.match(r'^\d+\s+(small|medium|large|extra)\b', heading_text, re.IGNORECASE):
                    _is_false_heading = True
                elif heading_text.rstrip().endswith(('\u2013', '\u2014', '\u2012', '-', ',')):
                    _is_false_heading = True
                elif '\n' in heading_text and heading_text.count('\n') >= 2:
                    _is_false_heading = True

                if _is_false_heading:
                    # Treat as paragraph instead
                    current_text_parts.append(block_text)
                    current_size += block_len
                    current_page_end = block_page
                    continue

                _flush()
                level = _get_heading_level(heading_text)

                # ── Detect top-level section headings ──
                # Headings like "SECTION 3 ..." or "APPENDIX A ..." signal
                # a completely new top-level section.  Reset the entire
                # breadcrumb stack so downstream agents get a clean,
                # section-specific section_hint for each RFP section.
                _TOP_LEVEL_RE = re.compile(
                    r'^(?:SECTION|PART|CHAPTER|APPENDIX|ANNEX)\s+',
                    re.IGNORECASE,
                )
                is_top_level = bool(_TOP_LEVEL_RE.match(heading_text))

                if is_top_level:
                    # Full reset — new top-level section starts fresh
                    heading_stack = [(0, "Untitled Section")]
                    logger.debug(
                        f"[PARSE] Heading stack reset at top-level: "
                        f"{heading_text[:80]}"
                    )
                elif level > 0:
                    # Sub-heading — pop siblings and children, keep parents
                    while heading_stack and heading_stack[-1][0] >= level:
                        heading_stack.pop()
                    if not heading_stack:
                        heading_stack.append((0, "Untitled Section"))
                else:
                    # Unnumbered heading (level 0) — replace last level-0
                    # entry but clear stale children from previous sections
                    while (heading_stack
                           and heading_stack[-1][0] == 0
                           and heading_stack[-1][1] != "Untitled Section"):
                        heading_stack.pop()

                heading_stack.append((level, heading_text))
                current_heading = " > ".join(
                    h[1] for h in heading_stack
                    if h[1] != "Untitled Section"
                ) or "Untitled Section"
                
                current_page_start = block_page
                current_page_end = block_page
                # Heading text is included as part of the new chunk
                current_text_parts.append(block_text)
                current_size += block_len
                continue

            # Would adding this block exceed max? Flush first.
            if current_size + block_len > max_chunk_size and current_text_parts:
                _flush()
                current_page_start = block_page

            current_text_parts.append(block_text)
            current_size += block_len
            current_page_end = block_page

        _flush()  # final buffer

        logger.info(
            f"Prepared {len(chunks)} semantic chunks from "
            f"{len(blocks)} blocks (max_size={max_chunk_size})"
        )
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


def _is_rejected_name(name: str) -> bool:
    """Check if a candidate client name is actually a section heading or sentence."""
    if not name:
        return True
    
    # Reject if it looks like a sentence fragment description rather than a name
    if len(name.split()) > 6 or "." in name or ";" in name:
        return True

    # Reject if it contains common verb/action words (sign of a sentence, not a name)
    _SENTENCE_WORDS = {"support", "provide", "ensure", "implement", "deploy",
                       "manage", "enable", "deliver", "maintain", "transform",
                       "develop", "integrate", "optimize", "rollout", "build",
                       "upgrade", "migrate", "configure", "design", "operate"}
    name_words = set(name.strip().lower().split())
    if name_words & _SENTENCE_WORDS:
        return True

    normalized = name.strip().lower().rstrip(".,;:")
    # Single word that's a common heading
    if normalized in _REJECTED_CLIENT_NAMES:
        return True
    # Very short (1-2 chars) or just a number
    if len(normalized) <= 2 or normalized.isdigit():
        return True
    return False


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

    # ── Reject false-positive headings ────────────────
    # Multi-line blocks and lines ending with dashes or commas
    # are specification fragments, not headings.
    if '\n' in stripped and stripped.count('\n') >= 2:
        return "paragraph"
    if stripped.rstrip().endswith(('\u2013', '\u2014', '\u2012', '-', ',')):
        return "paragraph"

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


def _extract_table_text(line_texts: list[str]) -> str:
    """
    Convert detected table lines into readable text.

    Joins multi-space-separated columns with " | " for clarity.
    Each row becomes a line in the output.
    """
    rows: list[str] = []
    for line in line_texts:
        # Normalize multi-space column gaps into pipe separators
        cells = re.split(r"\s{3,}", line.strip())
        if len(cells) > 1:
            rows.append(" | ".join(c.strip() for c in cells if c.strip()))
        else:
            rows.append(line.strip())
    return "\n".join(rows)


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
