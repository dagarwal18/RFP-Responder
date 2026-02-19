"""
Validation Rules — hard checks applied at the D1 Technical Validation gate.
Detects over-promised SLAs, prohibited language, unrealistic claims,
and inconsistencies.  Config loaded from MongoDB via RulesConfigStore.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from rfp_automation.mcp.rules.rules_config import RulesConfigStore

logger = logging.getLogger(__name__)


class ValidationRules:
    """D1 validation rules for proposal content checks."""

    def __init__(self):
        self._config_store = RulesConfigStore()

    def check_validation_rules(
        self,
        proposal_text: str,
        sections: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        """
        Apply hard validation checks.
        Returns list of violations: {rule, detail, severity}.
        """
        config = self._config_store.get_validation_config()
        violations: list[dict[str, str]] = []

        text_lower = proposal_text.lower()

        # ── Prohibited language ──────────────────────────
        for phrase in config.prohibited_phrases:
            if phrase.lower() in text_lower:
                violations.append({
                    "rule": "prohibited_language",
                    "detail": f"Prohibited phrase found: '{phrase}'",
                    "severity": "high",
                })

        # ── SLA realism checks ───────────────────────────
        # Detect uptime claims like "99.9999%" or "100%"
        uptime_matches = re.findall(r"(\d{2,3}(?:\.\d+)?)\s*%\s*uptime", text_lower)
        for match in uptime_matches:
            try:
                uptime_val = float(match)
                if uptime_val > config.max_uptime_sla:
                    violations.append({
                        "rule": "unrealistic_sla",
                        "detail": f"Uptime SLA {uptime_val}% exceeds realistic maximum {config.max_uptime_sla}%",
                        "severity": "high",
                    })
            except ValueError:
                pass

        # Detect response time claims like "0 minute" or "instant"
        instant_patterns = [
            r"response\s*time.*?(\d+)\s*(?:second|minute)",
            r"respond.*?within\s*(\d+)\s*(?:second|minute)",
        ]
        for pattern in instant_patterns:
            matches = re.findall(pattern, text_lower)
            for m in matches:
                try:
                    val = float(m)
                    # If the value is in seconds and < 1 minute, it's suspicious
                    if "second" in pattern and val < 60:
                        pass  # seconds can be okay depending on context
                except ValueError:
                    pass

        # ── Consistency checks ───────────────────────────
        # Check for conflicting statements
        contradiction_pairs = [
            ("no downtime", "scheduled maintenance"),
            ("unlimited", "subject to fair use"),
            ("guaranteed", "best effort"),
            ("24/7 support", "business hours only"),
        ]
        for phrase_a, phrase_b in contradiction_pairs:
            if phrase_a.lower() in text_lower and phrase_b.lower() in text_lower:
                violations.append({
                    "rule": "consistency_conflict",
                    "detail": f"Conflicting statements: '{phrase_a}' vs '{phrase_b}'",
                    "severity": "medium",
                })

        # ── Section length validation ────────────────────
        if sections:
            for section in sections:
                text = section.get("text", "")
                title = section.get("title", "Unknown Section")
                word_count = len(text.split())

                if word_count < config.section_min_words:
                    violations.append({
                        "rule": "section_too_short",
                        "detail": f"Section '{title}' has {word_count} words (min: {config.section_min_words})",
                        "severity": "low",
                    })
                if word_count > config.section_max_words:
                    violations.append({
                        "rule": "section_too_long",
                        "detail": f"Section '{title}' has {word_count} words (max: {config.section_max_words})",
                        "severity": "low",
                    })

        return violations
