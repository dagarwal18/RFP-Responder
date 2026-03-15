"""
H1 - Human Validation Agent
Responsibility: Build a review package and pause the pipeline for human input.
"""

from __future__ import annotations

import logging

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, PipelineStatus
from rfp_automation.models.state import RFPGraphState
from rfp_automation.services.review_service import ReviewService

logger = logging.getLogger(__name__)


class HumanValidationAgent(BaseAgent):
    name = AgentName.H1_HUMAN_VALIDATION

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        review_package = ReviewService.build_review_package(state)
        state.review_package = review_package
        state.status = PipelineStatus.AWAITING_HUMAN_VALIDATION

        logger.info(
            "[H1] Review package ready: %s source sections, %s response sections, %s open comments",
            len(review_package.source_sections),
            len(review_package.response_sections),
            review_package.open_comment_count,
        )
        return state
