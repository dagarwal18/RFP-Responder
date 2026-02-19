"""
Base agent class that every pipeline agent inherits.

Design:
  - `process()` is called by the LangGraph node.
  - When `mock_mode` is True, `_mock_process()` is invoked (returns hardcoded data).
  - When `mock_mode` is False, `_real_process()` is invoked (uses LLM + MCP).
  - Override `_real_process()` when you're ready to make an agent "real".
  - `_mock_process()` ships a sensible default; override if you need richer mocks.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.enums import AgentName
from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base for all pipeline agents."""

    name: AgentName  # set in each subclass

    def __init__(self, mock_mode: bool | None = None):
        settings = get_settings()
        self.mock_mode = mock_mode if mock_mode is not None else settings.mock_mode

    # ── Public entry point (called by LangGraph node) ────

    def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        LangGraph calls this as the node function.
        Accepts and returns a dict so LangGraph can merge updates
        into the shared state automatically.
        """
        logger.info(f"[{self.name.value}] Starting ({'MOCK' if self.mock_mode else 'REAL'})")

        # Hydrate state from dict
        graph_state = RFPGraphState(**state)
        graph_state.current_agent = self.name.value

        try:
            if self.mock_mode:
                updated = self._mock_process(graph_state)
            else:
                updated = self._real_process(graph_state)

            updated.add_audit(
                agent=self.name.value,
                action="completed",
                details=f"Mode={'mock' if self.mock_mode else 'real'}",
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
            updated = graph_state

        return updated.model_dump()

    # ── Subclass hooks ───────────────────────────────────

    @abstractmethod
    def _mock_process(self, state: RFPGraphState) -> RFPGraphState:
        """Return state with hardcoded/mock data. Must be overridden."""
        ...

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        """
        Real implementation using LLM + MCP.
        Override this when graduating from mock → real.
        Falls back to mock if not overridden.
        """
        logger.warning(
            f"[{self.name.value}] _real_process not implemented — falling back to mock"
        )
        return self._mock_process(state)
