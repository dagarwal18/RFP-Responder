"""
Knowledge Store — company capabilities, past proposals, certifications,
pricing rules, legal templates.  Stored as embeddings in the MCP server.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class KnowledgeStore:
    """Interface to the company knowledge base inside the MCP server."""

    def __init__(self, mock_mode: bool = True):
        self.mock_mode = mock_mode

    def query_capabilities(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Retrieve company capabilities relevant to a query."""
        if self.mock_mode:
            return [
                {
                    "capability": "CloudBridge™ Multi-Cloud Orchestration",
                    "description": "Unified management across AWS, Azure, GCP",
                    "evidence": "Deployed for 12 enterprise clients",
                    "score": 0.95,
                },
                {
                    "capability": "Enterprise Security Suite",
                    "description": "SOC 2 Type II, ISO 27001, AES-256, TLS 1.3",
                    "evidence": "Certified since 2020",
                    "score": 0.92,
                },
            ]
        raise NotImplementedError

    def query_past_proposals(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        """Retrieve relevant past proposals."""
        if self.mock_mode:
            return [
                {
                    "proposal_id": "PROP-2025-018",
                    "client": "GlobalBank Inc.",
                    "summary": "500-server AWS migration with zero-downtime cutover",
                    "outcome": "Won — $2.1M contract",
                    "score": 0.88,
                },
            ]
        raise NotImplementedError

    def query_certifications(self) -> dict[str, bool]:
        """Return map of certification name → whether we hold it."""
        if self.mock_mode:
            return {
                "SOC 2 Type II": True,
                "ISO 27001": True,
                "GDPR DPA": True,
                "HIPAA": True,
                "FedRAMP": False,
                "PCI DSS": True,
            }
        raise NotImplementedError

    def query_pricing_rules(self) -> dict[str, Any]:
        """Return pricing formula parameters."""
        if self.mock_mode:
            return {
                "base_cost": 150_000,
                "per_requirement_cost": 2_500,
                "complexity_tiers": {"low": 1.0, "medium": 1.25, "high": 1.5},
                "risk_margin_percent": 0.10,
                "payment_terms": "30/40/30 milestone-based",
            }
        raise NotImplementedError

    def query_legal_templates(self) -> list[dict[str, str]]:
        """Return company legal templates for clause comparison."""
        if self.mock_mode:
            return [
                {"clause_type": "liability", "template": "Liability limited to 2x annual contract value."},
                {"clause_type": "ip_ownership", "template": "Pre-existing IP remains with vendor."},
                {"clause_type": "indemnification", "template": "Mutual indemnification for negligence only."},
            ]
        raise NotImplementedError
