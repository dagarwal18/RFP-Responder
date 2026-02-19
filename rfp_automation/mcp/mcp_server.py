"""
MCPService — the ONLY class agents should import.

This is the facade over:
  • RFP Vector Store   (embed + query incoming RFP chunks)
  • Knowledge Base     (company capabilities, certs, pricing, legal templates)
  • Rules Engine       (policy / validation / commercial-legal gates)

Internally the stores use embeddings/ helpers
but agents never see those.
"""

from __future__ import annotations

import logging
from typing import Any

from rfp_automation.services.parsing_service import ParsingService

logger = logging.getLogger(__name__)


class MCPService:
    """
    Facade over all MCP layers.
    Agents depend on this single class.

    Usage in any agent:
        from rfp_automation.mcp import MCPService
        mcp = MCPService()
        mcp.store_rfp_document(rfp_id, raw_text, metadata)
        chunks = mcp.query_rfp("security requirements", rfp_id)
    """

    def __init__(self):
        from .vector_store.rfp_store import RFPVectorStore
        from .vector_store.knowledge_store import KnowledgeStore
        from .rules.policy_rules import PolicyRules
        from .rules.validation_rules import ValidationRules
        from .rules.commercial_rules import CommercialRules
        from .rules.legal_rules import LegalRules

        self.rfp_store = RFPVectorStore()
        self.knowledge_base = KnowledgeStore()
        self.policy_rules = PolicyRules()
        self.validation_rules = ValidationRules()
        self.commercial_rules = CommercialRules()
        self.legal_rules = LegalRules()

    # ── Convenience: RFP document storage ────────────────

    def store_rfp_document(
        self,
        rfp_id: str,
        raw_text: str,
        metadata: dict[str, Any] | None = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> int:
        """
        Convenience: chunk raw_text, embed, and store into Pinecone.
        Used by Intake Agent.  Returns chunk count.
        """
        return self.rfp_store.embed_document(
            rfp_id=rfp_id,
            raw_text=raw_text,
            metadata=metadata,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    # ── Convenience: Structured chunk storage ────────────

    def store_rfp_chunks(
        self,
        rfp_id: str,
        chunks: list[dict[str, Any]],
        source_file: str = "",
    ) -> int:
        """
        Embed pre-structured chunks and store into Pinecone.
        Each chunk must have: chunk_id, content_type, section_hint,
        text, page_start, page_end.
        Returns vector count.
        """
        extra = {"source_file": source_file} if source_file else {}
        count = self.rfp_store.embed_chunks(rfp_id, chunks, extra_metadata=extra)
        logger.info(f"[MCPService] Stored {count} vectors for {rfp_id}")
        return count

    # ── Convenience: RFP query ───────────────────────────

    def query_rfp(
        self,
        query: str,
        rfp_id: str = "",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Convenience: semantic search over RFP chunks."""
        return self.rfp_store.query(query, rfp_id, top_k)

    # ── Convenience: RFP full retrieval ────────────────────

    def query_rfp_all_chunks(
        self,
        rfp_id: str,
        top_k: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve all chunks for an RFP (for full-document classification)."""
        return self.rfp_store.query_all(rfp_id, top_k)

    # ── Convenience: Knowledge query ─────────────────────

    def query_knowledge(
        self,
        query: str,
        top_k: int = 5,
        doc_type: str = "",
    ) -> list[dict[str, Any]]:
        """Convenience: semantic search over company knowledge. If doc_type is empty, search all."""
        if doc_type:
            return self.knowledge_base.query_by_type(query, doc_type, top_k)
        return self.knowledge_base.query_all_types(query, top_k)

    # ── Knowledge base admin ─────────────────────────────

    def ingest_knowledge_doc(
        self,
        doc_type: str,
        texts: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> int:
        """Ingest company documents into the knowledge namespace."""
        return self.knowledge_base.ingest_company_docs(texts, metadatas, doc_type)

    def store_knowledge_config(
        self,
        config_type: str,
        data: dict[str, Any],
    ) -> None:
        """Store structured config (certifications, pricing, legal) in MongoDB."""
        db = self.knowledge_base._get_db()
        db.company_config.update_one(
            {"config_type": config_type},
            {"$set": {"config_type": config_type, **data}},
            upsert=True,
        )
        logger.info(f"[MCPService] Stored {config_type} config in MongoDB")

    def get_knowledge_stats(self) -> dict[str, Any]:
        """Return knowledge base stats: Pinecone vectors + MongoDB configs."""
        stats: dict[str, Any] = {
            "pinecone": {"total_vectors": 0, "namespaces": {}},
            "mongodb": {"configs": []},
        }

        try:
            index = self.knowledge_base._get_index()
            idx_stats = index.describe_index_stats()
            total = getattr(idx_stats, "total_vector_count", 0)
            namespaces_raw = getattr(idx_stats, "namespaces", {})

            ns_dict = {}
            if isinstance(namespaces_raw, dict):
                for k, v in namespaces_raw.items():
                    ns_dict[k] = getattr(v, "vector_count", 0) if not isinstance(v, dict) else v.get("vector_count", 0)
            stats["pinecone"] = {"total_vectors": total, "namespaces": ns_dict}
        except Exception as e:
            stats["pinecone"]["error"] = str(e)

        try:
            db = self.knowledge_base._get_db()
            configs = list(db.company_config.find({}, {"_id": 0, "config_type": 1}))
            stats["mongodb"]["configs"] = [c["config_type"] for c in configs]
        except Exception as e:
            stats["mongodb"]["error"] = str(e)

        return stats

    # ── Health check ─────────────────────────────────────

    async def health_check(self) -> dict[str, Any]:
        """Check connectivity of all sub-services."""
        status: dict[str, Any] = {
            "rfp_store": False,
            "knowledge_base": False,
            "rules_engine": True,  # rules are local/cached
        }

        try:
            self.rfp_store._get_index()
            status["rfp_store"] = True
        except Exception as e:
            status["rfp_store_error"] = str(e)

        try:
            self.knowledge_base._get_index()
            status["knowledge_base"] = True
        except Exception as e:
            status["knowledge_base_error"] = str(e)

        return status
