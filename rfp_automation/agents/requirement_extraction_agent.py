"""
B1 — Requirements Extraction Agent
Responsibility: Extract every requirement from the RFP, classify by type,
                category, and impact, and assign unique IDs.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import (
    AgentName,
    PipelineStatus,
    RequirementType,
    RequirementCategory,
    ImpactLevel,
)
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import Requirement


class RequirementsExtractionAgent(BaseAgent):
    name = AgentName.B1_REQUIREMENTS_EXTRACTION

    def _mock_process(self, state: RFPGraphState) -> RFPGraphState:
        state.requirements = [
            Requirement(
                requirement_id="REQ-001",
                text="The platform must support AWS, Azure, and GCP simultaneously.",
                type=RequirementType.MANDATORY,
                category=RequirementCategory.TECHNICAL,
                impact=ImpactLevel.CRITICAL,
                source_section="SEC-02",
                keywords=["multi-cloud", "AWS", "Azure", "GCP"],
            ),
            Requirement(
                requirement_id="REQ-002",
                text="Auto-scaling must handle 10x traffic spikes within 60 seconds.",
                type=RequirementType.MANDATORY,
                category=RequirementCategory.TECHNICAL,
                impact=ImpactLevel.HIGH,
                source_section="SEC-02",
                keywords=["auto-scaling", "performance"],
            ),
            Requirement(
                requirement_id="REQ-003",
                text="SOC 2 Type II certification is required.",
                type=RequirementType.MANDATORY,
                category=RequirementCategory.COMPLIANCE,
                impact=ImpactLevel.CRITICAL,
                source_section="SEC-03",
                keywords=["SOC 2", "certification", "compliance"],
            ),
            Requirement(
                requirement_id="REQ-004",
                text="ISO 27001 certification is required.",
                type=RequirementType.MANDATORY,
                category=RequirementCategory.COMPLIANCE,
                impact=ImpactLevel.CRITICAL,
                source_section="SEC-03",
                keywords=["ISO 27001", "certification"],
            ),
            Requirement(
                requirement_id="REQ-005",
                text="All data must be encrypted at rest (AES-256) and in transit (TLS 1.3).",
                type=RequirementType.MANDATORY,
                category=RequirementCategory.SECURITY,
                impact=ImpactLevel.CRITICAL,
                source_section="SEC-03",
                keywords=["encryption", "AES-256", "TLS"],
            ),
            Requirement(
                requirement_id="REQ-006",
                text="CI/CD pipeline integration with Jenkins, GitHub Actions, and GitLab CI.",
                type=RequirementType.MANDATORY,
                category=RequirementCategory.TECHNICAL,
                impact=ImpactLevel.HIGH,
                source_section="SEC-02",
                keywords=["CI/CD", "Jenkins", "GitHub Actions"],
            ),
            Requirement(
                requirement_id="REQ-007",
                text="Real-time monitoring dashboard with customizable alerts.",
                type=RequirementType.MANDATORY,
                category=RequirementCategory.FUNCTIONAL,
                impact=ImpactLevel.MEDIUM,
                source_section="SEC-02",
                keywords=["monitoring", "dashboard", "alerts"],
            ),
            Requirement(
                requirement_id="REQ-008",
                text="The vendor should provide 24/7 technical support.",
                type=RequirementType.OPTIONAL,
                category=RequirementCategory.OPERATIONAL,
                impact=ImpactLevel.MEDIUM,
                source_section="SEC-02",
                keywords=["support", "24/7"],
            ),
            Requirement(
                requirement_id="REQ-009",
                text="GDPR compliance for EU data subjects.",
                type=RequirementType.MANDATORY,
                category=RequirementCategory.COMPLIANCE,
                impact=ImpactLevel.HIGH,
                source_section="SEC-03",
                keywords=["GDPR", "compliance", "EU"],
            ),
            Requirement(
                requirement_id="REQ-010",
                text="Disaster recovery with RPO < 1 hour and RTO < 4 hours.",
                type=RequirementType.MANDATORY,
                category=RequirementCategory.TECHNICAL,
                impact=ImpactLevel.HIGH,
                source_section="SEC-02",
                keywords=["disaster recovery", "RPO", "RTO"],
            ),
            Requirement(
                requirement_id="REQ-011",
                text="The platform should support Infrastructure-as-Code via Terraform.",
                type=RequirementType.OPTIONAL,
                category=RequirementCategory.TECHNICAL,
                impact=ImpactLevel.MEDIUM,
                source_section="SEC-02",
                keywords=["IaC", "Terraform"],
            ),
            Requirement(
                requirement_id="REQ-012",
                text="Vendor must have minimum 5 years cloud migration experience.",
                type=RequirementType.MANDATORY,
                category=RequirementCategory.COMPLIANCE,
                impact=ImpactLevel.HIGH,
                source_section="SEC-01",
                keywords=["experience", "cloud migration"],
            ),
        ]
        state.status = PipelineStatus.EXTRACTING_REQUIREMENTS
        return state
