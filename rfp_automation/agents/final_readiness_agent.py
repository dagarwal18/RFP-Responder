"""
F1 — Final Readiness Agent
Responsibility: Compile the approval package (proposal, pricing, legal risk
                register, coverage matrix, decision brief) and trigger the
                human approval gate.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, PipelineStatus, ApprovalDecision
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import ApprovalPackage


class FinalReadinessAgent(BaseAgent):
    name = AgentName.F1_FINAL_READINESS

    def _mock_process(self, state: RFPGraphState) -> RFPGraphState:
        rfp = state.rfp_metadata
        pricing = state.commercial_result.pricing
        legal = state.legal_result

        decision_brief = (
            f"DECISION BRIEF — {rfp.rfp_title}\n"
            f"{'='*50}\n\n"
            f"Client:       {rfp.client_name}\n"
            f"RFP Number:   {rfp.rfp_number}\n"
            f"Deadline:     {rfp.deadline}\n\n"
            f"RECOMMENDATION: APPROVE\n\n"
            f"Strategic Fit:  {state.go_no_go_result.strategic_fit_score}/10\n"
            f"Technical:      {state.go_no_go_result.technical_feasibility_score}/10\n"
            f"Regulatory:     {state.go_no_go_result.regulatory_risk_score}/10\n\n"
            f"Total Price:    ${pricing.total_price:,.2f}\n"
            f"Legal Status:   {legal.decision.value}\n"
            f"Requirements:   {len(state.requirements)} total "
            f"({state.requirements_validation.mandatory_count} mandatory)\n"
            f"Coverage:       100% mandatory requirements addressed\n\n"
            f"RISK NOTES:\n{legal.risk_register_summary}\n"
        )

        state.approval_package = ApprovalPackage(
            decision_brief=decision_brief,
            proposal_summary=state.assembled_proposal.executive_summary,
            pricing_summary=state.commercial_result.commercial_narrative,
            risk_summary=legal.risk_register_summary,
            coverage_summary=f"{len(state.writing_result.coverage_matrix)} requirements mapped",
            # Mock: auto-approve for flow testing
            approval_decision=ApprovalDecision.APPROVE,
            approver_notes="Auto-approved in mock mode.",
        )
        state.status = PipelineStatus.AWAITING_APPROVAL
        return state
