"""
Storage Service — high-level facade for file + state persistence.
Coordinates FileService and StateRepository for common operations.
"""

from __future__ import annotations

import logging
from typing import Any

from rfp_automation.services.file_service import FileService
from rfp_automation.persistence.state_repository import StateRepository

logger = logging.getLogger(__name__)


class StorageService:
    """Orchestrates file + state persistence."""

    def __init__(self):
        self.files = FileService()
        self.state_repo = StateRepository()

    def save_rfp_upload(self, rfp_id: str, file_bytes: bytes, filename: str) -> str:
        """Save an uploaded RFP file and return the path."""
        dest = f"uploads/{rfp_id}_{filename}"
        return self.files.save_file(file_bytes, dest)

    def save_pipeline_state(self, rfp_id: str, state_dict: dict[str, Any]) -> int:
        """Save a pipeline state snapshot and return version."""
        return self.state_repo.save_state(rfp_id, state_dict)

    def load_pipeline_state(self, rfp_id: str) -> dict[str, Any] | None:
        """Load the latest pipeline state for an RFP."""
        return self.state_repo.load_state(rfp_id)

    def list_all_rfps(self) -> list[str]:
        """List all known RFP IDs."""
        return self.state_repo.list_rfps()
