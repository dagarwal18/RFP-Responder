"""
Rules Config Store — loads/saves rule configurations from MongoDB.

Company-level setting: rules are configured once by admin and cached.
Falls back to sensible defaults if MongoDB is empty (first run).
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)


# ── Config models ────────────────────────────────────────

class PolicyConfig(BaseModel):
    """Policy rule configuration."""
    blocked_regions: list[str] = []
    allowed_regions: list[str] = []  # empty = all allowed
    min_contract_value: float = 10000.0
    max_contract_value: float = 10000000.0
    blocked_clients: list[str] = []
    required_certifications: list[str] = []
    certification_gap_severity: dict[str, str] = {
        "ISO 27001": "high",
        "SOC 2 Type II": "high",
        "FedRAMP Moderate": "critical",
        "HIPAA": "high",
        "PCI DSS": "high",
    }


class ValidationConfig(BaseModel):
    """Validation rule configuration."""
    max_uptime_sla: float = 99.999  # flag anything above this as unrealistic
    min_response_time_hours: float = 0.1  # flag anything below as unrealistic
    prohibited_phrases: list[str] = [
        "guaranteed 100% uptime",
        "zero defects",
        "unlimited support",
        "no additional cost ever",
        "perpetual license at no charge",
        "we will never fail",
        "absolute certainty",
        "risk-free implementation",
        "no downtime during migration",
        "instant resolution of all issues",
        "unlimited revisions",
        "we guarantee no bugs",
        "zero security vulnerabilities",
        "complete elimination of risk",
        "unconditional satisfaction",
    ]
    section_min_words: int = 50
    section_max_words: int = 5000


class CommercialConfig(BaseModel):
    """Commercial rule configuration."""
    minimum_margin_percent: float = 0.15
    maximum_discount_percent: float = 0.15
    max_contract_value: float = 5000000.0
    risky_payment_terms: list[str] = [
        "payment upon completion only",
        "net 120",
        "net 90",
        "payment after acceptance testing",
        "milestone-only with no advance",
    ]
    healthy_payment_terms: list[str] = [
        "net 30",
        "net 45",
        "net 60",
        "monthly invoicing",
        "time and materials",
        "50% advance, 50% on completion",
    ]


class LegalConfig(BaseModel):
    """Legal rule configuration."""
    auto_block_triggers: list[str] = [
        "unlimited liability",
        "irrevocable transfer of all intellectual property",
        "perpetual non-compete across all industries",
        "waiver of all warranties",
        "exclusive jurisdiction in foreign country",
    ]
    high_risk_keywords: list[str] = [
        "indemnify without limitation",
        "sole liability",
        "consequential damages with no cap",
        "perpetual confidentiality",
        "automatic renewal with no opt-out",
        "unilateral modification",
    ]
    max_liability_multiplier: float = 2.0  # max Nx contract value
    max_indemnity_percent: float = 1.0  # 100% of contract
    max_warranty_months: int = 12


# ── Store class ──────────────────────────────────────────

class RulesConfigStore:
    """
    Loads rule configs from MongoDB. Falls back to defaults on first run.
    Cached after first load for the lifetime of the process.
    """

    def __init__(self):
        self.settings = get_settings()
        self._db = None
        self._cache: dict[str, Any] = {}

    def _get_db(self):
        if self._db is not None:
            return self._db
        try:
            from pymongo import MongoClient
            client = MongoClient(self.settings.mongodb_uri)
            self._db = client[self.settings.mongodb_database]
        except Exception as e:
            logger.warning(f"MongoDB not available, using defaults: {e}")
            self._db = None
        return self._db

    def _load_config(self, rule_type: str, model_cls: type[BaseModel]) -> BaseModel:
        """Load from MongoDB or return defaults."""
        if rule_type in self._cache:
            return self._cache[rule_type]

        db = self._get_db()
        if db is not None:
            try:
                doc = db.rules_config.find_one({"rule_type": rule_type})
                if doc and "config" in doc:
                    config = model_cls(**doc["config"])
                    self._cache[rule_type] = config
                    return config
            except Exception as e:
                logger.warning(f"Failed loading {rule_type} from MongoDB: {e}")

        # Defaults
        config = model_cls()
        self._cache[rule_type] = config
        return config

    def get_policy_config(self) -> PolicyConfig:
        return self._load_config("policy", PolicyConfig)  # type: ignore[return-value]

    def get_validation_config(self) -> ValidationConfig:
        return self._load_config("validation", ValidationConfig)  # type: ignore[return-value]

    def get_commercial_config(self) -> CommercialConfig:
        return self._load_config("commercial", CommercialConfig)  # type: ignore[return-value]

    def get_legal_config(self) -> LegalConfig:
        return self._load_config("legal", LegalConfig)  # type: ignore[return-value]

    def update_config(self, rule_type: str, config_dict: dict[str, Any]) -> bool:
        """Admin: save/update a rule config in MongoDB."""
        db = self._get_db()
        if db is None:
            logger.error("Cannot update config — MongoDB not available")
            return False

        db.rules_config.update_one(
            {"rule_type": rule_type},
            {"$set": {"rule_type": rule_type, "config": config_dict}},
            upsert=True,
        )
        # Invalidate cache
        self._cache.pop(rule_type, None)
        logger.info(f"Updated {rule_type} config in MongoDB")
        return True
