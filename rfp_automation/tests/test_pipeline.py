"""
Tests: Full pipeline flow.

Since agents raise NotImplementedError until implemented,
these tests verify pipeline halts at the correct point.

Run with:
    pytest rfp_automation/tests/test_pipeline.py -v
"""

import pytest
from rfp_automation.orchestration.graph import run_pipeline


class TestPipelineHaltsAtUnimplemented:
    """Pipeline should halt at the first unimplemented agent (A1 Intake)."""

    def test_pipeline_halts_at_a1(self):
        with pytest.raises(Exception):
            run_pipeline(uploaded_file_path="/test/sample.pdf")
