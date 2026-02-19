"""
Audit Service — dedicated service for recording and querying audit trails.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class AuditService:
    """
    Records agent actions, pipeline decisions, and gate results.
    In mock mode, uses in-memory list. Real mode would write to MongoDB.
    """

    def __init__(self, mock_mode: bool = True):
        self.mock_mode = mock_mode
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

        if self.mock_mode:
            self._entries.append(entry)
            logger.debug(f"[AUDIT] {agent} → {action}: {details}")
        else:
            # TODO: Write to MongoDB audit collection
            raise NotImplementedError

        return entry

    def get_trail(self, rfp_id: str) -> list[dict[str, Any]]:
        """Return all audit entries for an RFP."""
        if self.mock_mode:
            return [e for e in self._entries if e["rfp_id"] == rfp_id]
        raise NotImplementedError

    def get_all(self) -> list[dict[str, Any]]:
        """Return all audit entries (for debugging)."""
        return list(self._entries)
