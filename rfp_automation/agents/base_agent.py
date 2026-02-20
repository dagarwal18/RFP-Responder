"""
Base agent class that every pipeline agent inherits.

Design:
  - `process()` is called by the LangGraph node.
  - `_real_process()` is the single abstract method — override in each agent.
  - Pipeline halts with NotImplementedError if an agent isn't implemented yet.
"""

from __future__ import annotations

import json
import logging
import time
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
        t0 = time.perf_counter()
        separator = "═" * 70
        logger.info(f"\n{separator}")
        logger.info(f"▶ [{self.name.value}] STARTING")
        logger.info(separator)

        # Log incoming state keys + sizes
        _log_state_summary("INPUT STATE", state)

        # Hydrate state from dict
        graph_state = RFPGraphState(**state)
        graph_state.current_agent = self.name.value

        # Broadcast real-time progress — prefer the tracking id the
        # frontend connected to, fall back to rfp_metadata.rfp_id
        rfp_id = state.get("tracking_rfp_id", "")
        if not rfp_id:
            meta = state.get("rfp_metadata")
            if isinstance(meta, dict):
                rfp_id = meta.get("rfp_id", "")
            elif hasattr(meta, "rfp_id"):
                rfp_id = meta.rfp_id or ""

        progress = None
        try:
            from rfp_automation.api.websocket import PipelineProgress
            progress = PipelineProgress.get()
            progress.on_node_start(rfp_id, self.name.value)
        except Exception:
            pass

        try:
            updated = self._real_process(graph_state)

            updated.add_audit(
                agent=self.name.value,
                action="completed",
                details="",
            )
            elapsed = time.perf_counter() - t0
            logger.info(f"✔ [{self.name.value}] COMPLETED in {elapsed:.3f}s")

            # Log output state diff
            out_dict = updated.model_dump()
            _log_state_summary("OUTPUT STATE", out_dict)
            _log_state_diff("STATE CHANGES", state, out_dict)

            logger.info(f"{separator}\n")

            try:
                if progress:
                    status = updated.status.value if hasattr(updated.status, 'value') else str(updated.status)
                    progress.on_node_end(rfp_id, self.name.value, status)
            except Exception:
                pass

        except Exception as exc:
            elapsed = time.perf_counter() - t0
            graph_state.error_message = f"[{self.name.value}] {exc}"
            graph_state.add_audit(
                agent=self.name.value,
                action="error",
                details=str(exc),
            )
            logger.exception(
                f"✘ [{self.name.value}] FAILED after {elapsed:.3f}s: {exc}"
            )
            logger.info(f"{separator}\n")

            try:
                if progress:
                    progress.on_error(rfp_id, self.name.value, str(exc))
            except Exception:
                pass

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


# ── Debug helpers (module-level) ─────────────────────────

def _log_state_summary(label: str, state: dict[str, Any]) -> None:
    """Log key names, non-empty values, and approximate sizes."""
    lines = [f"  ┌─ {label}"]
    for key in sorted(state.keys()):
        val = state[key]
        if val is None or val == "" or val == [] or val == {}:
            lines.append(f"  │  {key}: <empty>")
        elif isinstance(val, str):
            lines.append(f"  │  {key}: str({len(val)} chars)")
        elif isinstance(val, list):
            lines.append(f"  │  {key}: list({len(val)} items)")
        elif isinstance(val, dict):
            lines.append(f"  │  {key}: dict({len(val)} keys)")
        else:
            lines.append(f"  │  {key}: {type(val).__name__} = {_truncate(val)}")
    lines.append(f"  └─ ({len(state)} keys total)")
    logger.debug("\n".join(lines))


def _log_state_diff(label: str, before: dict[str, Any], after: dict[str, Any]) -> None:
    """Log which keys changed between input and output state."""
    changes: list[str] = []
    all_keys = set(before.keys()) | set(after.keys())
    for key in sorted(all_keys):
        old = before.get(key)
        new = after.get(key)
        if old != new:
            changes.append(f"  │  {key}: {_truncate(old)} → {_truncate(new)}")
    if changes:
        logger.debug(f"  ┌─ {label}\n" + "\n".join(changes) + f"\n  └─ ({len(changes)} fields changed)")
    else:
        logger.debug(f"  ── {label}: no changes")


def _truncate(val: Any, max_len: int = 120) -> str:
    """Produce a short repr for debug logging."""
    if val is None:
        return "<None>"
    if isinstance(val, str):
        if len(val) > max_len:
            return repr(val[:max_len]) + f"…({len(val)} chars)"
        return repr(val)
    if isinstance(val, list):
        return f"list({len(val)} items)"
    if isinstance(val, dict):
        try:
            s = json.dumps(val, default=str)
            if len(s) > max_len:
                return s[:max_len] + f"…({len(s)} chars)"
            return s
        except Exception:
            return f"dict({len(val)} keys)"
    s = str(val)
    if len(s) > max_len:
        return s[:max_len] + "…"
    return s
