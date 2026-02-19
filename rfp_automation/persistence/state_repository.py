"""
State Repository — persistence layer for graph state.
Handles save, load, versioning, and audit trail in MongoDB.
In mock mode, uses an in-memory dict.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)


class StateRepository:
    """
    Save/load RFPGraphState to persistent storage.
    Mock mode: in-memory dict.
    Real mode: MongoDB.
    """

    def __init__(self):
        self.settings = get_settings()
        self.mock_mode = self.settings.mock_mode
        self._memory_store: dict[str, list[dict[str, Any]]] = {}

    def save_state(self, rfp_id: str, state_dict: dict[str, Any]) -> int:
        """
        Save a state snapshot and return the version number.
        Each save creates a new version (append-only for audit).
        """
        if self.mock_mode:
            if rfp_id not in self._memory_store:
                self._memory_store[rfp_id] = []
            version = len(self._memory_store[rfp_id]) + 1
            snapshot = deepcopy(state_dict)
            snapshot["_version"] = version
            self._memory_store[rfp_id].append(snapshot)
            logger.info(f"[MOCK] Saved state v{version} for {rfp_id}")
            return version
        # TODO: MongoDB insert
        raise NotImplementedError

    def load_state(self, rfp_id: str, version: int | None = None) -> dict[str, Any] | None:
        """
        Load the latest (or specific version) of state for an RFP.
        Returns None if not found.
        """
        if self.mock_mode:
            snapshots = self._memory_store.get(rfp_id, [])
            if not snapshots:
                return None
            if version is not None:
                matches = [s for s in snapshots if s.get("_version") == version]
                return deepcopy(matches[0]) if matches else None
            return deepcopy(snapshots[-1])
        raise NotImplementedError

    def list_rfps(self) -> list[str]:
        """List all RFP IDs in the store."""
        if self.mock_mode:
            return list(self._memory_store.keys())
        raise NotImplementedError

    def get_version_count(self, rfp_id: str) -> int:
        """Return number of saved versions for an RFP."""
        if self.mock_mode:
            return len(self._memory_store.get(rfp_id, []))
        raise NotImplementedError
