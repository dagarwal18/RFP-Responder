"""
Tests: Full pipeline flow.

Pipeline should halt at A1 (FileNotFoundError for test path)
since we don't have a real file.
When a real Pinecone+file is available, A1 will pass and halt at A2 (not yet implemented).

Run with:
    pytest rfp_automation/tests/test_pipeline.py -v
"""

import pytest
from rfp_automation.orchestration.graph import run_pipeline


class TestPipelineHaltsAtUnimplemented:
    """Pipeline should halt at A1 (file not found) in test environment."""

    def test_pipeline_halts_at_a1_missing_file(self):
        with pytest.raises(Exception):
            run_pipeline(uploaded_file_path="/test/sample.pdf")
