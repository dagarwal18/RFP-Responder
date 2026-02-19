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
        assert "FedRAMP" in violations[0]


class TestValidationRules:
    def test_clean_text_passes(self):
        vr = ValidationRules()
        violations = vr.check_validation_rules("We will deliver the solution on time.")
        assert len(violations) == 0

    def test_guarantee_flagged(self):
        vr = ValidationRules()
        violations = vr.check_validation_rules("We guarantee 100% uptime forever.")
        assert len(violations) > 0


class TestCommercialRules:
    def test_valid_pricing(self):
        cr = CommercialRules()
        violations = cr.validate_pricing(total_price=500_000)
        assert len(violations) == 0

    def test_exceeds_max_contract(self):
        cr = CommercialRules()
        violations = cr.validate_pricing(total_price=2_000_000, max_contract_value=1_000_000)
        assert len(violations) == 1

    def test_within_max_contract(self):
        cr = CommercialRules()
        violations = cr.validate_pricing(total_price=500_000, max_contract_value=1_000_000)
        assert len(violations) == 0


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
