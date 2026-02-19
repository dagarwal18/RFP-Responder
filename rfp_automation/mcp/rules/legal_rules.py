"""
Legal Rules — contract clause risk assessment and legal gate logic.
Applied at the E2 Legal agent checkpoint.
Config loaded from MongoDB via RulesConfigStore.
"""

from __future__ import annotations

import logging
from typing import Any

from rfp_automation.mcp.rules.rules_config import RulesConfigStore

logger = logging.getLogger(__name__)


class LegalRules:
    """E2 legal rules for contract clause risk and compliance checks."""

    def __init__(self):
        self._config_store = RulesConfigStore()

    def score_clause(self, clause_text: str) -> dict[str, Any]:
        """
        Score a single contract clause for risk.
        Returns: {score: 0-100, risk_level: str, triggers: list, blocked: bool}
        """
        config = self._config_store.get_legal_config()
        clause_lower = clause_text.lower()
        score = 0
        triggers: list[str] = []
        blocked = False

        # ── Auto-block triggers (critical) ───────────────
        for trigger in config.auto_block_triggers:
            if trigger.lower() in clause_lower:
                score += 50
                triggers.append(f"AUTO-BLOCK: {trigger}")
                blocked = True

        # ── High-risk keywords ───────────────────────────
        for keyword in config.high_risk_keywords:
            if keyword.lower() in clause_lower:
                score += 15
                triggers.append(f"HIGH-RISK: {keyword}")

        # Cap score at 100
        score = min(score, 100)

        # Determine risk level
        if score >= 50 or blocked:
            risk_level = "critical"
        elif score >= 30:
            risk_level = "high"
        elif score >= 15:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "score": score,
            "risk_level": risk_level,
            "triggers": triggers,
            "blocked": blocked,
        }

    def evaluate_clauses(
        self, clauses: list[str]
    ) -> dict[str, Any]:
        """
        Score all clauses and compute aggregate risk.
        Returns: {
            clause_scores: list[dict],
            aggregate_score: float,
            aggregate_risk: str,
            blocked: bool,
            block_reasons: list[str],
        }
        """
        clause_scores = [self.score_clause(c) for c in clauses]

        if not clause_scores:
            return {
                "clause_scores": [],
                "aggregate_score": 0,
                "aggregate_risk": "low",
                "blocked": False,
                "block_reasons": [],
            }

        # Aggregate: weighted average (heavier weight for higher scores)
        total = sum(cs["score"] for cs in clause_scores)
        avg = total / len(clause_scores)

        blocked = any(cs["blocked"] for cs in clause_scores)
        block_reasons = []
        for cs in clause_scores:
            if cs["blocked"]:
                block_reasons.extend(cs["triggers"])

        if avg >= 50 or blocked:
            agg_risk = "critical"
        elif avg >= 30:
            agg_risk = "high"
        elif avg >= 15:
            agg_risk = "medium"
        else:
            agg_risk = "low"

        return {
            "clause_scores": clause_scores,
            "aggregate_score": round(avg, 1),
            "aggregate_risk": agg_risk,
            "blocked": blocked,
            "block_reasons": block_reasons,
        }

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
        if legal_decision == "BLOCKED":
            return {
                "gate_decision": "BLOCK",
                "reason": "; ".join(legal_block_reasons),
            }
        return {
            "gate_decision": "CLEAR",
            "reason": "No blocking issues. Legal status: " + legal_decision,
        }
