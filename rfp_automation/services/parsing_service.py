"""
Parsing Service — extracts text from PDF and DOCX files, with chunking.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ParsingService:
    """Extract raw text from uploaded RFP documents and split into chunks."""

    # ── Parsing ──────────────────────────────────────────

    @staticmethod
    def parse(file_path: str) -> str:
        """
        Parse a document and return extracted text.
        Supports: .pdf, .docx
        """
        ext = Path(file_path).suffix.lower()

        if ext == ".pdf":
            return ParsingService._parse_pdf(file_path)
        elif ext == ".docx":
            return ParsingService._parse_docx(file_path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")

    @staticmethod
    def _parse_pdf(file_path: str) -> str:
        """Extract text from PDF using PyMuPDF."""
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(file_path)
            text = ""
            for page in doc:
                text += page.get_text() + "\n"
            doc.close()
            return text.strip()
        except ImportError:
            logger.warning("PyMuPDF not installed — returning mock text")
            return f"[Mock PDF text extracted from {file_path}]"

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

    # ── Chunking ─────────────────────────────────────────

    @staticmethod
    def chunk_text(
        text: str,
        chunk_size: int = 1000,
        overlap: int = 200,
    ) -> list[str]:
        """
        Split text into overlapping chunks for embedding/retrieval.
        Returns a list of text chunks.
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
