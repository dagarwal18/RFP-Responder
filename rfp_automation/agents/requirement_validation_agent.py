"""
B2 — Requirements Validation Agent
Responsibility: Cross-check extracted requirements for completeness,
                duplicates, contradictions, and ambiguities.
                Issues do NOT block the pipeline — they flow forward as context.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, PipelineStatus
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import RequirementsValidationResult, ValidationIssue


class RequirementsValidationAgent(BaseAgent):
    name = AgentName.B2_REQUIREMENTS_VALIDATION

    def _mock_process(self, state: RFPGraphState) -> RFPGraphState:
        mandatory = [r for r in state.requirements if r.type.value == "MANDATORY"]
        optional = [r for r in state.requirements if r.type.value == "OPTIONAL"]

        issues = [
            ValidationIssue(
                issue_type="duplicate",
                requirement_ids=["REQ-003", "REQ-004"],
                description="SOC 2 and ISO 27001 both address certification compliance — consider grouping.",
                severity="info",
            ),
            ValidationIssue(
                issue_type="ambiguity",
                requirement_ids=["REQ-008"],
                description="'24/7 technical support' lacks definition of response-time SLAs.",
                severity="warning",
            ),
        ]

        state.requirements_validation = RequirementsValidationResult(
            validated_requirements=state.requirements,
            issues=issues,
            total_requirements=len(state.requirements),
            mandatory_count=len(mandatory),
            optional_count=len(optional),
        )
        state.status = PipelineStatus.VALIDATING_REQUIREMENTS
        return state
