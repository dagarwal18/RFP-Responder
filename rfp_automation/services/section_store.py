"""
Section Store — full-text storage for RFP sections to bypass vector store truncation limits.
Uses MongoDB as primary store with a local JSON file as a fallback.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)


class SectionStore:
    """
    Manages the full-text storage of extracted RFP sections/chunks.
    Solves the problem of Pinecone's 1000-character metadata limit.
    """

    def __init__(self):
        self.settings = get_settings()
        self._mongo_db = None
        
        # Ensure local fallback directory exists
        self.fallback_dir = Path("storage/sections")
        self.fallback_dir.mkdir(parents=True, exist_ok=True)

    def _get_db(self):
        """Lazy-init: connect to MongoDB."""
        if self._mongo_db is not None:
            return self._mongo_db
            
        try:
            from pymongo import MongoClient
            client = MongoClient(self.settings.mongodb_uri)
            self._mongo_db = client[self.settings.mongodb_database]
            return self._mongo_db
        except Exception as e:
            logger.warning(f"Failed to connect to MongoDB: {e}")
            return None

    def save_sections(self, rfp_id: str, chunks: list[dict[str, Any]]) -> None:
        """
        Save full chunk texts to MongoDB and JSON fallback.
        """
        if not chunks:
            return
            
        # Create map for JSON fallback
        chunk_map = {c.get("chunk_id"): c for c in chunks if c.get("chunk_id")}
        
        # 1. MongoDB Save
        db = self._get_db()
        if db is not None:
            try:
                # Delete existing chunks for this RFP to avoid duplicates
                db.rfp_chunks.delete_many({"rfp_id": rfp_id})
                
                docs = []
                for chunk in chunks:
                    doc = {
                        "rfp_id": rfp_id,
                        "chunk_id": chunk.get("chunk_id"),
                        "chunk_index": chunk.get("chunk_index"),
                        "full_text": chunk.get("text", ""),
                        "content_type": chunk.get("content_type", "text"),
                        "section_hint": chunk.get("section_hint", ""),
                        "page_start": chunk.get("page_start"),
                        "page_end": chunk.get("page_end"),
                    }
                    docs.append(doc)
                
                if docs:
                    db.rfp_chunks.insert_many(docs)
                logger.info(f"Saved {len(docs)} sections for {rfp_id} to MongoDB (rfp_chunks)")
            except Exception as e:
                logger.error(f"Failed to save sections to MongoDB for {rfp_id}: {e}")

        # 2. JSON Fallback Save
        fallback_path = self.fallback_dir / f"{rfp_id}.json"
        try:
            with open(fallback_path, "w", encoding="utf-8") as f:
                json.dump(chunk_map, f, indent=2)
            logger.debug(f"Saved JSON fallback for {rfp_id} at {fallback_path}")
        except Exception as e:
            logger.error(f"Failed to save JSON fallback for {rfp_id}: {e}")

    def load_sections(self, rfp_id: str) -> dict[str, dict[str, Any]]:
        """
        Load sections from MongoDB, falling back to JSON.
        Returns a dict mapping chunk_id -> chunk data (including 'text').
        """
        chunk_map = {}
        
        # 1. Try MongoDB
        db = self._get_db()
        if db is not None:
            try:
                cursor = db.rfp_chunks.find({"rfp_id": rfp_id})
                for doc in cursor:
                    chunk_id = doc.get("chunk_id")
                    if chunk_id:
                        chunk_map[chunk_id] = {
                            "chunk_id": chunk_id,
                            "chunk_index": doc.get("chunk_index"),
                            "text": doc.get("full_text", ""),
                            "content_type": doc.get("content_type", "text"),
                            "section_hint": doc.get("section_hint", ""),
                            "page_start": doc.get("page_start"),
                            "page_end": doc.get("page_end"),
                        }
                if chunk_map:
                    logger.debug(f"Loaded {len(chunk_map)} sections from MongoDB for {rfp_id}")
                    return chunk_map
            except Exception as e:
                logger.error(f"Failed to load sections from MongoDB for {rfp_id}: {e}")

        # 2. Try JSON Fallback
        fallback_path = self.fallback_dir / f"{rfp_id}.json"
        if fallback_path.exists():
            try:
                with open(fallback_path, "r", encoding="utf-8") as f:
                    chunk_map = json.load(f)
                logger.info(f"Loaded {len(chunk_map)} sections from JSON fallback for {rfp_id}")
                return chunk_map
            except Exception as e:
                logger.error(f"Failed to load JSON fallback for {rfp_id}: {e}")
        else:
            logger.warning(f"No JSON fallback found for {rfp_id} at {fallback_path}")

        return chunk_map
