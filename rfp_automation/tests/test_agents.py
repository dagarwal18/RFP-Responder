"""
Tests: Individual agent behaviour.

A1 Intake is now implemented — it should raise FileNotFoundError for
a non-existent file.  All other agents still raise NotImplementedError.

Run with:
    pytest rfp_automation/tests/test_agents.py -v
"""

import json
import pytest
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.enums import PipelineStatus


def _empty_state() -> dict:
    return RFPGraphState(
        uploaded_file_path="/test/rfp.pdf",
        status=PipelineStatus.RECEIVED,
    ).model_dump()


class TestIntakeAgent:
    def test_raises_file_not_found_for_missing_file(self):
        """A1 is implemented — it validates the file exists."""
        from rfp_automation.agents import IntakeAgent

        agent = IntakeAgent()
        with pytest.raises(FileNotFoundError):
            agent.process(_empty_state())

    def test_raises_value_error_for_no_path(self):
        """A1 is implemented — it rejects empty file path."""
        from rfp_automation.agents import IntakeAgent

        agent = IntakeAgent()
        state = RFPGraphState(status=PipelineStatus.RECEIVED).model_dump()
        with pytest.raises(ValueError, match="No file path"):
            agent.process(state)


class TestStructuringAgent:
    """Tests for A2 Structuring Agent."""

    def _structuring_state(self, rfp_id="RFP-TEST1234") -> dict:
        """State with rfp_id set (A1 has already run)."""
        from rfp_automation.models.schemas import RFPMetadata

        return RFPGraphState(
            uploaded_file_path="/test/rfp.pdf",
            status=PipelineStatus.STRUCTURING,
            rfp_metadata=RFPMetadata(rfp_id=rfp_id),
            raw_text="This is test RFP content for structuring.",
        ).model_dump()

    def test_structuring_success(self, monkeypatch):
        """High-confidence LLM response → sections populated, status = GO_NO_GO."""
        from rfp_automation.agents import StructuringAgent

        mock_chunks = [
            {"id": "chunk_0", "score": 0.9, "text": "Project scope...", "chunk_index": 0, "metadata": {}},
            {"id": "chunk_1", "score": 0.9, "text": "Technical specs...", "chunk_index": 1, "metadata": {}},
        ]
        llm_response = json.dumps([
            {
                "section_id": "SEC-01",
                "title": "Project Scope",
                "category": "scope",
                "content_summary": "Describes the project scope.",
                "confidence": 0.92,
                "page_range": "1-3",
            },
            {
                "section_id": "SEC-02",
                "title": "Technical Requirements",
                "category": "technical",
                "content_summary": "Lists technical specs.",
                "confidence": 0.88,
                "page_range": "4-8",
            },
        ])

        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.MCPService",
            lambda: type("MockMCP", (), {"query_rfp_all_chunks": lambda self, rfp_id, top_k=100: mock_chunks})(),
        )
        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.llm_text_call",
            lambda prompt: llm_response,
        )

        agent = StructuringAgent()
        result = agent.process(self._structuring_state())

        assert result["structuring_result"]["overall_confidence"] >= 0.6
        assert len(result["structuring_result"]["sections"]) == 2
        assert result["status"] == PipelineStatus.GO_NO_GO.value

    def test_structuring_low_confidence_increments_retry(self, monkeypatch):
        """Low-confidence LLM response → retry_count incremented, status stays STRUCTURING."""
        from rfp_automation.agents import StructuringAgent

        mock_chunks = [
            {"id": "chunk_0", "score": 0.5, "text": "Ambiguous content...", "chunk_index": 0, "metadata": {}},
        ]
        llm_response = json.dumps([
            {
                "section_id": "SEC-01",
                "title": "Unclear Section",
                "category": "scope",
                "content_summary": "Hard to classify.",
                "confidence": 0.3,
                "page_range": "",
            },
        ])

        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.MCPService",
            lambda: type("MockMCP", (), {"query_rfp_all_chunks": lambda self, rfp_id, top_k=100: mock_chunks})(),
        )
        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.llm_text_call",
            lambda prompt: llm_response,
        )

        agent = StructuringAgent()
        result = agent.process(self._structuring_state())

        assert result["structuring_result"]["overall_confidence"] < 0.6
        assert result["structuring_result"]["retry_count"] == 1
        assert result["status"] == PipelineStatus.STRUCTURING.value

    def test_structuring_invalid_json_triggers_retry(self, monkeypatch):
        """Malformed LLM response → 0 sections, confidence = 0, retry incremented."""
        from rfp_automation.agents import StructuringAgent

        mock_chunks = [
            {"id": "chunk_0", "score": 0.9, "text": "Some content...", "chunk_index": 0, "metadata": {}},
        ]

        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.MCPService",
            lambda: type("MockMCP", (), {"query_rfp_all_chunks": lambda self, rfp_id, top_k=100: mock_chunks})(),
        )
        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.llm_text_call",
            lambda prompt: "This is not valid JSON at all",
        )

        agent = StructuringAgent()
        result = agent.process(self._structuring_state())

        assert result["structuring_result"]["overall_confidence"] == 0.0
        assert result["structuring_result"]["retry_count"] == 1
        assert len(result["structuring_result"]["sections"]) == 0

    def test_structuring_no_rfp_id_raises(self):
        """Missing rfp_id → ValueError."""
        from rfp_automation.agents import StructuringAgent

        agent = StructuringAgent()
        state = RFPGraphState(
            status=PipelineStatus.STRUCTURING,
        ).model_dump()
        with pytest.raises(ValueError, match="No rfp_id"):
            agent.process(state)


class TestGoNoGoAgent:
    def test_raises_not_implemented(self):
        from rfp_automation.agents import GoNoGoAgent

        agent = GoNoGoAgent()
        with pytest.raises(NotImplementedError):
            agent.process(_empty_state())
