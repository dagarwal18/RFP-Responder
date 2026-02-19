"""
MCPService — the ONLY class agents should import.

This is the facade over:
  • RFP Vector Store   (embed + query incoming RFP chunks)
  • Knowledge Base     (company capabilities, certs, pricing, legal templates)
  • Rules Engine       (policy / validation / commercial-legal gates)

Internally the stores use embeddings/ helpers
but agents never see those.
"""

from __future__ import annotations

import logging
from typing import Any

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)


class MCPService:
    """
    Facade over all MCP layers.
    Agents depend on this single class — swap the implementation underneath
    when moving from mock → real.

    Usage in any agent:
        from rfp_automation.mcp import MCPService
        mcp = MCPService()
        chunks = mcp.rfp_store.query("security requirements", rfp_id="RFP-001")
    """

    def __init__(self):
        settings = get_settings()
        self.mock_mode = settings.mock_mode

        from .vector_store.rfp_store import RFPVectorStore
        from .vector_store.knowledge_store import KnowledgeStore
        from .rules.policy_rules import PolicyRules
        from .rules.validation_rules import ValidationRules
        from .rules.commercial_rules import CommercialRules
        from .rules.legal_rules import LegalRules

        self.rfp_store = RFPVectorStore(mock_mode=self.mock_mode)
        self.knowledge_base = KnowledgeStore(mock_mode=self.mock_mode)
        self.policy_rules = PolicyRules(mock_mode=self.mock_mode)
        self.validation_rules = ValidationRules(mock_mode=self.mock_mode)
        self.commercial_rules = CommercialRules(mock_mode=self.mock_mode)
        self.legal_rules = LegalRules(mock_mode=self.mock_mode)

    async def health_check(self) -> dict[str, bool]:
        return {
            "rfp_store": True,
            "knowledge_base": True,
            "rules_engine": True,
        }
