"""
File Service — abstraction over local filesystem and S3.
Handles upload, download, and archival of RFP files and outputs.
"""

from __future__ import annotations

import logging
from pathlib import Path

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)


class FileService:
    """Swappable file storage — local for dev, S3 for prod."""

    def __init__(self):
        self.settings = get_settings()
        self.backend = self.settings.storage_backend

        if self.backend == "local":
            self.base_path = Path(self.settings.local_storage_path)
            self.base_path.mkdir(parents=True, exist_ok=True)

    def save_file(self, file_bytes: bytes, destination: str) -> str:
        """Save a file and return the stored path/key."""
        if self.backend == "local":
            path = self.base_path / destination
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(file_bytes)
            logger.info(f"Saved file to {path}")
            return str(path)

        # TODO: S3 upload with boto3
        raise NotImplementedError(f"Backend '{self.backend}' not implemented")

    def load_file(self, path: str) -> bytes:
        """Load a file's content."""
        if self.backend == "local":
            return Path(path).read_bytes()
        raise NotImplementedError

    def archive(self, rfp_id: str, files: dict[str, bytes]) -> str:
        """Archive all deliverables for an RFP."""
        archive_dir = f"archive/{rfp_id}"
        for name, content in files.items():
            self.save_file(content, f"{archive_dir}/{name}")
        logger.info(f"Archived {len(files)} files for {rfp_id}")
        return archive_dir

    def list_files(self, prefix: str = "") -> list[str]:
        """List files under a prefix."""
        if self.backend == "local":
            base = self.base_path / prefix
            if base.exists():
                return [
                    str(p.relative_to(self.base_path))
                    for p in base.rglob("*")
                    if p.is_file()
                ]
            return []
        raise NotImplementedError
