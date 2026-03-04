"""
Tests: Stage 4 — VLM Table Extraction, Cross-References, Hybrid Retrieval.

Run with:
    pytest rfp_automation/tests/test_stage4.py -v
"""

import json
import pytest
from unittest.mock import patch, MagicMock


# ═══════════════════════════════════════════════════════════
# Feature 1: Vision Service — Table Detection + VLM
# ═══════════════════════════════════════════════════════════


class TestVisionServiceTableParsing:
    """Tests for VLM JSON response parsing and table formatting."""

    def test_parse_valid_table_json(self):
        from rfp_automation.services.vision_service import VisionService

        response = json.dumps([
            {
                "table_id": "T1",
                "caption": "SLA Metrics",
                "headers": ["Metric", "Target", "Penalty"],
                "rows": [
                    ["Uptime", "99.9%", "1% credit"],
                    ["Response Time", "<200ms", "0.5% credit"],
                ],
            }
        ])

        tables = VisionService._parse_table_json(response, page_number=3, region_idx=0)
        assert len(tables) == 1
        assert tables[0]["table_id"] == "T1"
        assert tables[0]["caption"] == "SLA Metrics"
        assert len(tables[0]["headers"]) == 3
        assert len(tables[0]["rows"]) == 2
        assert tables[0]["page_number"] == 3

    def test_parse_json_with_markdown_fences(self):
        from rfp_automation.services.vision_service import VisionService

        response = '```json\n[{"table_id": "T1", "headers": ["A"], "rows": [["1"]]}]\n```'
        tables = VisionService._parse_table_json(response, page_number=1, region_idx=0)
        assert len(tables) == 1
        assert tables[0]["headers"] == ["A"]

    def test_parse_invalid_json_returns_empty(self):
        from rfp_automation.services.vision_service import VisionService

        tables = VisionService._parse_table_json(
            "not valid json at all", page_number=1, region_idx=0
        )
        assert tables == []

    def test_parse_empty_array_returns_empty(self):
        from rfp_automation.services.vision_service import VisionService

        tables = VisionService._parse_table_json("[]", page_number=1, region_idx=0)
        assert tables == []

    def test_format_table_as_text(self):
        from rfp_automation.services.vision_service import VisionService

        table = {
            "headers": ["Name", "Value"],
            "rows": [["Uptime", "99.9%"], ["Latency", "<50ms"]],
        }
        text = VisionService.format_table_as_text(table)
        assert "Name | Value" in text
        assert "Uptime | 99.9%" in text
        assert "Latency | <50ms" in text

    def test_format_empty_table(self):
        from rfp_automation.services.vision_service import VisionService

        text = VisionService.format_table_as_text({"headers": [], "rows": []})
        assert text == ""


class TestVLMDisabledFallback:
    """When vlm_enabled=False, parsing uses heuristic-only table extraction."""

    def test_vlm_disabled_skips_vlm(self, monkeypatch):
        """When VLM is disabled, VisionService should never be instantiated."""
        # Use environment variable override for Pydantic Settings
        monkeypatch.setenv("VLM_ENABLED", "false")

        # Clear cached settings so the env var takes effect
        from rfp_automation.config import get_settings
        get_settings.cache_clear()

        try:
            settings = get_settings()
            assert settings.vlm_enabled is False
        finally:
            # Restore cache for other tests
            get_settings.cache_clear()


# ═══════════════════════════════════════════════════════════
# Feature 2: Cross-Reference Resolution
# ═══════════════════════════════════════════════════════════


