"""
Tests: Full pipeline flow — all conditional paths.

Run with:
    pytest rfp_automation/tests/test_pipeline.py -v
"""

import pytest
from rfp_automation.orchestration.graph import run_pipeline
from rfp_automation.models.enums import PipelineStatus


class TestHappyPath:
    """Happy path: GO → PASS → CLEAR → APPROVE → SUBMITTED"""

    def test_pipeline_reaches_submitted(self):
        result = run_pipeline(uploaded_file_path="/test/sample.pdf")
        assert result["status"] == PipelineStatus.SUBMITTED.value

    def test_pipeline_has_rfp_id(self):
        result = run_pipeline()
        rfp_meta = result.get("rfp_metadata", {})
        assert rfp_meta.get("rfp_id", "").startswith("RFP-")

    def test_all_agents_produced_output(self):
        result = run_pipeline()

        # Every agent should have written its section
        assert result["rfp_metadata"]["rfp_id"] != ""
        assert result["structuring_result"]["overall_confidence"] > 0
        assert result["go_no_go_result"]["decision"] == "GO"
        assert len(result["requirements"]) > 0
        assert result["requirements_validation"]["total_requirements"] > 0
        assert result["architecture_plan"]["total_sections"] > 0
        assert len(result["writing_result"]["section_responses"]) > 0
        assert result["assembled_proposal"]["word_count"] > 0
        assert result["technical_validation"]["decision"] == "PASS"
        assert result["commercial_result"]["pricing"]["total_price"] > 0
        assert result["legal_result"]["decision"] in ("APPROVED", "CONDITIONAL")
        assert result["approval_package"]["approval_decision"] == "APPROVE"
        assert result["submission_record"]["file_hash"] != ""

    def test_audit_trail_populated(self):
        result = run_pipeline()
        audit = result.get("audit_trail", [])
        # At least one entry per agent that ran
        assert len(audit) >= 10


class TestGoNoGoTermination:
    """A3 NO_GO → pipeline should terminate early."""

    def test_no_go_stops_pipeline(self):
        from rfp_automation.agents.go_no_go_agent import GoNoGoAgent
        from rfp_automation.models.enums import GoNoGoDecision
        from rfp_automation.models.schemas import GoNoGoResult

        # Patch the mock to return NO_GO
        original_mock = GoNoGoAgent._mock_process

        def forced_no_go(self, state):
            state.go_no_go_result = GoNoGoResult(
                decision=GoNoGoDecision.NO_GO,
                strategic_fit_score=2.0,
                technical_feasibility_score=3.0,
                regulatory_risk_score=2.0,
                policy_violations=["Required cert not held: FedRAMP"],
                justification="Disqualified due to missing FedRAMP certification.",
            )
            state.status = PipelineStatus.GO_NO_GO
            return state

        GoNoGoAgent._mock_process = forced_no_go
        try:
            result = run_pipeline()
            assert result["status"] == PipelineStatus.NO_GO.value
            # Should NOT have requirements (B1 never ran)
            assert len(result.get("requirements", [])) == 0
        finally:
            GoNoGoAgent._mock_process = original_mock


class TestValidationLoop:
    """D1 REJECT → C3 retry → D1 again."""

    def test_validation_reject_loops_back(self):
        from rfp_automation.agents.technical_validation_agent import TechnicalValidationAgent
        from rfp_automation.models.enums import ValidationDecision
        from rfp_automation.models.schemas import TechnicalValidationResult, ValidationCheckResult

        call_count = {"n": 0}
        original_mock = TechnicalValidationAgent._mock_process

        def reject_then_pass(self, state):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                # First call: REJECT
                state.technical_validation = TechnicalValidationResult(
                    decision=ValidationDecision.REJECT,
                    checks=[ValidationCheckResult(check_name="completeness", passed=False, issues=["Missing REQ-010"])],
                    critical_failures=1,
                    warnings=0,
                    feedback_for_revision="Address REQ-010 coverage gap",
                    retry_count=call_count["n"],
                )
            else:
                # Second call: PASS
                state.technical_validation = TechnicalValidationResult(
                    decision=ValidationDecision.PASS,
                    checks=[],
                    critical_failures=0,
                    warnings=0,
                    retry_count=call_count["n"],
                )
            state.status = PipelineStatus.TECHNICAL_VALIDATION
            return state

        TechnicalValidationAgent._mock_process = reject_then_pass
        try:
            result = run_pipeline()
            assert result["status"] == PipelineStatus.SUBMITTED.value
            assert call_count["n"] >= 2  # D1 ran at least twice
        finally:
            TechnicalValidationAgent._mock_process = original_mock
