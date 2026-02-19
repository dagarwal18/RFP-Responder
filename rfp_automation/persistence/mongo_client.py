"""
Mongo Client — raw database connection management.
In mock mode, no actual connection is created.
"""

from __future__ import annotations

import logging
from typing import Any

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)


class MongoClient:
    """
    Thin wrapper around motor (async) / pymongo.
    In mock mode this is a no-op placeholder.
    """

    def __init__(self):
        self.settings = get_settings()
        self._client: Any = None
        self._db: Any = None

    def connect(self) -> None:
        """Establish the MongoDB connection (no-op in mock mode)."""
        if self.settings.mock_mode:
            logger.info("[MOCK] MongoDB connection simulated")
            return

        try:
            from pymongo import MongoClient as PyMongoClient

            self._client = PyMongoClient(self.settings.mongodb_uri)
            self._db = self._client[self.settings.mongodb_db_name]
            logger.info(f"Connected to MongoDB: {self.settings.mongodb_db_name}")
        except ImportError:
            logger.error("pymongo not installed — falling back to mock mode")

    def get_database(self) -> Any:
        """Return the database handle."""
        if self._db is None and not self.settings.mock_mode:
            self.connect()
        return self._db

    def close(self) -> None:
        """Close the connection."""
        if self._client:
            self._client.close()
            logger.info("MongoDB connection closed")
