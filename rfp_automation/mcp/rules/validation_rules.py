"""
Validation Rules — hard checks applied at the D1 Technical Validation gate.
Detects over-promised SLAs, prohibited language, unrealistic claims.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class ValidationRules:
    """D1 validation rules for proposal content checks."""

    def __init__(self, mock_mode: bool = True):
        self.mock_mode = mock_mode

    def check_validation_rules(self, proposal_text: str) -> list[dict[str, str]]:
        """
        Apply hard validation checks (over-promised SLAs, prohibited language).
        Returns list of violations.
        """
        if self.mock_mode:
            violations = []
            prohibited = ["guarantee 100% uptime", "unlimited", "zero risk"]
            for phrase in prohibited:
                if phrase.lower() in proposal_text.lower():
                    violations.append({
                        "rule": "prohibited_language",
                        "detail": f"Prohibited phrase found: '{phrase}'",
                    })
            return violations
        raise NotImplementedError
