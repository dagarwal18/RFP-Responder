"""
C2 — Requirement Writing Agent
Responsibility: Generate prose response per section using requirement context
                and capability evidence.  Build a coverage matrix.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, PipelineStatus
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import WritingResult, SectionResponse, CoverageEntry


class RequirementWritingAgent(BaseAgent):
    name = AgentName.C2_REQUIREMENT_WRITING

    def _mock_process(self, state: RFPGraphState) -> RFPGraphState:
        section_responses = []
        coverage_matrix = []

        mock_content = {
            "RESP-01": (
                "Our CloudBridge™ platform provides unified multi-cloud orchestration across AWS, "
                "Azure, and GCP through a single control plane. The auto-scaling engine monitors "
                "real-time workload metrics and provisions additional capacity within 45 seconds, "
                "well under the 60-second requirement. Disaster recovery is architected with "
                "geo-redundant deployments across three regions, achieving an RPO of 30 minutes "
                "and RTO of 2 hours — exceeding the stated thresholds."
            ),
            "RESP-02": (
                "Security is foundational to our platform. We maintain current SOC 2 Type II "
                "certification (latest audit: January 2026) and ISO 27001 certification (since 2020, "
                "renewed annually). All data at rest is encrypted with AES-256, and all data in "
                "transit uses TLS 1.3. For GDPR compliance, we provide a pre-approved Data Processing "
                "Agreement, dedicated EU data residency options, and automated data subject access "
                "request workflows."
            ),
            "RESP-03": (
                "Our platform integrates natively with Jenkins, GitHub Actions, and GitLab CI through "
                "pre-built pipeline templates and webhook-driven triggers. For Infrastructure-as-Code, "
                "we maintain an official Terraform provider (v3.2, publicly available) that supports "
                "full lifecycle management of cloud resources across all three providers."
            ),
            "RESP-04": (
                "The built-in observability dashboard provides real-time visibility into infrastructure "
                "health, application performance, and cost metrics with fully customizable alert rules. "
                "Our 24/7 Network Operations Center staffs certified engineers across three global "
                "time zones, with a guaranteed 15-minute initial response SLA for Priority 1 incidents."
            ),
            "RESP-05": (
                "With 8 years of dedicated cloud migration experience, our team has successfully "
                "completed 12 enterprise-scale migration projects across financial services, healthcare, "
                "and government sectors. Key references include a 500-server migration for a Fortune 100 "
                "bank and a HIPAA-compliant healthcare platform migration."
            ),
        }

        for section in state.architecture_plan.sections:
            content = mock_content.get(section.section_id, "Response content pending.")
            section_responses.append(
                SectionResponse(
                    section_id=section.section_id,
                    title=section.title,
                    content=content,
                    requirements_addressed=section.requirement_ids,
                    word_count=len(content.split()),
                )
            )
            for req_id in section.requirement_ids:
                coverage_matrix.append(
                    CoverageEntry(
                        requirement_id=req_id,
                        addressed_in_section=section.section_id,
                        coverage_quality="full",
                    )
                )

        state.writing_result = WritingResult(
            section_responses=section_responses,
            coverage_matrix=coverage_matrix,
        )
        state.status = PipelineStatus.WRITING_RESPONSES
        return state
