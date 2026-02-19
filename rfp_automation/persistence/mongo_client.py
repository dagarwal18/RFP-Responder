"""
Mongo Client — raw database connection management.
"""

from __future__ import annotations

import logging
from typing import Any

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)


class MongoClient:
    """
    Thin wrapper around pymongo for MongoDB connections.
    """

    def __init__(self):
        self.settings = get_settings()
        self._client: Any = None
        self._db: Any = None

    def connect(self) -> None:
        """Establish the MongoDB connection."""
        try:
            from pymongo import MongoClient as PyMongoClient

            self._client = PyMongoClient(self.settings.mongodb_uri)
            self._db = self._client[self.settings.mongodb_database]
            logger.info(f"Connected to MongoDB: {self.settings.mongodb_database}")
        except ImportError:
            logger.error("pymongo not installed")
            raise

    def get_database(self) -> Any:
        """Return the database handle."""
        if self._db is None:
            self.connect()
        return self._db

    def close(self) -> None:
        """Close the connection."""
        if self._client:
            self._client.close()
            logger.info("MongoDB connection closed")
