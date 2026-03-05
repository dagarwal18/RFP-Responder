"""
Tests: B1 Extraction Overhaul — integration-style tests for the refactored
requirement extraction pipeline.

Validates:
  - Embedding-based deduplication merges near-duplicates
  - Text-based deduplication fallback works
  - Coverage validation triggers warning when appropriate
  - Deterministic ID assignment across sections
  - Table content is included in extraction input
  - Semantic chunking preserves logical boundaries
"""

import json
import logging
import pytest

from rfp_automation.models.enums import (
    RequirementType,
    RequirementClassification,
    RequirementCategory,
    ImpactLevel,
)
from rfp_automation.models.schemas import Requirement
from rfp_automation.services.parsing_service import ParsingService


# ═══════════════════════════════════════════════════════════
# Deduplication Tests
# ═══════════════════════════════════════════════════════════


class TestDeduplication:
    """Tests for the dedup logic in RequirementsExtractionAgent."""

    @staticmethod
    def _make_req(text: str, req_id: str = "REQ-0001") -> Requirement:
        return Requirement(
            requirement_id=req_id,
            text=text,
            type=RequirementType.MANDATORY,
            classification=RequirementClassification.FUNCTIONAL,
            category=RequirementCategory.TECHNICAL,
            impact=ImpactLevel.HIGH,
            source_section="Test",
        )

    def test_text_dedup_removes_exact_duplicates(self):
        from rfp_automation.agents.requirement_extraction_agent import (
            RequirementsExtractionAgent,
        )

        reqs = [
            self._make_req("The vendor shall provide SSO.", "REQ-0001"),
            self._make_req("The vendor shall provide SSO.", "REQ-0002"),
            self._make_req("Data must be encrypted at rest.", "REQ-0003"),
        ]
        unique = RequirementsExtractionAgent._text_dedup(reqs)
        assert len(unique) == 2
        assert unique[0].text == "The vendor shall provide SSO."
        assert unique[1].text == "Data must be encrypted at rest."

    def test_text_dedup_case_insensitive(self):
        from rfp_automation.agents.requirement_extraction_agent import (
            RequirementsExtractionAgent,
        )

        reqs = [
            self._make_req("The Vendor SHALL Provide SSO.", "REQ-0001"),
            self._make_req("the vendor shall provide sso.", "REQ-0002"),
        ]
        unique = RequirementsExtractionAgent._text_dedup(reqs)
        assert len(unique) == 1

    def test_text_dedup_whitespace_normalization(self):
        from rfp_automation.agents.requirement_extraction_agent import (
            RequirementsExtractionAgent,
        )

        reqs = [
            self._make_req("The vendor  shall   provide SSO.", "REQ-0001"),
            self._make_req("The vendor shall provide SSO.", "REQ-0002"),
        ]
        unique = RequirementsExtractionAgent._text_dedup(reqs)
        assert len(unique) == 1

    def test_dedup_fallback_on_embedding_failure(self):
        """If embedding dedup fails, should fall back to text dedup."""
        from rfp_automation.agents.requirement_extraction_agent import (
            RequirementsExtractionAgent,
        )

        reqs = [
            self._make_req("The vendor shall provide SSO.", "REQ-0001"),
            self._make_req("The vendor shall provide SSO.", "REQ-0002"),
            self._make_req("Data must be encrypted.", "REQ-0003"),
        ]
        # _deduplicate will try embedding first, fail, then use text dedup
        unique = RequirementsExtractionAgent._deduplicate(reqs, threshold=0.95)
        assert len(unique) == 2


# ═══════════════════════════════════════════════════════════
# Coverage Validation Tests
# ═══════════════════════════════════════════════════════════


class TestCoverageValidation:

    @staticmethod
    def _make_req(text: str) -> Requirement:
        return Requirement(
            requirement_id="REQ-0001",
            text=text,
            type=RequirementType.MANDATORY,
        )

    def test_coverage_good_ratio(self, caplog):
        from rfp_automation.agents.requirement_extraction_agent import (
            RequirementsExtractionAgent,
        )

        reqs = [self._make_req(f"Req {i}") for i in range(10)]
        with caplog.at_level(logging.WARNING):
            RequirementsExtractionAgent._validate_coverage(
                reqs, total_indicator_count=12, warn_ratio=0.6
            )
        # 10 / 12 = 0.83 > 0.6 → no warning
        assert "LOW COVERAGE" not in caplog.text

    def test_coverage_low_ratio_triggers_warning(self, caplog):
        from rfp_automation.agents.requirement_extraction_agent import (
            RequirementsExtractionAgent,
        )

        reqs = [self._make_req("Req 1"), self._make_req("Req 2")]
        with caplog.at_level(logging.WARNING):
            RequirementsExtractionAgent._validate_coverage(
                reqs, total_indicator_count=20, warn_ratio=0.6
            )
        # 2 / 20 = 0.1 < 0.6 → warning
        assert "LOW COVERAGE" in caplog.text

    def test_coverage_zero_indicators(self, caplog):
        from rfp_automation.agents.requirement_extraction_agent import (
            RequirementsExtractionAgent,
        )

        reqs = [self._make_req("Req 1")]
        with caplog.at_level(logging.INFO):
            RequirementsExtractionAgent._validate_coverage(
                reqs, total_indicator_count=0, warn_ratio=0.6
            )
        # 0 indicators → should not crash
        assert "LOW COVERAGE" not in caplog.text


