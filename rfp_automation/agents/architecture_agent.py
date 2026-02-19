"""
C1 — Architecture Planning Agent
Responsibility: Group requirements into response sections, map each to
                company capabilities.  Verify every mandatory requirement
                appears in the plan.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, PipelineStatus
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import ArchitecturePlan, ResponseSection


class ArchitecturePlanningAgent(BaseAgent):
    name = AgentName.C1_ARCHITECTURE_PLANNING

    def _mock_process(self, state: RFPGraphState) -> RFPGraphState:
        sections = [
            ResponseSection(
                section_id="RESP-01",
                title="Multi-Cloud Platform Architecture",
                requirement_ids=["REQ-001", "REQ-002", "REQ-010"],
                mapped_capabilities=[
                    "CloudBridge™ multi-cloud orchestration engine",
                    "Auto-scaling controller with sub-60s burst capacity",
                    "Geo-redundant DR across 3 regions",
                ],
                priority=1,
            ),
            ResponseSection(
                section_id="RESP-02",
                title="Security & Compliance Framework",
                requirement_ids=["REQ-003", "REQ-004", "REQ-005", "REQ-009"],
                mapped_capabilities=[
                    "SOC 2 Type II certified (audit report available)",
                    "ISO 27001 certified since 2020",
                    "AES-256 encryption at rest, TLS 1.3 in transit",
                    "GDPR Data Processing Agreement template",
                ],
                priority=2,
            ),
            ResponseSection(
                section_id="RESP-03",
                title="DevOps & CI/CD Integration",
                requirement_ids=["REQ-006", "REQ-011"],
                mapped_capabilities=[
                    "Native integrations with Jenkins, GitHub Actions, GitLab CI",
                    "Terraform provider for IaC-driven deployments",
                ],
                priority=3,
            ),
            ResponseSection(
                section_id="RESP-04",
                title="Monitoring & Operations",
                requirement_ids=["REQ-007", "REQ-008"],
                mapped_capabilities=[
                    "Real-time observability dashboard (Grafana-based)",
                    "24/7 NOC with 15-min P1 response SLA",
                ],
                priority=4,
            ),
            ResponseSection(
                section_id="RESP-05",
                title="Company Experience & Qualifications",
                requirement_ids=["REQ-012"],
                mapped_capabilities=[
                    "8 years of cloud migration experience",
                    "12 enterprise migration projects completed",
                ],
                priority=5,
            ),
        ]

        state.architecture_plan = ArchitecturePlan(
            sections=sections,
            coverage_gaps=[],
            total_sections=len(sections),
        )
        state.status = PipelineStatus.ARCHITECTURE_PLANNING
        return state
