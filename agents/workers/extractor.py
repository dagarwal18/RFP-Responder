from orchestration.state import Requirement
import io
import re
from typing import List, Dict
import json

async def extract_requirements(filename: str, content: bytes) -> List[Dict]:
    """
    Extract rough 'requirements' from a PDF or text file.
    - Tries pdfminer.six for per-page extraction (if installed).
    - Falls back to naive decode and page-split by form-feed.
    Returns a list of dicts:
    {
        "id": "<filename>-REQ-<n>",
        "title": "...",
        "description": "...",
        "evidence": {"page": i, "text": "snippet...", "paragraph_index": idx}
    }
    """
    pages = _extract_pages(content)
    requirements = []
    req_counter = 1
    heading_rx = re.compile(r'^\s*\d+(\.\d+)*\s+.+')  # e.g. "1.1. Overview" or "2.3.4 Title"

    for pidx, page_text in enumerate(pages, start=1):
        lines = [l.strip() for l in page_text.splitlines() if l.strip()]
        # First pass: create requirement from headings
        for li, line in enumerate(lines):
            if heading_rx.match(line):
                title = line
                # gather following lines up to next heading or 3 lines as description
                desc_lines = []
                for nxt in lines[li+1:li+4]:
                    desc_lines.append(nxt)
                description = " ".join(desc_lines).strip()[:800]
                req = {
                    "id": f"{filename}-REQ-{req_counter}",
                    "title": title,
                    "description": description or title,
                    "evidence": {"page": pidx, "text": line, "paragraph_index": li}
                }
                requirements.append(req)
                req_counter += 1
        # Fallback: if no headings on page, create coarse-grain requirements from paragraphs
        if not any(heading_rx.match(l) for l in lines):
            para_texts = _split_paragraphs(lines)
            for pi, para in enumerate(para_texts):
                if len(para) < 40:
                    continue
                req = {
                    "id": f"{filename}-REQ-{req_counter}",
                    "title": (para[:80].split("\n")[0]).strip(),
                    "description": para.strip()[:800],
                    "evidence": {"page": pidx, "text": para.strip()[:200], "paragraph_index": pi}
                }
                requirements.append(req)
                req_counter += 1

    # Ensure at least one requirement exists
    if not requirements:
        # create a single generic requirement from first page or content
        snippet = pages[0][:400] if pages else ""
        requirements.append({
            "id": f"{filename}-REQ-1",
            "title": "Document Overview",
            "description": snippet,
            "evidence": {"page": 1, "text": snippet[:200], "paragraph_index": 0}
        })
    return requirements

def _extract_pages(content: bytes) -> List[str]:
    """
    Attempt to extract per-page text using pdfminer (preferred) or fallback.
    """
    try:
        # lazy import to avoid forcing dependency at module import
        from pdfminer.high_level import extract_text_to_fp
        from pdfminer.layout import LAParams
        fp = io.BytesIO(content)
        out_fp = io.StringIO()
        extract_text_to_fp(fp, out_fp, laparams=LAParams(), output_type='text', codec=None)
        full = out_fp.getvalue()
        # pdfminer doesn't always include page breaks; try splitting on common markers
        pages = re.split(r'\f+', full)
        if len(pages) == 1:
            # try splitting by page headings like "Page \d+"
            pages = re.split(r'\n\s*Page\s+\d+\s*\n', full)
        return [p for p in pages if p.strip()]
    except Exception:
        # fallback: try a naive decode and split on form-feed
        try:
            text = content.decode('utf-8', errors='ignore')
        except Exception:
            text = content.decode('latin-1', errors='ignore')
        pages = text.split('\f')
        return [p for p in pages if p.strip()]

def _split_paragraphs(lines: List[str]) -> List[str]:
    """
    Coalesce consecutive lines into paragraphs.
    """
    paras = []
    buf = []
    for l in lines:
        if not l:
            if buf:
                paras.append(" ".join(buf).strip())
                buf = []
        else:
            buf.append(l)
    if buf:
        paras.append(" ".join(buf).strip())
    return paras
