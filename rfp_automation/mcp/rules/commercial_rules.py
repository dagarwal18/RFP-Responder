"""
Commercial Rules — pricing constraints and commercial gate logic.
Applied at the E1 Commercial agent checkpoint.
Config loaded from MongoDB via RulesConfigStore.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from rfp_automation.mcp.rules.rules_config import RulesConfigStore

logger = logging.getLogger(__name__)

_PRICING_RULES_PATH = (
    Path(__file__).resolve().parent.parent / "knowledge_data" / "pricing_rules.json"
)


class CommercialRules:
    """E1 commercial pricing rules and constraints."""

    def __init__(self):
        self._config_store = RulesConfigStore()
        self._pricing_config: dict[str, Any] | None = None

    def load_pricing_config(self) -> dict[str, Any]:
        """Load pricing rules from knowledge_data/pricing_rules.json.

        Returns a dict with keys like base_cost, per_requirement_cost,
        complexity_tiers, risk_margin_percent, etc.
        Cached after the first load.
        """
        if self._pricing_config is not None:
            return self._pricing_config

        try:
            raw = _PRICING_RULES_PATH.read_text(encoding="utf-8")
            self._pricing_config = json.loads(raw)
            logger.info(
                f"[CommercialRules] Loaded pricing config from {_PRICING_RULES_PATH.name}"
            )
        except Exception as exc:
            logger.error(
                f"[CommercialRules] Failed to load pricing_rules.json: {exc}. "
                "Pricing data must be seeded from KB documents before generating proposals. "
                "Upload company documents via /api/knowledge/upload or seed via /api/knowledge/seed."
            )
            self._pricing_config = {
                "source": "missing",
                "entries": [],
                "currency": "",
                "payment_terms": "",
                "error": str(exc),
            }

        return self._pricing_config

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