# ═══════════════════════════════════════════════════════════
# Deterministic ID Assignment Tests
# ═══════════════════════════════════════════════════════════


class TestStableIds:

    def test_ids_are_4_digit_sequential(self, monkeypatch):
        """IDs should be REQ-0001, REQ-0002, ... in document order."""
        from rfp_automation.agents import RequirementsExtractionAgent
        from rfp_automation.models.state import RFPGraphState
        from rfp_automation.models.schemas import RFPMetadata, StructuringResult
        from rfp_automation.models.enums import PipelineStatus

        mock_chunks = [
            {
                "id": "c0", "chunk_index": 0,
                "section_hint": "Section A",
                "text": "The vendor must deliver Phase 1 by Q1.",
                "content_type": "text", "page_start": 1, "page_end": 1,
                "metadata": {},
            },
            {
                "id": "c1", "chunk_index": 1,
                "section_hint": "Section B",
                "text": "The system shall support 1000 concurrent users.",
                "content_type": "text", "page_start": 2, "page_end": 2,
                "metadata": {},
            },
        ]

        llm_responses = [
            json.dumps([
                {"requirement_id": "REQ-0001", "text": "The vendor must deliver Phase 1 by Q1",
                 "type": "MANDATORY", "classification": "FUNCTIONAL",
                 "category": "OPERATIONAL", "impact": "HIGH", "keywords": ["delivery"]},
            ]),
            json.dumps([
                {"requirement_id": "REQ-0002", "text": "The system shall support 1000 concurrent users",
                 "type": "MANDATORY", "classification": "NON_FUNCTIONAL",
                 "category": "TECHNICAL", "impact": "HIGH", "keywords": ["scalability"]},
            ]),
        ]
        call_count = {"n": 0}

        def mock_llm(prompt, max_retries=1):
            idx = call_count["n"]
            call_count["n"] += 1
            return llm_responses[idx] if idx < len(llm_responses) else "[]"

        mock_mcp = type("MockMCP", (), {
            "fetch_all_rfp_chunks": lambda self, rfp_id: mock_chunks,
        })()
        monkeypatch.setattr("rfp_automation.agents.requirement_extraction_agent.MCPService", lambda: mock_mcp)
        monkeypatch.setattr("rfp_automation.agents.requirement_extraction_agent.llm_deterministic_call", mock_llm)

        state = RFPGraphState(
            status=PipelineStatus.EXTRACTING_REQUIREMENTS,
            rfp_metadata=RFPMetadata(rfp_id="RFP-ID-TEST"),
            structuring_result=StructuringResult(
                sections=[], overall_confidence=0.0,
            ),
        ).model_dump()

        agent = RequirementsExtractionAgent()
        result = agent.process(state)
        reqs = result["requirements"]
        assert len(reqs) == 2
        assert reqs[0]["requirement_id"] == "REQ-0001"
        assert reqs[1]["requirement_id"] == "REQ-0002"


# ═══════════════════════════════════════════════════════════
# Table Content Extraction Tests
# ═══════════════════════════════════════════════════════════


class TestTableExtraction:

    def test_table_text_not_placeholder(self):
        """Table blocks should contain actual text, not [TABLE DETECTED]."""
        blocks = [
            {"block_id": "tbl-001", "type": "table",
             "text": "Feature | Required | Priority\nSSO | Yes | High\nMFA | Yes | Critical",
             "page_number": 5},
        ]
        chunks = ParsingService.prepare_chunks(blocks)
        assert len(chunks) == 1
        assert "[TABLE DETECTED]" not in chunks[0]["text"]
        assert "SSO" in chunks[0]["text"]
        assert chunks[0]["content_type"] == "table"


# ═══════════════════════════════════════════════════════════
# Semantic Chunking Tests
# ═══════════════════════════════════════════════════════════


