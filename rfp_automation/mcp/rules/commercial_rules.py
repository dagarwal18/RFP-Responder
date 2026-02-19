"""
Commercial Rules — pricing constraints and commercial gate logic.
Applied at the E1 Commercial agent checkpoint.
Config loaded from MongoDB via RulesConfigStore.
"""

from __future__ import annotations

import logging
from typing import Any

from rfp_automation.mcp.rules.rules_config import RulesConfigStore

logger = logging.getLogger(__name__)


class CommercialRules:
    """E1 commercial pricing rules and constraints."""

    def __init__(self):
        self._config_store = RulesConfigStore()

    def validate_pricing(
        self,
        total_price: float,
        total_cost: float = 0.0,
        discount_percent: float = 0.0,
        payment_terms: str = "",
    ) -> list[dict[str, Any]]:
        """
        Validate pricing against commercial constraints.
        Returns list of violations: {rule, detail, severity}.
        """
        config = self._config_store.get_commercial_config()
        violations: list[dict[str, Any]] = []

        # ── Contract value cap ───────────────────────────
        if total_price > config.max_contract_value:
            violations.append({
                "rule": "contract_value_exceeded",
                "detail": (
                    f"Total price ${total_price:,.2f} exceeds max "
                    f"${config.max_contract_value:,.2f}"
                ),
                "severity": "high",
            })

        # ── Minimum margin check ─────────────────────────
        if total_cost > 0:
            margin = (total_price - total_cost) / total_price
            if margin < config.minimum_margin_percent:
                violations.append({
                    "rule": "margin_too_low",
                    "detail": (
                        f"Margin {margin:.1%} is below minimum "
                        f"{config.minimum_margin_percent:.1%}"
                    ),
                    "severity": "high",
                })

        # ── Discount limit ───────────────────────────────
        if discount_percent > config.maximum_discount_percent:
            violations.append({
                "rule": "discount_exceeded",
                "detail": (
                    f"Discount {discount_percent:.1%} exceeds maximum "
                    f"{config.maximum_discount_percent:.1%}"
                ),
                "severity": "medium",
            })

        # ── Payment terms validation ─────────────────────
        if payment_terms:
            terms_lower = payment_terms.lower()
            for risky in config.risky_payment_terms:
                if risky.lower() in terms_lower:
                    violations.append({
                        "rule": "risky_payment_terms",
                        "detail": f"Risky payment terms detected: '{payment_terms}'",
                        "severity": "medium",
                    })
                    break

        return violations
