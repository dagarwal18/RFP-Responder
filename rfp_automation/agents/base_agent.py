"""
Base agent class that every pipeline agent inherits.

Design:
  - `process()` is called by the LangGraph node.
  - `_real_process()` is the single abstract method — override in each agent.
  - Pipeline halts with NotImplementedError if an agent isn't implemented yet.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.enums import AgentName

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base for all pipeline agents."""

    name: AgentName  # set in each subclass

    # ── Public entry point (called by LangGraph node) ────

    def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        LangGraph calls this as the node function.
        Accepts and returns a dict so LangGraph can merge updates
        into the shared state automatically.
        """
        logger.info(f"[{self.name.value}] Starting")

        # Hydrate state from dict
        graph_state = RFPGraphState(**state)
        graph_state.current_agent = self.name.value

        try:
            updated = self._real_process(graph_state)

            updated.add_audit(
                agent=self.name.value,
                action="completed",
                details="",
            )
            logger.info(f"[{self.name.value}] Completed successfully")

        except Exception as exc:
            graph_state.error_message = f"[{self.name.value}] {exc}"
            graph_state.add_audit(
                agent=self.name.value,
                action="error",
                details=str(exc),
            )
            logger.exception(f"[{self.name.value}] Failed: {exc}")
            raise

        return updated.model_dump()

    # ── Subclass hook ────────────────────────────────────

    @abstractmethod
    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        """
        Real implementation using LLM + MCP.
        Must be overridden by each agent.
        """
        ...