class TestSemanticChunking:

    def test_heading_grouped_with_body(self):
        blocks = [
            {"block_id": "h1", "type": "heading", "text": "3.1 Security Requirements", "page_number": 5},
            {"block_id": "p1", "type": "paragraph", "text": "The system must encrypt all data at rest.", "page_number": 5},
            {"block_id": "p2", "type": "paragraph", "text": "AES-256 encryption is required.", "page_number": 5},
        ]
        chunks = ParsingService.prepare_semantic_chunks(blocks, max_chunk_size=5000)
        # Heading + body should be in one chunk
        assert len(chunks) == 1
        assert "3.1 Security Requirements" in chunks[0]["text"]
        assert "AES-256" in chunks[0]["text"]

    def test_table_gets_own_chunk(self):
        blocks = [
            {"block_id": "h1", "type": "heading", "text": "Features", "page_number": 1},
            {"block_id": "p1", "type": "paragraph", "text": "The following features are required:", "page_number": 1},
            {"block_id": "t1", "type": "table", "text": "SSO | Required | High", "page_number": 2},
            {"block_id": "p2", "type": "paragraph", "text": "Additional notes here.", "page_number": 2},
        ]
        chunks = ParsingService.prepare_semantic_chunks(blocks, max_chunk_size=5000)
        # Table should be its own chunk
        table_chunks = [c for c in chunks if c["content_type"] == "table"]
        assert len(table_chunks) == 1
        assert "SSO" in table_chunks[0]["text"]

    def test_max_chunk_size_respected(self):
        blocks = [
            {"block_id": "h1", "type": "heading", "text": "Section 1", "page_number": 1},
            {"block_id": "p1", "type": "paragraph", "text": "A" * 1500, "page_number": 1},
            {"block_id": "p2", "type": "paragraph", "text": "B" * 1500, "page_number": 1},
        ]
        chunks = ParsingService.prepare_semantic_chunks(blocks, max_chunk_size=2000)
        # Should split into at least 2 chunks since heading + p1 exceeds 2000
        assert len(chunks) >= 2

    def test_chunk_index_sequential(self):
        blocks = [
            {"block_id": "h1", "type": "heading", "text": "Section 1", "page_number": 1},
            {"block_id": "p1", "type": "paragraph", "text": "Text 1", "page_number": 1},
            {"block_id": "h2", "type": "heading", "text": "Section 2", "page_number": 2},
            {"block_id": "p2", "type": "paragraph", "text": "Text 2", "page_number": 2},
        ]
        chunks = ParsingService.prepare_semantic_chunks(blocks, max_chunk_size=5000)
        for i, chunk in enumerate(chunks):
            assert chunk["chunk_index"] == i

    def test_empty_blocks(self):
        chunks = ParsingService.prepare_semantic_chunks([], max_chunk_size=2000)
        assert chunks == []


# ═══════════════════════════════════════════════════════════
# JSON Recovery & Boundary Truncation Tests
# ═══════════════════════════════════════════════════════════


class TestJSONRecovery:
    def test_json_recovery_truncation(self):
        from rfp_automation.agents.requirement_extraction_agent import RequirementsExtractionAgent
        
        agent = RequirementsExtractionAgent()
        # Simulated truncated JSON — texts must be ≥15 chars to pass content filters
        truncated_json = '''[
          {"requirement_id": "REQ-0001", "text": "The vendor must deliver Phase 1 by Q1 2026."},
          {"requirement_id": "REQ-0002", "text": "The system shall support 1000 concurrent users", "type": "MANDA'''
        
        # It should recover REQ-0001 because it can find the last '}'
        reqs = agent._parse_requirements_json(truncated_json, "Section A", 1)
        assert len(reqs) == 1
        assert reqs[0].requirement_id == "REQ-0001"
        assert reqs[0].text == "The vendor must deliver Phase 1 by Q1 2026."
        
    def test_json_recovery_failure_raises(self):
        from rfp_automation.agents.requirement_extraction_agent import RequirementsExtractionAgent, ExtractionBatchError
        
        agent = RequirementsExtractionAgent()
        # Completely garbled
        garbled_json = '''[{"req'''
        
        with pytest.raises(ExtractionBatchError):
            agent._parse_requirements_json(garbled_json, "Section A", 1)


class TestTextBoundaryTruncation:
    def test_truncate_at_sentence(self):
        from rfp_automation.utils.text import truncate_at_boundary
        
        text = "This is a sentence. This is another sentence that goes on."
        # If limit is 25, "This is a sentence. Thi" -> Should cut at "This is a sentence." (19 chars)
        truncated = truncate_at_boundary(text, 25)
        assert truncated.strip() == "This is a sentence."
        
    def test_truncate_at_paragraph(self):
        from rfp_automation.utils.text import truncate_at_boundary
        text = "Paragraph 1.\n\nParagraph 2 is here."
        truncated = truncate_at_boundary(text, 20)
        assert truncated == "Paragraph 1.\n\n"

