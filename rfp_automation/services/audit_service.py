"""
Audit Service — dedicated service for recording and querying audit trails.
Records to MongoDB via the persistence layer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class AuditService:
    """
    Records agent actions, pipeline decisions, and gate results.
    Uses in-memory list for now. Will be wired to MongoDB.
    """

    def __init__(self):
        self._entries: list[dict[str, Any]] = []

    def record(
        self,
        rfp_id: str,
        agent: str,
        action: str,
        details: str = "",
        state_version: int = 0,
    ) -> dict[str, Any]:
        """Record an audit entry and return it."""
        entry = {
            "rfp_id": rfp_id,
            "agent": agent,
            "action": action,
            "details": details,
            "state_version": state_version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # TODO: Write to MongoDB audit collection once wired
        self._entries.append(entry)
        logger.debug(f"[AUDIT] {agent} → {action}: {details}")

        return entry

    def get_trail(self, rfp_id: str) -> list[dict[str, Any]]:
        """Return all audit entries for an RFP."""
        return [e for e in self._entries if e["rfp_id"] == rfp_id]

    def get_all(self) -> list[dict[str, Any]]:
        """Return all audit entries (for debugging)."""
        return list(self._entries)
