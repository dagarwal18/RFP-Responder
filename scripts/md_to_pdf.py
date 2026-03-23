#!/usr/bin/env python3
"""
MD-to-PDF Converter — Professional RFP Proposal Export

Converts a markdown file (typically the pipeline's assembled_proposal.full_narrative)
into a professional PDF with cover page, page numbers, and native table rendering.

Dependencies:
    pip install weasyprint markdown

Usage:
    python scripts/md_to_pdf.py input.md output.pdf
    python scripts/md_to_pdf.py input.md output.pdf --rfp-title "Apex RFP" --client-name "Apex Industrial"
    python scripts/md_to_pdf.py input.md output.pdf --company-name "Vodafone Business"

Options:
    --rfp-title      RFP title for the cover page
    --client-name    Client/issuer name for the cover page
    --company-name   Proposing company name for the cover page
    --no-cover       Skip the cover page
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# ── CSS Stylesheet ────────────────────────────────────────

_CSS = """
@page {
    size: A4;
    margin: 2.5cm 2cm 3cm 2cm;
    @frame footer {
        -pdf-frame-content: footerContent;
        bottom: 0.8cm;
        margin-left: 2cm;
        margin-right: 2cm;
        height: 1.2cm;
    }
    @frame header {
        -pdf-frame-content: headerContent;
        top: 0.6cm;
        margin-left: 2cm;
        margin-right: 2cm;
        height: 1cm;
    }
}

/* Cover page gets its own page definition (no header/footer) */
@page cover {
    margin: 2.5cm 2cm 3cm 2cm;
}

body {
    font-family: Helvetica, Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.45;
    color: #1a1a1a;
}

/* ── Cover page ───────────────────────────── */

.cover-page {
    page: cover;
    text-align: center;
    padding-top: 5cm;
    page-break-after: always;
}

.cover-page .logo-bar {
    margin-bottom: 2cm;
    padding-bottom: 1cm;
    border-bottom: 3px solid #0052CC;
    font-size: 18pt;
    font-weight: bold;
    color: #0052CC;
}

.cover-page .rfp-title {
    font-size: 24pt;
    font-weight: bold;
    color: #0052CC;
    margin-bottom: 1cm;
    line-height: 1.2;
}

.cover-page .subtitle {
    font-size: 14pt;
    color: #555555;
    margin-bottom: 2cm;
}

.cover-page .meta-block {
    font-size: 12pt;
    color: #333333;
    line-height: 2;
}

.cover-page .meta-block strong {
    color: #0052CC;
}

/* ── Header / Footer content ─────────────── */

.page-header {
    font-size: 8pt;
    color: #888888;
    border-bottom: 0.5px solid #cccccc;
    padding-bottom: 4pt;
}

.page-footer {
    font-size: 8pt;
    color: #888888;
    text-align: center;
    border-top: 0.5px solid #cccccc;
    padding-top: 4pt;
}

/* ── Headings ─────────────────────────────── */

h1 {
    font-size: 18pt;
    font-weight: bold;
    color: #0052CC;
    border-bottom: 2px solid #0052CC;
    padding-bottom: 6pt;
    margin-top: 28pt;
    margin-bottom: 14pt;
    page-break-after: avoid;
}

h2 {
    font-size: 15pt;
    font-weight: bold;
    color: #1a3a5c;
    border-bottom: 1px solid #d0d7de;
    padding-bottom: 4pt;
    margin-top: 22pt;
    margin-bottom: 10pt;
    page-break-after: avoid;
}

h3 {
    font-size: 13pt;
    font-weight: bold;
    color: #2d5f8a;
    margin-top: 16pt;
    margin-bottom: 8pt;
    page-break-after: avoid;
}

h4 {
    font-size: 11.5pt;
    font-weight: bold;
    color: #333333;
    margin-top: 12pt;
    margin-bottom: 6pt;
    page-break-after: avoid;
}

h5, h6 {
    font-size: 11pt;
    font-weight: bold;
    font-style: italic;
    color: #444444;
    margin-top: 10pt;
    margin-bottom: 4pt;
}

/* ── Tables (robust for xhtml2pdf) ───────── */

table {
    width: 100%;
    border-collapse: collapse;
    margin: 14pt 0;
    font-size: 8.5pt;
    line-height: 1.35;
    word-wrap: break-word;
    overflow-wrap: break-word;
}

