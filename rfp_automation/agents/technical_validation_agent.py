"""
D1 — Technical Validation Agent
Responsibility: Validate assembled proposal against original requirements.
                Check completeness, alignment, realism, consistency.
                REJECT loops back to C3 (max 3 retries).
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, PipelineStatus, ValidationDecision
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import TechnicalValidationResult, ValidationCheckResult
from rfp_automation.config import get_settings


class TechnicalValidationAgent(BaseAgent):
    name = AgentName.D1_TECHNICAL_VALIDATION

    def _mock_process(self, state: RFPGraphState) -> RFPGraphState:
        settings = get_settings()

        # Track retry count
        current_retries = state.technical_validation.retry_count

        checks = [
            ValidationCheckResult(
                check_name="completeness",
                passed=True,
                issues=[],
            ),
            ValidationCheckResult(
                check_name="alignment",
                passed=True,
                issues=[],
            ),
            ValidationCheckResult(
                check_name="realism",
                passed=True,
                issues=[],
            ),
            ValidationCheckResult(
                check_name="consistency",
                passed=True,
                issues=[],
            ),
        ]

        # Mock: always PASS on first attempt
        # To test the retry loop, change this logic
        decision = ValidationDecision.PASS
        critical = 0
        warnings = 0
        feedback = ""

        state.technical_validation = TechnicalValidationResult(
            decision=decision,
            checks=checks,
            critical_failures=critical,
            warnings=warnings,
            feedback_for_revision=feedback,
            retry_count=current_retries,
        )
        state.status = PipelineStatus.TECHNICAL_VALIDATION
        return state
