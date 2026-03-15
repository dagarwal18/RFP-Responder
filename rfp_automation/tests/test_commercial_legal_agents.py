"""
Tests: E1 Commercial and E2 Legal Agent Logic.

Run with:
    pytest rfp_automation/tests/test_commercial_legal_agents.py -v
"""

import pytest
from unittest.mock import MagicMock, patch

from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import (
    Requirement,
    RequirementsValidationResult,
    WritingResult,
    CoverageEntry,
)
from rfp_automation.agents.commercial_agent import CommercialAgent
from rfp_automation.agents.legal_agent import LegalAgent
from rfp_automation.mcp.rules.rules_config import RulesConfigStore


@pytest.fixture
def empty_state():
    state = RFPGraphState()
    # Mock A1 Intake details
    state.rfp_metadata.rfp_id = "test-rfp"
    state.rfp_metadata.client_name = "Acme Corp"
    state.rfp_metadata.rfp_title = "Data Migration Service"
    return state


# ── E1 Commercial Agent Tests ──────────────────────────────

def test_scope_analysis(empty_state):
    """E1 should correctly count requirements by category."""
    agent = CommercialAgent()
    empty_state.requirements_validation = RequirementsValidationResult(
        validated_requirements=[
            Requirement(requirement_id="1", text="Req 1", category="TECHNICAL"),
            Requirement(requirement_id="2", text="Req 2", category="TECHNICAL"),
            Requirement(requirement_id="3", text="Req 3", category="SECURITY"),
        ]
    )
    req_counts, total = agent._analyse_scope(empty_state)
    assert total == 3
    assert req_counts.get("TECHNICAL") == 2
    assert req_counts.get("SECURITY") == 1
    assert "COMMERCIAL" not in req_counts


def test_compute_complexity(empty_state):
    """E1 should compute complexity based on coverage matrix quality."""
    agent = CommercialAgent()
    
    # 2 full (1.0 each), 1 partial (1.2), 1 missing (1.5)
    # Total = (2 + 1.2 + 1.5) / 4 = 4.7 / 4 = 1.175 -> round to 1.18
    empty_state.writing_result = WritingResult(
        coverage_matrix=[
            CoverageEntry(requirement_id="1", addressed_in_section="A", coverage_quality="full"),
            CoverageEntry(requirement_id="2", addressed_in_section="B", coverage_quality="full"),
            CoverageEntry(requirement_id="3", addressed_in_section="C", coverage_quality="partial"),
            CoverageEntry(requirement_id="4", addressed_in_section="D", coverage_quality="missing"),
        ]
    )
    
    multiplier = agent._compute_complexity(empty_state)
    # 4.7 / 4.0 = 1.175
    assert multiplier == 1.18

    # Empty coverage matrix
    empty_state.writing_result.coverage_matrix = []
    assert agent._compute_complexity(empty_state) == 1.0


def test_compute_pricing(empty_state):
    """E1 should compute deterministic pricing math."""
    agent = CommercialAgent()
    config = {
        "base_cost": 10000.0,
        "per_requirement_cost": 1000.0,
        "complexity_tiers": {"medium": 1.25, "high": 1.5},
    }
    
    # "TECHNICAL" defaults to "high" (1.5). 1 req * 1000 * 1.5 * 1.2 cmplx = 1800
    # "FUNCTIONAL" defaults to "medium" (1.25). 2 reqs * 1000 * 1.25 * 1.2 cmplx = 3000
    req_counts = {"TECHNICAL": 1, "FUNCTIONAL": 2}
    complexity = 1.2

    line_items, subtotal = agent._compute_pricing(req_counts, complexity, config)
    
    # 1 base + 2 categories
    assert len(line_items) == 3
    
    base_item = next(item for item in line_items if item.category == "base")
    assert base_item.total == 10000.0
    
    tech_item = next(item for item in line_items if item.category == "TECHNICAL")
    assert tech_item.total == 1800.0
    
    func_item = next(item for item in line_items if item.category == "FUNCTIONAL")
    assert func_item.total == 3000.0
    
    assert subtotal == 14800.0


# ── E2 Legal Agent Tests ───────────────────────────────────

