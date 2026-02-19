"""
State Repository — persistence layer for graph state.
Handles save, load, versioning, and audit trail.
Uses in-memory dict for now; will be wired to MongoDB.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

logger = logging.getLogger(__name__)


class StateRepository:
    """
    Save/load RFPGraphState to persistent storage.
    Currently uses in-memory dict. TODO: wire to MongoDB.
    """

    def __init__(self):
        self._memory_store: dict[str, list[dict[str, Any]]] = {}

    def save_state(self, rfp_id: str, state_dict: dict[str, Any]) -> int:
        """
        Save a state snapshot and return the version number.
        Each save creates a new version (append-only for audit).
        """
        if rfp_id not in self._memory_store:
            self._memory_store[rfp_id] = []
        version = len(self._memory_store[rfp_id]) + 1
        snapshot = deepcopy(state_dict)
        snapshot["_version"] = version
        self._memory_store[rfp_id].append(snapshot)
        logger.info(f"Saved state v{version} for {rfp_id}")
        return version

    def load_state(self, rfp_id: str, version: int | None = None) -> dict[str, Any] | None:
        """
        Load the latest (or specific version) of state for an RFP.
        Returns None if not found.
        """
        snapshots = self._memory_store.get(rfp_id, [])
        if not snapshots:
            return None
        if version is not None:
            matches = [s for s in snapshots if s.get("_version") == version]
            return deepcopy(matches[0]) if matches else None
        return deepcopy(snapshots[-1])

    def list_rfps(self) -> list[str]:
        """List all RFP IDs in the store."""
        return list(self._memory_store.keys())

    def get_version_count(self, rfp_id: str) -> int:
        """Return number of saved versions for an RFP."""
        return len(self._memory_store.get(rfp_id, []))
