"""
Requirement Schema — data structures for extracted requirements in the MCP context.
"""

from __future__ import annotations

from pydantic import BaseModel


class ExtractedRequirement(BaseModel):
    """A requirement as stored/queried in the MCP vector store."""
    requirement_id: str
    text: str
    section_id: str = ""
    type: str = "MANDATORY"  # MANDATORY | OPTIONAL
    category: str = "TECHNICAL"
    impact: str = "MEDIUM"
    embedding_id: str = ""
    source_chunk_ids: list[str] = []  # trace back to vector store chunks
    compliance_mapping: str = ""  # regulatory cross-reference (e.g. "NIST 800-53 AC-2")
