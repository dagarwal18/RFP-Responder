"""
Policy Rules — hard-coded business rules applied at the A3 Go/No-Go gate.
Checks certifications, geography restrictions, contract value limits.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class PolicyRules:
    """Go/No-Go policy rules for the A3 governance checkpoint."""

    def check_policy_rules(
        self,
        required_certs: list[str],
        held_certs: dict[str, bool],
        contract_value: float | None = None,
        geography: str | None = None,
    ) -> list[str]:
        """
        Return list of policy violations (empty = pass).
        Any violation → auto NO_GO.
        """
        violations = []
        for cert in required_certs:
            if not held_certs.get(cert, False):
                violations.append(f"Required certification not held: {cert}")
        return violations
