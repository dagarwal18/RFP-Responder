"""
Tests: Individual agent behaviour.

Since agents now raise NotImplementedError until implemented,
these tests verify that the pipeline correctly halts.

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
    def test_raises_not_implemented(self):
        from rfp_automation.agents import IntakeAgent

        agent = IntakeAgent()
        with pytest.raises(NotImplementedError):
            agent.process(_empty_state())


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
