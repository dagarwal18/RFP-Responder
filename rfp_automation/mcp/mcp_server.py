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
        from .vector_store.bm25_store import BM25Store
        from .rules.policy_rules import PolicyRules
        from .rules.validation_rules import ValidationRules
        from .rules.commercial_rules import CommercialRules
        from .rules.legal_rules import LegalRules
        from rfp_automation.services.section_store import SectionStore

        self.rfp_store = RFPVectorStore()
        self.knowledge_base = KnowledgeStore()
        self._bm25_store = BM25Store()
        self.policy_rules = PolicyRules()
        self.validation_rules = ValidationRules()
        self.commercial_rules = CommercialRules()
        self.legal_rules = LegalRules()
        self.section_store = SectionStore()

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
        logger.debug(f"[MCPService] store_rfp_chunks: rfp_id={rfp_id}, {len(chunks)} chunks")
        
        # Save full texts to Mongo/JSON
        self.section_store.save_sections(rfp_id, chunks)

        extra = {"source_file": source_file} if source_file else {}
        count = self.rfp_store.embed_chunks(rfp_id, chunks, extra_metadata=extra)

        # Also build BM25 sparse index for hybrid retrieval
        try:
            self._bm25_store.index(rfp_id, chunks)
        except Exception as e:
            logger.warning(f"[MCPService] BM25 indexing failed for {rfp_id}: {e}")

        logger.info(f"[MCPService] Stored {count} vectors for {rfp_id}")
        return count

    def load_rfp_sections(self, rfp_id: str) -> dict[str, dict[str, Any]]:
        """Load full text sections from the section store."""
        return self.section_store.load_sections(rfp_id)

    def _hydrate_chunks(self, rfp_id: str, chunks: list[dict[str, Any]]) -> None:
        """Inject full text from MongoDB/JSON into retrieved Pinecone chunks."""
        if not rfp_id or not chunks:
            return
            
        full_sections = self.section_store.load_sections(rfp_id)
        hydrated_count = 0
        
        for chunk in chunks:
            chunk_id = chunk.get("metadata", {}).get("chunk_id")
            if not chunk_id:
                # Fallback to id parsing if chunk_id not in metadata
                # Format is usually {rfp_id}_chunk_{index}
                pass
                
            if chunk_id and chunk_id in full_sections:
                # Replace the truncated text with the full text
                full_text = full_sections[chunk_id].get("text", "")
                if full_text:
                    chunk["text"] = full_text
                    # Also update metadata for consistency if agents read it
                    chunk["metadata"]["text"] = full_text
                    hydrated_count += 1
                    
        if hydrated_count < len(chunks):
            logger.warning(
                f"[MCPService] Hydration mismatch on {rfp_id}: "
                f"Hydrated {hydrated_count}/{len(chunks)} chunks"
            )

    # ── Convenience: RFP query ───────────────────────────

    def query_rfp(
        self,
        query: str,
        rfp_id: str = "",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Convenience: semantic search over RFP chunks."""
        logger.debug(f"[MCPService] query_rfp: q={query[:60]!r}, rfp_id={rfp_id}, top_k={top_k}")
        results = self.rfp_store.query(query, rfp_id, top_k)
        if rfp_id:
            self._hydrate_chunks(rfp_id, results)
        logger.debug(f"[MCPService] query_rfp returned {len(results)} results")
        return results

    # ── Convenience: Hybrid RFP query ────────────────────

    def query_rfp_hybrid(
        self,
        query: str,
        rfp_id: str = "",
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Hybrid retrieval: merge Pinecone dense + BM25 sparse results
        using Reciprocal Rank Fusion.

        Falls back to dense-only if no BM25 index exists.
        """
        logger.debug(
            f"[MCPService] query_rfp_hybrid: q={query[:60]!r}, "
            f"rfp_id={rfp_id}, top_k={top_k}"
        )

        # Dense retrieval (existing Pinecone)
        dense_results = self.query_rfp(query, rfp_id, top_k=top_k * 2)

        # Sparse retrieval (BM25)
        sparse_results = self._bm25_store.query(rfp_id, query, top_k=top_k * 2)

        if not sparse_results:
            # No BM25 index or no matches — return dense only
            logger.debug(
                f"[MCPService] No BM25 results for {rfp_id}, using dense only"
            )
            return dense_results[:top_k]

        fused = self._reciprocal_rank_fusion(
            dense_results, sparse_results, top_k
        )
        logger.info(
            f"[MCPService] Hybrid query returned {len(fused)} results "
            f"(dense={len(dense_results)}, sparse={len(sparse_results)})"
        )
        return fused

    @staticmethod
    def _reciprocal_rank_fusion(
        dense: list[dict[str, Any]],
        sparse: list[dict[str, Any]],
        top_k: int,
        k: int = 60,
    ) -> list[dict[str, Any]]:
        """
        Merge two ranked lists using Reciprocal Rank Fusion.

        score(doc) = Σ 1/(k + rank)

        k=60 is the standard RRF constant (from the original paper).
        """
        scores: dict[str, float] = {}     # chunk_id → RRF score
        chunk_map: dict[str, dict] = {}   # chunk_id → best chunk dict

        # Score dense results
        for rank, item in enumerate(dense):
            cid = (
                item.get("metadata", {}).get("chunk_id")
                or item.get("chunk_id")
                or f"dense_{rank}"
            )
            scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank)
            chunk_map[cid] = item

        # Score sparse results
        for rank, item in enumerate(sparse):
            cid = item.get("chunk_id", f"sparse_{rank}")
            scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank)
            if cid not in chunk_map:
                chunk_map[cid] = item

        # Sort by RRF score descending, take top_k
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [chunk_map[cid] for cid, _ in ranked if cid in chunk_map]

    # ── Convenience: RFP full retrieval ────────────────────

    def query_rfp_all_chunks(
        self,
        rfp_id: str,
        top_k: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve all chunks for an RFP (for full-document classification)."""
        logger.debug(f"[MCPService] query_rfp_all_chunks: rfp_id={rfp_id}, top_k={top_k}")
        results = self.rfp_store.query_all(rfp_id, top_k)
        self._hydrate_chunks(rfp_id, results)
        logger.debug(f"[MCPService] query_rfp_all_chunks returned {len(results)} chunks")
        return results

    # ── Convenience: RFP deterministic fetch ───────────────

    def fetch_all_rfp_chunks(
        self,
        rfp_id: str,
    ) -> list[dict[str, Any]]:
        """
        Deterministically fetch ALL chunks for an RFP using list+fetch.

        Unlike query_rfp / query_rfp_all_chunks, this does NOT use embedding
        similarity. It retrieves every vector in the namespace, sorted by
        chunk_index (document order).
        """
        logger.debug(f"[MCPService] fetch_all_rfp_chunks: rfp_id={rfp_id}")
        results = self.rfp_store.fetch_all_vectors(rfp_id)
        self._hydrate_chunks(rfp_id, results)
        logger.debug(
            f"[MCPService] fetch_all_rfp_chunks returned {len(results)} chunks (hydrated)"
        )
        return results

    # ── Convenience: Knowledge query ─────────────────────

    def query_knowledge(
        self,
        query: str,
        top_k: int = 5,
        doc_type: str = "",
    ) -> list[dict[str, Any]]:
        """Convenience: semantic search over company knowledge. If doc_type is empty, search all."""
        logger.debug(f"[MCPService] query_knowledge: q={query[:60]!r}, doc_type={doc_type!r}, top_k={top_k}")
        if doc_type:
            results = self.knowledge_base.query_by_type(query, doc_type, top_k)
        else:
            results = self.knowledge_base.query_all_types(query, top_k)
        logger.debug(f"[MCPService] query_knowledge returned {len(results)} results")
        return results

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

    # ── Pre-extracted policies (from JSON file) ────────

    def get_extracted_policies(self, category: str = "") -> list[dict[str, Any]]:
        """Read pre-extracted policies from the JSON file, optionally filtered by category."""
        from rfp_automation.services.policy_extraction_service import PolicyExtractionService
        policies = PolicyExtractionService.get_all_policies()
        if category:
            policies = [p for p in policies if p.get("category") == category]
        logger.debug(f"[MCPService] get_extracted_policies(category={category!r}): {len(policies)} policies")
        return policies

    def get_certifications_from_policies(self) -> dict[str, bool]:
        """Derive a cert map from extracted policies where category='certification'."""
        cert_policies = self.get_extracted_policies(category="certification")
        return {p.get("policy_text", ""): True for p in cert_policies if p.get("policy_text")}

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
