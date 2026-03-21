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
        bottom: 1cm;
        margin-left: 2cm;
        margin-right: 2cm;
        height: 1cm;
    }
    @frame header {
        -pdf-frame-content: headerContent;
        top: 1cm;
        margin-left: 2cm;
        margin-right: 2cm;
        height: 1cm;
    }
}

body {
    font-family: Helvetica, Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.5;
    color: #1a1a1a;
}

/* ── Cover page ───────────────────────────── */

.cover-page {
    text-align: center;
    padding-top: 5cm;
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

/* ── Headings ─────────────────────────────── */

h1 {
    font-size: 18pt;
    font-weight: bold;
    color: #0052CC;
    border-bottom: 1px solid #0052CC;
    padding-bottom: 6pt;
    margin-top: 24pt;
    margin-bottom: 12pt;
    page-break-after: avoid;
}

h2 {
    font-size: 15pt;
    font-weight: bold;
    color: #1a3a5c;
    margin-top: 18pt;
    margin-bottom: 8pt;
    page-break-after: avoid;
}

h3 {
    font-size: 13pt;
    font-weight: bold;
    color: #2d5f8a;
    margin-top: 14pt;
    margin-bottom: 6pt;
    page-break-after: avoid;
}

h4, h5, h6 {
    font-size: 11pt;
    font-weight: bold;
    color: #333333;
    margin-top: 10pt;
    margin-bottom: 4pt;
}

/* ── Tables ───────────────────────────────── */

table {
    width: 100%;
    border-collapse: collapse;
    margin: 12pt 0;
    font-size: 10pt;
}

th {
    background-color: #0052CC;
    color: #ffffff;
    font-weight: bold;
    padding: 6pt 8pt;
    text-align: left;
    border: 0.5px solid #004099;
}

td {
    padding: 6pt 8pt;
    border: 0.5px solid #dddddd;
    vertical-align: top;
}

/* ── Lists ────────────────────────────────── */

ul, ol {
    margin: 6pt 0;
    padding-left: 20pt;
}

li {
    margin-bottom: 4pt;
}

/* ── Code ─────────────────────────────────── */

code {
    font-family: "Courier New", Courier, monospace;
    font-size: 9pt;
    background-color: #f4f4f4;
    padding: 1pt 4pt;
}

pre {
    background-color: #f4f4f4;
    padding: 10pt;
    font-size: 9pt;
    line-height: 1.3;
}

/* ── Blockquotes ──────────────────────────── */

blockquote {
    border-left: 3px solid #0052CC;
    margin: 10pt 0;
    padding: 6pt 12pt;
    background-color: #f0f4f8;
    color: #333333;
}

/* ── Horizontal rules ─────────────────────── */

hr {
    border: 0;
    border-top: 0.5px solid #cccccc;
    margin: 16pt 0;
}

/* ── Paragraphs ───────────────────────────── */

p {
    margin-bottom: 8pt;
    text-align: justify;
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

    # Convert Markdown → HTML
    extensions = [
        "tables",         # pipe tables
        "fenced_code",    # ```code blocks```
        "toc",            # table of contents
        "nl2br",          # newlines → <br>
        "sane_lists",     # better list handling
    ]
    html_body = markdown.markdown(md_text, extensions=extensions)

    # Build full HTML document
    cover_html = ""
    if include_cover:
        cover_html = _build_cover_html(rfp_title, client_name, company_name)

    # Note: xhtml2pdf supports specific CSS features. Included CSS is mostly compatible.
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
{cover_html}
{html_body}
</body>
</html>"""

    # Generate PDF
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w+b") as result_file:
        pisa_status = pisa.CreatePDF(full_html, dest=result_file)

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
