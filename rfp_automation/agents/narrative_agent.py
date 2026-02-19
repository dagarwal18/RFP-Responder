"""
C3 — Narrative Assembly Agent
Responsibility: Combine section responses into a cohesive proposal with
                executive summary, transitions, and coverage appendix.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, PipelineStatus
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import AssembledProposal


class NarrativeAssemblyAgent(BaseAgent):
    name = AgentName.C3_NARRATIVE_ASSEMBLY

    def _mock_process(self, state: RFPGraphState) -> RFPGraphState:
        exec_summary = (
            "EXECUTIVE SUMMARY\n\n"
            "We are pleased to submit our proposal for the Enterprise Cloud Migration Platform "
            "in response to RFP-2026-0042 issued by Acme Corporation. Our CloudBridge™ platform "
            "delivers unified multi-cloud orchestration, enterprise-grade security, and proven "
            "migration methodology — backed by 8 years of experience and 12 successful enterprise "
            "engagements.\n\n"
            "Key highlights:\n"
            "• Full multi-cloud support (AWS, Azure, GCP) through a single pane of glass\n"
            "• SOC 2 Type II and ISO 27001 certified with AES-256 / TLS 1.3 encryption\n"
            "• Sub-60-second auto-scaling and DR with RPO 30 min / RTO 2 hr\n"
            "• Native CI/CD integrations and Terraform IaC provider\n"
            "• 24/7 NOC with 15-minute P1 response SLA\n"
        )

        # Assemble full narrative from section responses
        body_parts = []
        for sr in state.writing_result.section_responses:
            body_parts.append(f"\n{'='*60}\n{sr.title}\n{'='*60}\n\n{sr.content}\n")

        full_narrative = exec_summary + "\n".join(body_parts)

        # Coverage appendix
        appendix = "\n\nAPPENDIX: REQUIREMENT COVERAGE MATRIX\n" + "-" * 40 + "\n"
        for entry in state.writing_result.coverage_matrix:
            appendix += f"  {entry.requirement_id} → {entry.addressed_in_section} [{entry.coverage_quality}]\n"

        full_narrative += appendix

        state.assembled_proposal = AssembledProposal(
            executive_summary=exec_summary,
            full_narrative=full_narrative,
            word_count=len(full_narrative.split()),
            sections_included=len(state.writing_result.section_responses),
            has_placeholders=False,
        )
        state.status = PipelineStatus.ASSEMBLING_NARRATIVE
        return state
