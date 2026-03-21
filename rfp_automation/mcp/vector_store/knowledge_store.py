"""
Knowledge Store — company-level knowledge base.

Vector data (capabilities, past proposals) lives in Pinecone under the
"knowledge" namespace.  Structured config (certifications, pricing rules,
legal templates) lives in MongoDB.

This is a GLOBAL store — not per-RFP.  An admin seeds it once and every
pipeline run reads from it.
"""

from __future__ import annotations

import logging
from typing import Any

from rfp_automation.config import get_settings
from rfp_automation.mcp.embeddings.embedding_model import EmbeddingModel

logger = logging.getLogger(__name__)

KNOWLEDGE_NAMESPACE = "company_knowledge"


class KnowledgeStore:
    """
    Company knowledge base: capabilities, certifications, pricing rules,
    legal templates, past proposals.
    """

    def __init__(self):
        self.settings = get_settings()
        self._embedder = EmbeddingModel()
        self._index = None
        self._mongo_db = None

    # ── Pinecone connection ──────────────────────────────

    def _get_index(self):
        """Lazy-init: connect to Pinecone index (shared with RFP store)."""
        if self._index is not None:
            return self._index

        from pinecone import Pinecone, ServerlessSpec

        pc = Pinecone(api_key=self.settings.pinecone_api_key)
        index_name = self.settings.pinecone_index_name

        existing = [idx.name for idx in pc.list_indexes()]
        if index_name not in existing:
            pc.create_index(
                name=index_name,
                dimension=self._embedder.dimension,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud=self.settings.pinecone_cloud,
                    region=self.settings.pinecone_region,
                ),
            )

        self._index = pc.Index(index_name)
        return self._index

    # ── MongoDB connection ───────────────────────────────

    def _get_db(self):
        """Lazy-init: connect to MongoDB for structured company data."""
        if self._mongo_db is not None:
            return self._mongo_db

        from pymongo import MongoClient

        client = MongoClient(self.settings.mongodb_uri)
        self._mongo_db = client[self.settings.mongodb_database]
        return self._mongo_db

    # ── Admin: ingest company documents ──────────────────

    def ingest_company_docs(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]] | None = None,
        doc_type: str = "capability",
    ) -> int:
        """
        Admin function: embed company documents and store in Pinecone
        knowledge namespace.  Returns number of vectors stored.
        """
        index = self._get_index()
        embeddings = self._embedder.embed(texts)
        metadatas = metadatas or [{} for _ in texts]

        vectors = []
        for i, (text, emb, meta) in enumerate(zip(texts, embeddings, metadatas)):
            vec_id = f"knowledge_{doc_type}_{meta.get('id', i)}"
            vec_metadata = {
                "text": text,
                "doc_type": doc_type,
                **meta,
            }
            vectors.append((vec_id, emb, vec_metadata))

        # Batch upsert
        batch_size = 100
        for start in range(0, len(vectors), batch_size):
            batch = vectors[start : start + batch_size]
            index.upsert(vectors=batch, namespace=KNOWLEDGE_NAMESPACE)

        logger.info(f"Ingested {len(texts)} {doc_type} docs into knowledge store")
        return len(texts)

    def clear_index(self) -> None:
        """Clear the entire Pinecone knowledge namespace."""
        index = self._get_index()
        try:
            index.delete(delete_all=True, namespace=KNOWLEDGE_NAMESPACE)
            logger.info("Cleared entire knowledge namespace in Pinecone")
        except Exception as e:
            logger.error(f"Failed to clear knowledge namespace: {e}")

    def clear_derived_knowledge(self) -> None:
        """Clear capabilities from Pinecone and all derived configs from MongoDB."""
        index = self._get_index()
        try:
            # Clear capabilities in Pinecone vector DB
            index.delete(delete_all=True, namespace=KNOWLEDGE_NAMESPACE)
            logger.info("Cleared Pinecone knowledge index to remove stale capabilities")
        except Exception as e:
            if "Namespace not found" in str(e) or "404" in str(e):
                logger.info("Knowledge namespace already empty or not found (ignoring).")
            else:
                logger.error(f"Failed to clear Pinecone knowledge index: {e}")
            
        try:
            db = self._get_db()
            # Clear all derived configuration entries in the company database
            db.company_config.update_one(
                {"config_type": "certifications"},
                {"$set": {"certifications": {}}},
                upsert=True
            )
            db.company_config.update_one(
                {"config_type": "pricing_rules"},
                {"$set": {"rules": {}}},
                upsert=True
            )
            db.company_config.update_one(
                {"config_type": "legal_templates"},
                {"$set": {"templates": []}},
                upsert=True
            )
            db.company_config.update_one(
                {"config_type": "company_profile"},
                {"$set": {"profile": {}}},
                upsert=True
            )
            logger.info("Cleared MongoDB derived configs (certifications, pricing, legal, profile)")
        except Exception as e:
            logger.error(f"Failed to clear MongoDB derived configs: {e}")

    # ── Query: all types (no filter) ─────────────────────

    def query_all_types(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Semantic search over ALL knowledge documents (no doc_type filter)."""
        index = self._get_index()
        query_emb = self._embedder.embed_single(query)

        results = index.query(
            vector=query_emb,
            top_k=top_k,
            namespace=KNOWLEDGE_NAMESPACE,
            include_metadata=True,
        )

        return [
            {
                "id": m["id"],
                "score": m["score"],
                "text": m.get("metadata", {}).get("text", ""),
                "doc_type": m.get("metadata", {}).get("doc_type", ""),
                "metadata": m.get("metadata", {}),
            }
            for m in results.get("matches", [])
        ]

    # ── Query: by specific type ──────────────────────────

    def query_by_type(self, query: str, doc_type: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Semantic search filtered by a specific doc_type."""
        index = self._get_index()
        query_emb = self._embedder.embed_single(query)

        results = index.query(
            vector=query_emb,
            top_k=top_k,
            namespace=KNOWLEDGE_NAMESPACE,
            include_metadata=True,
            filter={"doc_type": doc_type},
        )

        return [
            {
                "id": m["id"],
                "score": m["score"],
                "text": m.get("metadata", {}).get("text", ""),
                "doc_type": doc_type,
                "metadata": m.get("metadata", {}),
            }
            for m in results.get("matches", [])
        ]

    # ── Query: capabilities (Pinecone) ───────────────────

    def query_capabilities(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Semantic search over company capabilities."""
        return self.query_by_type(query, "capability", top_k)

    # ── Query: past proposals (Pinecone) ─────────────────

    def query_past_proposals(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        """Semantic search over past winning proposals."""
        return self.query_by_type(query, "past_proposal", top_k)

    # ── Query: certifications (MongoDB) ──────────────────

    def query_certifications(self) -> dict[str, bool]:
        """Return map of certification name → whether we hold it."""
        db = self._get_db()
        doc = db.company_config.find_one({"config_type": "certifications"})
        if doc and "certifications" in doc:
            return doc["certifications"]
        # Default if MongoDB is empty
        return {}

    # ── Query: pricing rules (MongoDB) ───────────────────

    def query_pricing_rules(self) -> dict[str, Any]:
        """Return pricing formula parameters from MongoDB.

        Returns empty dict if no rules have been seeded. Pricing data
        should be extracted from KB documents via the sync pipeline.
        """
        db = self._get_db()
        doc = db.company_config.find_one({"config_type": "pricing_rules"})
        if doc and "rules" in doc:
            return doc["rules"]
        logger.warning(
            "[KnowledgeStore] No pricing rules found in MongoDB. "
            "Upload company documents to extract pricing data."
        )
        return {}

    # ── Query / Upsert: company profile (MongoDB) ─────────

    def query_company_profile(self) -> dict[str, Any]:
        """Return company profile (name, description, etc.) from MongoDB."""
        db = self._get_db()
        doc = db.company_config.find_one({"config_type": "company_profile"})
        if doc and "profile" in doc:
            return doc["profile"]
        return {}

    def upsert_company_profile(self, profile: dict[str, Any]) -> None:
        """Create or update the company profile in MongoDB."""
        db = self._get_db()
        db.company_config.update_one(
            {"config_type": "company_profile"},
            {"$set": {"config_type": "company_profile", "profile": profile}},
            upsert=True,
        )
        logger.info(f"Upserted company profile: {list(profile.keys())}")

    # ── Query: legal templates (MongoDB) ─────────────────

    def query_legal_templates(self) -> list[dict[str, str]]:
        """Return company legal templates for clause comparison."""
        db = self._get_db()
        doc = db.company_config.find_one({"config_type": "legal_templates"})
        if doc and "templates" in doc:
            return doc["templates"]
        # Default if MongoDB is empty
        return []
