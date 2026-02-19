"""
Policy Rules — business rules applied at the A3 Go/No-Go gate.
Checks certifications, geography restrictions, contract value limits,
and conflict of interest.  Config loaded from MongoDB via RulesConfigStore.
"""

from __future__ import annotations

import logging
from typing import Any

from rfp_automation.mcp.rules.rules_config import RulesConfigStore

logger = logging.getLogger(__name__)


class PolicyRules:
    """Go/No-Go policy rules for the A3 governance checkpoint."""

    def __init__(self):
        self._config_store = RulesConfigStore()

    def check_policy_rules(
        self,
        required_certs: list[str],
        held_certs: dict[str, bool],
        contract_value: float | None = None,
        geography: str | None = None,
        client_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return list of policy violations (empty = pass).
        Each violation has: rule, detail, severity.
        """
        config = self._config_store.get_policy_config()
        violations: list[dict[str, Any]] = []

        # ── Certification gaps ───────────────────────────
        for cert in required_certs:
            if not held_certs.get(cert, False):
                severity = config.certification_gap_severity.get(cert, "medium")
                violations.append({
                    "rule": "certification_gap",
                    "detail": f"Required certification not held: {cert}",
                    "severity": severity,
                })

        # ── Geography restrictions ───────────────────────
        if geography:
            geo_upper = geography.upper()
            if config.blocked_regions:
                for blocked in config.blocked_regions:
                    if blocked.upper() in geo_upper:
                        violations.append({
                            "rule": "blocked_geography",
                            "detail": f"Geography '{geography}' is in blocked regions",
                            "severity": "critical",
                        })
            if config.allowed_regions:
                if not any(a.upper() in geo_upper for a in config.allowed_regions):
                    violations.append({
                        "rule": "geography_not_allowed",
                        "detail": f"Geography '{geography}' is not in allowed regions",
                        "severity": "high",
                    })

        # ── Contract value limits ────────────────────────
        if contract_value is not None:
            if contract_value < config.min_contract_value:
                violations.append({
                    "rule": "contract_too_small",
                    "detail": (
                        f"Contract value ${contract_value:,.2f} is below minimum "
                        f"${config.min_contract_value:,.2f}"
                    ),
                    "severity": "medium",
                })
            if contract_value > config.max_contract_value:
                violations.append({
                    "rule": "contract_too_large",
                    "detail": (
                        f"Contract value ${contract_value:,.2f} exceeds maximum "
                        f"${config.max_contract_value:,.2f}"
                    ),
                    "severity": "high",
                })

        # ── Conflict of interest ─────────────────────────
        if client_name and config.blocked_clients:
            for blocked in config.blocked_clients:
                if blocked.lower() in client_name.lower():
                    violations.append({
                        "rule": "conflict_of_interest",
                        "detail": f"Client '{client_name}' matches blocked client '{blocked}'",
                        "severity": "critical",
                    })

        return violations
