"""
Tests: MCP Rule engines.

Run with:
    pytest rfp_automation/tests/test_rules.py -v
"""

import pytest
from rfp_automation.mcp.rules.policy_rules import PolicyRules
from rfp_automation.mcp.rules.validation_rules import ValidationRules
from rfp_automation.mcp.rules.commercial_rules import CommercialRules
from rfp_automation.mcp.rules.legal_rules import LegalRules


class TestPolicyRules:
    def test_all_certs_held(self):
        pr = PolicyRules()
        violations = pr.check_policy_rules(
            required_certs=["ISO 27001", "SOC 2"],
            held_certs={"ISO 27001": True, "SOC 2": True, "FedRAMP": True},
        )
        assert len(violations) == 0

    def test_missing_cert(self):
        pr = PolicyRules()
        violations = pr.check_policy_rules(
            required_certs=["ISO 27001", "FedRAMP"],
            held_certs={"ISO 27001": True},
        )
        assert len(violations) == 1
        assert violations[0]["rule"] == "certification_gap"
        assert "FedRAMP" in violations[0]["detail"]

    def test_contract_too_large(self):
        pr = PolicyRules()
        violations = pr.check_policy_rules(
            required_certs=[],
            held_certs={},
            contract_value=20_000_000,
        )
        # Should flag because default max is 10M
        contract_violations = [v for v in violations if v["rule"] == "contract_too_large"]
        assert len(contract_violations) == 1


class TestValidationRules:
    def test_clean_text_passes(self):
        vr = ValidationRules()
        violations = vr.check_validation_rules("We will deliver the solution on time.")
        assert len(violations) == 0

    def test_prohibited_phrase_flagged(self):
        vr = ValidationRules()
        violations = vr.check_validation_rules("We guarantee 100% uptime forever.")
        assert len(violations) > 0
        rules = [v["rule"] for v in violations]
        assert "prohibited_language" in rules

    def test_contradiction_detected(self):
        vr = ValidationRules()
        violations = vr.check_validation_rules(
            "We offer 24/7 support. Support is available during business hours only."
        )
        contradiction_violations = [v for v in violations if v["rule"] == "consistency_conflict"]
        assert len(contradiction_violations) > 0


class TestCommercialRules:
    def test_valid_pricing(self):
        cr = CommercialRules()
        violations = cr.validate_pricing(total_price=500_000)
        assert len(violations) == 0

    def test_exceeds_max_contract(self):
        cr = CommercialRules()
        violations = cr.validate_pricing(total_price=10_000_000)
        # Default max is 5M
        assert any(v["rule"] == "contract_value_exceeded" for v in violations)

    def test_margin_too_low(self):
        cr = CommercialRules()
        violations = cr.validate_pricing(total_price=100_000, total_cost=95_000)
        # 5% margin < 15% minimum
        assert any(v["rule"] == "margin_too_low" for v in violations)

    def test_healthy_margin(self):
        cr = CommercialRules()
        violations = cr.validate_pricing(total_price=100_000, total_cost=70_000)
        # 30% margin > 15% minimum
        margin_violations = [v for v in violations if v["rule"] == "margin_too_low"]
        assert len(margin_violations) == 0


class TestLegalRules:
    def test_clear_gate(self):
        lr = LegalRules()
        result = lr.evaluate_commercial_legal_gate(
            legal_decision="CONDITIONAL",
            legal_block_reasons=[],
            pricing_total=500_000,
        )
        assert result["gate_decision"] == "CLEAR"

    def test_blocked_gate(self):
        lr = LegalRules()
        result = lr.evaluate_commercial_legal_gate(
            legal_decision="BLOCKED",
            legal_block_reasons=["Unlimited liability clause"],
            pricing_total=500_000,
        )
        assert result["gate_decision"] == "BLOCK"

    def test_clause_scoring_auto_block(self):
        lr = LegalRules()
        result = lr.score_clause(
            "The contractor accepts unlimited liability for all damages."
        )
        assert result["blocked"] is True
        assert result["risk_level"] == "critical"

    def test_clause_scoring_clean(self):
        lr = LegalRules()
        result = lr.score_clause(
            "Standard limitation of liability applies per contract terms."
        )
        assert result["blocked"] is False
        assert result["risk_level"] == "low"
