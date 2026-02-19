"""
Commercial Rules — pricing constraints and commercial gate logic.
Applied at the E1 Commercial agent checkpoint.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CommercialRules:
    """E1 commercial pricing rules and constraints."""

    def validate_pricing(
        self,
        total_price: float,
        min_margin_percent: float = 0.10,
        max_contract_value: float | None = None,
    ) -> list[str]:
        """
        Validate pricing against commercial constraints.
        Returns list of violations (empty = pass).
        """
        violations = []
        if max_contract_value and total_price > max_contract_value:
            violations.append(
                f"Total price ${total_price:,.2f} exceeds max contract value ${max_contract_value:,.2f}"
            )
        return violations
