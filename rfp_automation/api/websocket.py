"""
WebSocket / Callback hooks for pipeline lifecycle events.
Used for logging, WebSocket notifications, and status tracking.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class PipelineCallbacks:
    """
    Hook into graph execution events.
    Replace these with WebSocket emitters / API calls in production.
    """

    @staticmethod
    def on_node_start(node_name: str, state: dict[str, Any]) -> None:
        rfp_id = state.get("rfp_metadata", {}).get("rfp_id", "unknown")
        logger.info(f"▶  [{rfp_id}] Starting node: {node_name}")

    @staticmethod
    def on_node_end(node_name: str, state: dict[str, Any]) -> None:
        rfp_id = state.get("rfp_metadata", {}).get("rfp_id", "unknown")
        status = state.get("status", "unknown")
        logger.info(f"✓  [{rfp_id}] Completed node: {node_name} → status={status}")

    @staticmethod
    def on_pipeline_end(state: dict[str, Any]) -> None:
        rfp_id = state.get("rfp_metadata", {}).get("rfp_id", "unknown")
        status = state.get("status", "unknown")
        logger.info(f"══ [{rfp_id}] Pipeline finished with status: {status}")

    @staticmethod
    def on_error(node_name: str, error: Exception, state: dict[str, Any]) -> None:
        rfp_id = state.get("rfp_metadata", {}).get("rfp_id", "unknown")
        logger.error(f"✗  [{rfp_id}] Error in {node_name}: {error}")
