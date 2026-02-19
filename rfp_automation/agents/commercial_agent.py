"""
E1 — Commercial Agent
Responsibility: Generate pricing breakdown using MCP knowledge base pricing
                rules.  Runs in parallel with E2 Legal.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, PipelineStatus
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import CommercialResult, PricingBreakdown


class CommercialAgent(BaseAgent):
    name = AgentName.E1_COMMERCIAL

    def _mock_process(self, state: RFPGraphState) -> RFPGraphState:
        num_requirements = len(state.requirements)

        pricing = PricingBreakdown(
            base_cost=150_000.00,
            per_requirement_cost=2_500.00,
            complexity_multiplier=1.25,
            risk_margin=15_000.00,
            total_price=150_000 + (num_requirements * 2_500 * 1.25) + 15_000,
            payment_terms="30% at contract signing, 40% at UAT completion, 30% at go-live",
            assumptions=[
                "Client provides cloud account access within 5 business days",
                "Scope limited to workloads identified in discovery phase",
                "Change requests handled under separate SOW",
            ],
            exclusions=[
                "Third-party license costs",
                "On-site travel expenses",
                "Data migration exceeding 50 TB",
            ],
        )

        state.commercial_result = CommercialResult(
            pricing=pricing,
            commercial_narrative=(
                f"Our commercial proposal totals ${pricing.total_price:,.2f}, structured across "
                f"three milestone-based payments ({pricing.payment_terms}). This pricing reflects "
                f"{num_requirements} identified requirements with a complexity multiplier of "
                f"{pricing.complexity_multiplier}x and includes a risk margin to cover contingencies."
            ),
        )
        state.status = PipelineStatus.COMMERCIAL_LEGAL_REVIEW
        return state
