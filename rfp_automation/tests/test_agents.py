"""
Tests: Individual agent behaviour.

A1 Intake is now implemented — it should raise FileNotFoundError for
a non-existent file.  All other agents still raise NotImplementedError.

Run with:
    pytest rfp_automation/tests/test_agents.py -v
"""

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
    def test_raises_not_implemented(self):
        from rfp_automation.agents import StructuringAgent

        agent = StructuringAgent()
        with pytest.raises(NotImplementedError):
            agent.process(_empty_state())


class TestGoNoGoAgent:
    def test_raises_not_implemented(self):
        from rfp_automation.agents import GoNoGoAgent

        agent = GoNoGoAgent()
        with pytest.raises(NotImplementedError):
            agent.process(_empty_state())