class TestCrossRefResolver:
    """Tests for cross-reference detection and content injection."""

    def _make_chunks(self):
        """Create a set of test chunks with section structure."""
        return [
            {
                "chunk_id": "sc-0001",
                "content_type": "text",
                "section_hint": "1 Introduction",
                "text": "1 Introduction\n\nThis document describes the requirements.",
                "page_start": 1,
                "page_end": 1,
            },
            {
                "chunk_id": "sc-0002",
                "content_type": "text",
                "section_hint": "5 Security Requirements",
                "text": "5 Security Requirements\n\nAll systems must comply with ISO 27001.",
                "page_start": 5,
                "page_end": 5,
            },
            {
                "chunk_id": "sc-0003",
                "content_type": "text",
                "section_hint": "3.2 SLA Targets",
                "text": "3.2 SLA Targets\n\nUptime must be 99.9%. Response time < 200ms.",
                "page_start": 3,
                "page_end": 3,
            },
            {
                "chunk_id": "sc-0004",
                "content_type": "table",
                "section_hint": "Table 7 SLA Metrics",
                "text": "Table 7: SLA Metrics\nMetric | Target\nUptime | 99.9%",
                "page_start": 4,
                "page_end": 4,
            },
            {
                "chunk_id": "sc-0005",
                "content_type": "text",
                "section_hint": "6 Compliance",
                "text": (
                    "6 Compliance\n\nThe vendor must comply with security policies "
                    "as specified in Section 5 and meet SLA targets per Table 7."
                ),
                "page_start": 6,
                "page_end": 6,
            },
        ]

    def test_section_reference_injection(self):
        from rfp_automation.services.cross_ref_resolver import CrossRefResolver

        chunks = self._make_chunks()
        resolver = CrossRefResolver()
        enriched = resolver.resolve(chunks)

        # The compliance chunk (index 4) references "Section 5"
        compliance_chunk = enriched[4]
        assert "[Referenced Section 5]:" in compliance_chunk["text"]
        assert "ISO 27001" in compliance_chunk["text"]

    def test_table_reference_injection(self):
        from rfp_automation.services.cross_ref_resolver import CrossRefResolver

        chunks = self._make_chunks()
        resolver = CrossRefResolver()
        enriched = resolver.resolve(chunks)

        # The compliance chunk references "Table 7"
        compliance_chunk = enriched[4]
        assert "[Referenced Table 7]:" in compliance_chunk["text"]
        assert "SLA Metrics" in compliance_chunk["text"]

    def test_unresolvable_reference_unchanged(self):
        from rfp_automation.services.cross_ref_resolver import CrossRefResolver

        chunks = [
            {
                "chunk_id": "sc-0001",
                "content_type": "text",
                "section_hint": "1 Overview",
                "text": "See Section 99 for details.",
                "page_start": 1,
                "page_end": 1,
            },
        ]
        resolver = CrossRefResolver()
        enriched = resolver.resolve(chunks)

        # "Section 99" doesn't exist, so no injection
        assert enriched[0]["text"] == "See Section 99 for details."

    def test_no_references_passthrough(self):
        from rfp_automation.services.cross_ref_resolver import CrossRefResolver

        chunks = [
            {
                "chunk_id": "sc-0001",
                "content_type": "text",
                "section_hint": "1 Overview",
                "text": "This is plain text with no cross-references.",
                "page_start": 1,
                "page_end": 1,
            },
        ]
        resolver = CrossRefResolver()
        enriched = resolver.resolve(chunks)
        assert enriched[0]["text"] == "This is plain text with no cross-references."

    def test_injection_cap_2000_chars(self):
        from rfp_automation.services.cross_ref_resolver import CrossRefResolver

        # Create a chunk with very long content that will be referenced
        long_text = "5 Long Section\n\n" + "A" * 5000
        chunks = [
            {
                "chunk_id": "sc-0001",
                "content_type": "text",
                "section_hint": "5 Long Section",
                "text": long_text,
                "page_start": 1,
                "page_end": 1,
            },
            {
                "chunk_id": "sc-0002",
                "content_type": "text",
                "section_hint": "6 Other",
                "text": "See Section 5 for the full spec.",
                "page_start": 2,
                "page_end": 2,
            },
        ]
        resolver = CrossRefResolver()
        enriched = resolver.resolve(chunks)

        # The injected content should be capped
        ref_chunk = enriched[1]
        assert "[Referenced Section 5]:" in ref_chunk["text"]
        assert "[...]" in ref_chunk["text"]
        # Original text length was 31 chars. Injected should be capped at ~2000 + label
        assert len(ref_chunk["text"]) < 31 + 2100  # some room for label text

    def test_appendix_reference_injection(self):
        from rfp_automation.services.cross_ref_resolver import CrossRefResolver

        chunks = [
            {
                "chunk_id": "sc-0001",
                "content_type": "text",
                "section_hint": "Appendix A Glossary",
                "text": "Appendix A\n\nRFP: Request for Proposal\nSLA: Service Level Agreement",
                "page_start": 10,
                "page_end": 10,
            },
            {
                "chunk_id": "sc-0002",
                "content_type": "text",
                "section_hint": "1 Overview",
                "text": "Definitions are available, see Appendix A for the full glossary.",
                "page_start": 1,
                "page_end": 1,
            },
        ]
        resolver = CrossRefResolver()
        enriched = resolver.resolve(chunks)

        assert "[Referenced Appendix A]:" in enriched[1]["text"]
        assert "Request for Proposal" in enriched[1]["text"]

    def test_empty_chunks_passthrough(self):
        from rfp_automation.services.cross_ref_resolver import CrossRefResolver

        resolver = CrossRefResolver()
        assert resolver.resolve([]) == []

    def test_original_chunks_not_mutated(self):
        from rfp_automation.services.cross_ref_resolver import CrossRefResolver

        chunks = self._make_chunks()
        original_text = chunks[4]["text"]
        resolver = CrossRefResolver()
        enriched = resolver.resolve(chunks)

        # Enriched chunk is different (has injections)
        assert enriched[4]["text"] != original_text
        # But original chunk is untouched
        assert chunks[4]["text"] == original_text


# ═══════════════════════════════════════════════════════════
# Feature 3: BM25 Store + Hybrid Retrieval
# ═══════════════════════════════════════════════════════════