def test_check_compliance_all_held(empty_state):
    """E2 should correctly assert certifications are held."""
    agent = LegalAgent()
    mcp = MagicMock()
    mcp.legal_rules._config_store = RulesConfigStore()
    mcp.policy_rules._config_store = RulesConfigStore()
    
    held = {"ISO 27001": True, "SOC 2 Type II": True}
    required = ["ISO 27001", "SOC 2 Type II"]
    
    checks = agent._check_compliance(required, held, mcp)
    
    assert len(checks) == 2
    for check in checks:
        assert check.held is True
        assert check.required is True
        assert check.gap_severity == "low"


def test_check_compliance_gap(empty_state):
    """E2 should identify critical cert gaps."""
    agent = LegalAgent()
    mcp = MagicMock()
    # Mock PolicyConfig mapping severity -> FEDRAMP MODERATE is critical
    class MockConfig:
        certification_gap_severity = {"FedRAMP Moderate": "critical", "ISO 27001": "high"}
    
    mcp.legal_rules._config_store = RulesConfigStore()
    mcp.policy_rules._config_store = MagicMock()
    mcp.policy_rules._config_store.get_policy_config.return_value = MockConfig()
    
    held = {"ISO 27001": True}
    required = ["ISO 27001", "FedRAMP Moderate"]
    
    checks = agent._check_compliance(required, held, mcp)
    assert len(checks) == 2
    
    fedramp = next(c for c in checks if c.certification == "FedRAMP Moderate")
    assert fedramp.held is False
    assert fedramp.gap_severity == "critical"
    
    iso = next(c for c in checks if c.certification == "ISO 27001")
    assert iso.held is True
    assert iso.gap_severity == "low"


def test_determine_decision(empty_state):
    """E2 decision tree combining rule scores + LLM scores + cert gaps."""
    agent = LegalAgent()
    
    # Case 1: All clear
    dec, reas = agent._determine_decision(
        rules_blocked=False, rule_block_reasons=[],
        llm_decision="APPROVED", llm_block_reasons=[],
        llm_clause_risks=[{"risk_level": "LOW"}],
        critical_cert_gaps=[],
    )
    assert dec.value == "APPROVED"
    assert len(reas) == 0

    # Case 2: Rule blocked overrides
    dec, reas = agent._determine_decision(
        rules_blocked=True, rule_block_reasons=["Unlimited IP"],
        llm_decision="APPROVED", llm_block_reasons=[],
        llm_clause_risks=[{"risk_level": "LOW"}],
        critical_cert_gaps=[],
    )
    assert dec.value == "BLOCKED"
    assert "Unlimited IP" in reas

    # Case 3: LLM high risk -> CONDITIONAL
    dec, reas = agent._determine_decision(
        rules_blocked=False, rule_block_reasons=[],
        llm_decision="APPROVED", llm_block_reasons=[],
        llm_clause_risks=[{"risk_level": "HIGH"}],
        critical_cert_gaps=[],
    )
    assert dec.value == "CONDITIONAL"

    # Case 4: Critical cert gap -> BLOCKED
    from rfp_automation.models.schemas import ComplianceCheck
    gap = ComplianceCheck(certification="FedRAMP", required=True, gap_severity="critical")
    dec, reas = agent._determine_decision(
        rules_blocked=False, rule_block_reasons=[],
        llm_decision="APPROVED", llm_block_reasons=[],
        llm_clause_risks=[{"risk_level": "LOW"}],
        critical_cert_gaps=[gap],
    )
    assert dec.value == "BLOCKED"
    assert any("FedRAMP" in r for r in reas)

    # Case 5: High cert gap → CONDITIONAL (not APPROVED)
    high_gap = ComplianceCheck(certification="PCI DSS", required=True, gap_severity="high")
    dec, reas = agent._determine_decision(
        rules_blocked=False, rule_block_reasons=[],
        llm_decision="APPROVED", llm_block_reasons=[],
        llm_clause_risks=[{"risk_level": "LOW"}],
        critical_cert_gaps=[],
        high_cert_gaps=[high_gap],
    )
    assert dec.value == "CONDITIONAL"
    assert any("PCI DSS" in r for r in reas)
