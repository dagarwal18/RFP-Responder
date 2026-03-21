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
from rfp_automation.orchestration import graph as graph_module


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


def test_legal_parse_failure_blocks(empty_state, monkeypatch):
    """Malformed E2 LLM output should fail closed instead of silently approving."""
    agent = LegalAgent()

    mcp = MagicMock()
    mcp.legal_rules.evaluate_clauses.return_value = {
        "blocked": False,
        "block_reasons": [],
        "aggregate_risk": "low",
        "clause_scores": [],
    }
    mcp.policy_rules._config_store = RulesConfigStore()
    mcp.legal_rules._config_store = RulesConfigStore()
    mcp.query_knowledge.return_value = []
    mcp.query_rfp.return_value = []

    monkeypatch.setattr("rfp_automation.agents.legal_agent.MCPService", lambda: mcp)
    monkeypatch.setattr(
        agent,
        "_run_llm_analysis",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad json")),
    )
    monkeypatch.setattr(agent, "_extract_required_certs", lambda *args, **kwargs: [])
    mcp.get_certifications_from_policies.return_value = {}

    state = empty_state
    result = agent._real_process(state)

    assert result.legal_result.decision.value == "BLOCKED"
    assert any("Manual legal review required" in reason for reason in result.legal_result.block_reasons)


def test_run_pipeline_from_uses_requested_entry(monkeypatch):
    """Reruns should start from the requested node, not replay the H1 end edge."""
    seen: dict[str, str] = {}

    class FakeCompiledGraph:
        def stream(self, state):
            yield {
                "f1_final_readiness": {
                    **state,
                    "status": "SUBMITTING",
                }
            }

    def fake_build_graph(entry_point="a1_intake"):
        seen["entry_point"] = entry_point
        return FakeCompiledGraph()

    monkeypatch.setattr(graph_module, "build_graph", fake_build_graph)

    result = graph_module.run_pipeline_from(
        "f1_final_readiness",
        {"status": "AWAITING_HUMAN_VALIDATION"},
    )

    assert seen["entry_point"] == "f1_final_readiness"
    assert result["status"] == "SUBMITTING"