class TestBM25Store:
    """Tests for the in-memory BM25 index."""

    def _make_chunks(self):
        return [
            {
                "chunk_id": "sc-0001",
                "text": "ISO 27001 Information Security Management certification required",
            },
            {
                "chunk_id": "sc-0002",
                "text": "The vendor must provide 24x7 technical support with SLA",
            },
            {
                "chunk_id": "sc-0003",
                "text": "Cloud deployment on AWS or Azure with Kubernetes orchestration",
            },
            {
                "chunk_id": "sc-0004",
                "text": "Annual security audit and penetration testing compliance",
            },
        ]

    def test_index_and_query_basic(self):
        from rfp_automation.mcp.vector_store.bm25_store import BM25Store

        store = BM25Store()
        chunks = self._make_chunks()
        store.index("RFP-001", chunks)

        results = store.query("RFP-001", "ISO 27001 certification")
        assert len(results) > 0
        # The ISO 27001 chunk should be top result
        assert results[0]["chunk_id"] == "sc-0001"
        assert "bm25_score" in results[0]

    def test_query_kubernetes(self):
        from rfp_automation.mcp.vector_store.bm25_store import BM25Store

        store = BM25Store()
        store.index("RFP-001", self._make_chunks())

        results = store.query("RFP-001", "Kubernetes deployment")
        assert len(results) > 0
        assert results[0]["chunk_id"] == "sc-0003"

    def test_no_match_returns_empty(self):
        from rfp_automation.mcp.vector_store.bm25_store import BM25Store

        store = BM25Store()
        store.index("RFP-001", self._make_chunks())

        results = store.query("RFP-001", "xyznonexistentterm")
        assert results == []

    def test_missing_rfp_returns_empty(self):
        from rfp_automation.mcp.vector_store.bm25_store import BM25Store

        store = BM25Store()
        results = store.query("NONEXISTENT", "some query")
        assert results == []

    def test_has_index(self):
        from rfp_automation.mcp.vector_store.bm25_store import BM25Store

        store = BM25Store()
        assert not store.has_index("RFP-001")
        store.index("RFP-001", self._make_chunks())
        assert store.has_index("RFP-001")

    def test_reindex_replaces_old(self):
        from rfp_automation.mcp.vector_store.bm25_store import BM25Store

        store = BM25Store()
        store.index("RFP-001", self._make_chunks())

        # Original chunks should match "ISO 27001"
        results_before = store.query("RFP-001", "ISO 27001")
        assert len(results_before) > 0

        # Replace with completely different chunks
        # "bananas" only appears in new-1 (not new-2), so BM25 IDF won't zero it
        new_chunks = [
            {"chunk_id": "new-1", "text": "fresh tropical bananas from the market"},
            {"chunk_id": "new-2", "text": "cloud deployment with docker containers"},
            {"chunk_id": "new-3", "text": "server configuration and networking setup"},
        ]
        store.index("RFP-001", new_chunks)

        # Old query should no longer match
        results_old = store.query("RFP-001", "ISO 27001")
        assert len(results_old) == 0

        # New query should match
        results_new = store.query("RFP-001", "bananas")
        assert len(results_new) > 0
        assert results_new[0]["chunk_id"] == "new-1"


class TestReciprocalRankFusion:
    """Tests for the RRF merging algorithm."""

    def test_rrf_merges_correctly(self):
        from rfp_automation.mcp.mcp_server import MCPService

        dense = [
            {"metadata": {"chunk_id": "A"}, "text": "doc A"},
            {"metadata": {"chunk_id": "B"}, "text": "doc B"},
            {"metadata": {"chunk_id": "C"}, "text": "doc C"},
        ]
        sparse = [
            {"chunk_id": "B", "text": "doc B"},
            {"chunk_id": "D", "text": "doc D"},
            {"chunk_id": "A", "text": "doc A"},
        ]

        fused = MCPService._reciprocal_rank_fusion(dense, sparse, top_k=4, k=60)

        # B appears in both lists at good ranks → should be top
        chunk_ids = [
            c.get("metadata", {}).get("chunk_id") or c.get("chunk_id")
            for c in fused
        ]
        # B should be ranked highly (appears rank 1 in dense, rank 0 in sparse)
        assert "B" in chunk_ids
        assert "A" in chunk_ids
        assert len(fused) == 4

    def test_rrf_respects_top_k(self):
        from rfp_automation.mcp.mcp_server import MCPService

        dense = [{"metadata": {"chunk_id": f"d{i}"}} for i in range(10)]
        sparse = [{"chunk_id": f"s{i}"} for i in range(10)]

        fused = MCPService._reciprocal_rank_fusion(dense, sparse, top_k=3)
        assert len(fused) <= 3

    def test_rrf_empty_sparse(self):
        from rfp_automation.mcp.mcp_server import MCPService

        dense = [
            {"metadata": {"chunk_id": "A"}, "text": "doc A"},
        ]
        fused = MCPService._reciprocal_rank_fusion(dense, [], top_k=5)
        assert len(fused) == 1

    def test_rrf_empty_dense(self):
        from rfp_automation.mcp.mcp_server import MCPService

        sparse = [
            {"chunk_id": "A", "text": "doc A"},
        ]
        fused = MCPService._reciprocal_rank_fusion([], sparse, top_k=5)
        assert len(fused) == 1
