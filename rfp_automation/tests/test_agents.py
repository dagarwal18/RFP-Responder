"""
Tests: Individual agent behaviour.

Run with:
    pytest rfp_automation/tests/test_agents.py -v
"""

import pytest
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.enums import PipelineStatus, GoNoGoDecision, ValidationDecision


def _empty_state() -> dict:
    return RFPGraphState(
        uploaded_file_path="/test/rfp.pdf",
        status=PipelineStatus.RECEIVED,
    ).model_dump()


class TestIntakeAgent:
    def test_produces_rfp_metadata(self):
        from rfp_automation.agents import IntakeAgent

        agent = IntakeAgent(mock_mode=True)
        result = agent.process(_empty_state())
        assert result["rfp_metadata"]["rfp_id"].startswith("RFP-")
        assert result["rfp_metadata"]["client_name"] != ""
        assert result["rfp_metadata"]["page_count"] > 0

    def test_sets_raw_text(self):
        from rfp_automation.agents import IntakeAgent

        agent = IntakeAgent(mock_mode=True)
        result = agent.process(_empty_state())
        assert len(result["raw_text"]) > 0


class TestStructuringAgent:
    def test_produces_sections(self):
        from rfp_automation.agents import IntakeAgent, StructuringAgent

        state = IntakeAgent(mock_mode=True).process(_empty_state())
        result = StructuringAgent(mock_mode=True).process(state)
        assert len(result["structuring_result"]["sections"]) >= 5
        assert result["structuring_result"]["overall_confidence"] > 0.5


class TestGoNoGoAgent:
    def test_default_is_go(self):
        from rfp_automation.agents import GoNoGoAgent

        agent = GoNoGoAgent(mock_mode=True)
        result = agent.process(_empty_state())
        assert result["go_no_go_result"]["decision"] == GoNoGoDecision.GO.value


class TestRequirementsExtractionAgent:
    def test_extracts_requirements(self):
        from rfp_automation.agents import RequirementsExtractionAgent

        agent = RequirementsExtractionAgent(mock_mode=True)
        result = agent.process(_empty_state())
        reqs = result["requirements"]
        assert len(reqs) >= 10
        assert all(r["requirement_id"].startswith("REQ-") for r in reqs)


class TestRequirementsValidationAgent:
    def test_validates_requirements(self):
        from rfp_automation.agents import RequirementsExtractionAgent, RequirementsValidationAgent

        state = RequirementsExtractionAgent(mock_mode=True).process(_empty_state())
        result = RequirementsValidationAgent(mock_mode=True).process(state)
        val = result["requirements_validation"]
        assert val["total_requirements"] > 0
        assert val["mandatory_count"] > 0


class TestTechnicalValidationAgent:
    def test_default_pass(self):
        from rfp_automation.agents import TechnicalValidationAgent

        agent = TechnicalValidationAgent(mock_mode=True)
        result = agent.process(_empty_state())
        assert result["technical_validation"]["decision"] == ValidationDecision.PASS.value


class TestCommercialAgent:
    def test_produces_pricing(self):
        from rfp_automation.agents import RequirementsExtractionAgent, CommercialAgent

        state = RequirementsExtractionAgent(mock_mode=True).process(_empty_state())
        result = CommercialAgent(mock_mode=True).process(state)
        assert result["commercial_result"]["pricing"]["total_price"] > 0


class TestLegalAgent:
    def test_identifies_risks(self):
        from rfp_automation.agents import LegalAgent

        agent = LegalAgent(mock_mode=True)
        result = agent.process(_empty_state())
        assert len(result["legal_result"]["clause_risks"]) > 0


class TestFinalReadinessAgent:
    def test_auto_approves_in_mock(self):
        from rfp_automation.agents import FinalReadinessAgent

        # Need a populated state for F1
        from rfp_automation.orchestration.graph import run_pipeline

        # Run the full pipeline; F1 should auto-approve
        result = run_pipeline()
        assert result["approval_package"]["approval_decision"] == "APPROVE"
