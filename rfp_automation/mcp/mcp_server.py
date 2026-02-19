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
    ) -> list[dict[str, Any]]:
        """Convenience: semantic search over company capabilities."""
        return self.knowledge_base.query_capabilities(query, top_k)

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
