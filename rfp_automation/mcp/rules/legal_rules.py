"""
Legal Rules — contract clause risk assessment and legal gate logic.
Applied at the E2 Legal agent checkpoint.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LegalRules:
    """E2 legal rules for contract clause risk and compliance checks."""

    def __init__(self, mock_mode: bool = True):
        self.mock_mode = mock_mode

    def evaluate_commercial_legal_gate(
        self,
        legal_decision: str,
        legal_block_reasons: list[str],
        pricing_total: float,
    ) -> dict[str, Any]:
        """
        Combined gate that merges E1 + E2 outputs.
        E2 BLOCK always overrides E1 → pipeline ends.
        """
        if self.mock_mode:
            if legal_decision == "BLOCKED":
                return {
                    "gate_decision": "BLOCK",
                    "reason": "; ".join(legal_block_reasons),
                }
            return {
                "gate_decision": "CLEAR",
                "reason": "No blocking issues. Legal status: " + legal_decision,
            }
        raise NotImplementedError
