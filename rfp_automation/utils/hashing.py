"""
Hashing utilities for document integrity and auditability.
"""

from __future__ import annotations

import hashlib


def sha256_hash(content: str | bytes) -> str:
    """Return the SHA-256 hex digest of the given content."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()
