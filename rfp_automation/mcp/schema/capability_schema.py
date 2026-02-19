"""
Capability Schema — data structures for company capabilities stored in the knowledge base.
"""

from __future__ import annotations

from pydantic import BaseModel


class Capability(BaseModel):
    """A company capability record in the knowledge store."""
    capability_id: str
    name: str
    description: str = ""
    evidence: str = ""
    category: str = ""  # "cloud", "security", "devops", etc.
    confidence_score: float = 0.0