th {
    background-color: #0052CC;
    color: #ffffff;
    font-weight: bold;
    padding: 5pt 6pt;
    text-align: left;
    border: 0.5px solid #004099;
    word-wrap: break-word;
}

td {
    padding: 4pt 5pt;
    border: 0.5px solid #dddddd;
    vertical-align: top;
    word-wrap: break-word;
}

/* Removed page-break-inside: avoid from tr to allow long cells to break */
tr {
}

tr:nth-child(even) td {
    background-color: #f8f9fa;
}

/* ── Lists ────────────────────────────────── */

ul, ol {
    margin: 8pt 0;
    padding-left: 22pt;
}

li {
    margin-bottom: 4pt;
    line-height: 1.5;
}

/* ── Code ─────────────────────────────────── */

code {
    font-family: "Courier New", Courier, monospace;
    font-size: 9pt;
    background-color: #f4f4f4;
    padding: 1pt 4pt;
    border-radius: 2pt;
}

pre {
    background-color: #f4f4f4;
    padding: 10pt;
    font-size: 9pt;
    line-height: 1.3;
    border: 0.5px solid #dddddd;
    page-break-inside: avoid;
    white-space: pre-wrap;
    word-wrap: break-word;
}

/* ── Blockquotes ──────────────────────────── */

blockquote {
    border-left: 3px solid #0052CC;
    margin: 12pt 0;
    padding: 8pt 14pt;
    background-color: #f0f4f8;
    color: #333333;
    font-style: italic;
}

/* ── Horizontal rules ─────────────────────── */

hr {
    border: 0;
    border-top: 0.5px solid #cccccc;
    margin: 18pt 0;
}

/* ── Paragraphs ───────────────────────────── */

p {
    margin-bottom: 12pt;
    text-align: left;
    line-height: 1.5;
}

/* ── Images (for Mermaid diagrams) ────────── */

img {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 14pt auto;
    page-break-inside: avoid;
}

/* ── Bold / Italic / Strong ──────────────── */

strong, b {
    font-weight: bold;
    color: #111111;
}

em, i {
    font-style: italic;
}
"""


def _build_cover_html(
    rfp_title: str,
    client_name: str,
    company_name: str,
) -> str:
    """Generate the HTML cover page."""
    date_str = datetime.now().strftime("%B %d, %Y")
    return f"""
<div class="cover-page">
    <div class="logo-bar">
        <div style="font-size: 18pt; font-weight: 700; color: #0052CC;">
            {company_name}
        </div>
    </div>
    <div class="rfp-title">{rfp_title}</div>
    <div class="subtitle">Technical &amp; Commercial Proposal</div>
    <div class="meta-block">
        <strong>Submitted to:</strong> {client_name}<br>
        <strong>Submitted by:</strong> {company_name}<br>
        <strong>Date:</strong> {date_str}<br>
    </div>
