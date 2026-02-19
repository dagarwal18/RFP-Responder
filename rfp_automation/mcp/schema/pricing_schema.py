"""
Pricing Schema — data structures for commercial pricing logic in the MCP context.
"""

from __future__ import annotations

from pydantic import BaseModel


class PricingParameters(BaseModel):
    """Pricing formula parameters from the knowledge store."""
    base_cost: float = 0.0
    per_requirement_cost: float = 0.0
    complexity_tiers: dict[str, float] = {}  # "low" -> 1.0, "medium" -> 1.25, "high" -> 1.5
    risk_margin_percent: float = 0.10
    payment_terms: str = ""
