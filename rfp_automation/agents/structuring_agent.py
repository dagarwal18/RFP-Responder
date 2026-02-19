"""
A2 — RFP Structuring Agent
Responsibility: Query MCP RFP store, classify document into sections,
                assign confidence scores.  Retry up to 3x if confidence is low.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, PipelineStatus
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import RFPSection, StructuringResult


class StructuringAgent(BaseAgent):
    name = AgentName.A2_STRUCTURING

    def _mock_process(self, state: RFPGraphState) -> RFPGraphState:
        sections = [
            RFPSection(
                section_id="SEC-01",
                title="Project Scope & Objectives",
                category="scope",
                content_summary="Cloud migration platform covering AWS, Azure, GCP with automated workload assessment.",
                confidence=0.92,
                page_range="1-8",
            ),
            RFPSection(
                section_id="SEC-02",
                title="Technical Requirements",
                category="technical",
                content_summary="Multi-cloud support, auto-scaling, CI/CD integration, monitoring dashboards.",
                confidence=0.95,
                page_range="9-20",
            ),
            RFPSection(
                section_id="SEC-03",
                title="Security & Compliance",
                category="compliance",
                content_summary="SOC 2 Type II, ISO 27001, GDPR, encryption at rest and in transit.",
                confidence=0.90,
                page_range="21-28",
            ),
            RFPSection(
                section_id="SEC-04",
                title="Legal & Contractual Terms",
                category="legal",
                content_summary="Liability caps, IP ownership, indemnification clauses, SLA terms.",
                confidence=0.88,
                page_range="29-35",
            ),
            RFPSection(
                section_id="SEC-05",
                title="Submission Instructions",
                category="submission",
                content_summary="Format requirements, submission deadline, evaluation timeline.",
                confidence=0.97,
                page_range="36-40",
            ),
            RFPSection(
                section_id="SEC-06",
                title="Evaluation Criteria",
                category="evaluation",
                content_summary="Technical approach 40%, experience 25%, pricing 20%, innovation 15%.",
                confidence=0.93,
                page_range="41-45",
            ),
        ]

        state.structuring_result = StructuringResult(
            sections=sections,
            overall_confidence=0.92,
            retry_count=0,
        )
        state.status = PipelineStatus.STRUCTURING
        return state