</div>
"""


def _scrub_markdown(md_text: str) -> str:
    """Pre-process markdown to remove artifacts that confuse xhtml2pdf.

    Handles:
      - Stray ```mermaid blocks (should already be replaced, but just in case)
      - Orphaned markdown syntax characters that bleed through
      - Excessively long unbroken strings in table cells
    """
    import re

    # Remove any leftover mermaid code blocks (replace with placeholder note)
    md_text = re.sub(
        r"```mermaid\s*.*?```",
        "\n> *[Diagram not rendered — see proposal_raw.md]*\n",
        md_text,
        flags=re.DOTALL,
    )

    # Remove orphaned bold/italic markers at start of otherwise empty lines
    # e.g., a line that is just "**" or "***" with nothing else
    md_text = re.sub(r"^\s*\*{1,3}\s*$", "", md_text, flags=re.MULTILINE)

    # Remove stray hash lines (e.g., a line that is just "###" with no title)
    md_text = re.sub(r"^\s*#{1,6}\s*$", "", md_text, flags=re.MULTILINE)

    return md_text


def convert_md_to_pdf(
    input_path: str,
    output_path: str,
    rfp_title: str = "RFP Response Proposal",
    client_name: str = "Client",
    company_name: str = "Proposing Company",
    include_cover: bool = True,
) -> str:
    """
    Convert a Markdown file to a professional PDF using xhtml2pdf.

    Args:
        input_path:    Path to the input .md file
        output_path:   Path for the output .pdf file
        rfp_title:     Title for the cover page
        client_name:   Client name for the cover page
        company_name:  Proposing company for the cover page
        include_cover: Whether to include the cover page

    Returns:
        Absolute path to the generated PDF
    """
    try:
        import markdown
        from xhtml2pdf import pisa
    except ImportError as e:
        missing = str(e).split("'")[-2] if "'" in str(e) else str(e)
        print(
            f"ERROR: Missing dependency '{missing}'.\n"
            f"Install with: pip install xhtml2pdf markdown",
            file=sys.stderr,
        )
        sys.exit(1)

    # Read the markdown
    md_path = Path(input_path)
    if not md_path.exists():
        print(f"ERROR: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    md_text = md_path.read_text(encoding="utf-8")
    logger.info(f"Read {len(md_text)} chars from {md_path.name}")

    # ── Pre-process: scrub stray markdown artifacts ──
    md_text = _scrub_markdown(md_text)

    # Convert Markdown → HTML
    extensions = [
        "tables",         # pipe tables
        "fenced_code",    # ```code blocks```
        "toc",            # table of contents
        "sane_lists",     # better list handling
    ]
    html_body = markdown.markdown(md_text, extensions=extensions)

    # Build full HTML document
    cover_html = ""
    if include_cover:
        cover_html = _build_cover_html(rfp_title, client_name, company_name)

    # Header and footer content for non-cover pages
    header_html = f"""
<div id="headerContent">
    <div class="page-header">{company_name} — {rfp_title}</div>
</div>
"""
    footer_html = """
<div id="footerContent">
    <div class="page-footer">
        <pdf:pagenumber />
    </div>
</div>
"""

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{rfp_title}</title>
    <style>
        {_CSS}
    </style>
</head>
<body>
{header_html}
{footer_html}
{cover_html}
{html_body}
</body>
</html>"""

    # Generate PDF
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Use link_callback to resolve relative image paths from the markdown dir
    base_dir = str(md_path.parent.resolve())

    def link_callback(uri, rel):
        """Resolve image paths relative to the markdown file's directory."""
        if uri.startswith(("http://", "https://", "data:")):
            return uri
        resolved = Path(base_dir) / uri
        if resolved.exists():
            return str(resolved)
        # Try as absolute path
        abs_path = Path(uri)
        if abs_path.exists():
            return str(abs_path)
        return uri

    with open(out_path, "w+b") as result_file:
        pisa_status = pisa.CreatePDF(
            full_html,
            dest=result_file,
            link_callback=link_callback,
        )

    if pisa_status.err:
        print(f"ERROR: Generated PDF with errors", file=sys.stderr)
        sys.exit(1)

    file_size_kb = out_path.stat().st_size / 1024
    logger.info(f"Generated PDF: {out_path} ({file_size_kb:.1f} KB)")
    print(f"SUCCESS: PDF generated at {out_path} ({file_size_kb:.1f} KB)")

    return str(out_path.resolve())


def main():
    parser = argparse.ArgumentParser(
        description="Convert Markdown output to professional PDF",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/md_to_pdf.py proposal.md proposal.pdf\n"
            '  python scripts/md_to_pdf.py proposal.md out.pdf --rfp-title "Apex RFP"\n'
            '  python scripts/md_to_pdf.py proposal.md out.pdf --company-name "Vodafone"'
        ),
    )
    parser.add_argument("input", help="Path to the input Markdown file")
    parser.add_argument("output", help="Path for the output PDF file")
    parser.add_argument(
        "--rfp-title",
        default="RFP Response Proposal",
        help="RFP title for the cover page (default: 'RFP Response Proposal')",
    )
    parser.add_argument(
        "--client-name",
        default="Client",
        help="Client/issuing organization name (default: 'Client')",
    )
    parser.add_argument(
        "--company-name",
        default="Proposing Company",
        help="Proposing company name (default: 'Proposing Company')",
    )
    parser.add_argument(
        "--no-cover",
        action="store_true",
        help="Skip the cover page",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s | %(message)s",
    )

    convert_md_to_pdf(
        input_path=args.input,
        output_path=args.output,
        rfp_title=args.rfp_title,
        client_name=args.client_name,
        company_name=args.company_name,
        include_cover=not args.no_cover,
    )


if __name__ == "__main__":
    main()
