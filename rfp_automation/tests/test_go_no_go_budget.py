from rfp_automation.agents.go_no_go_agent import GoNoGoAgent


def test_go_no_go_prompt_budget_compacts_large_context():
    agent = GoNoGoAgent()
    sections = [
        {
            "section_id": f"SEC-{idx:03d}",
            "title": f"Technical Security Section {idx}",
            "category": "technical" if idx % 2 else "compliance",
            "content_summary": (
                "Managed SD-WAN, cloud interconnect, SOC operations, DPDP compliance, "
                "pricing, eligibility, and SLA commitments are mandatory for this programme. "
            ) * 4,
        }
        for idx in range(1, 90)
    ]
    policies = [
        {
            "policy_id": f"POL-{idx:03d}",
            "category": "security",
            "policy_text": (
                "Maintain ISO 27001, SOC 2, India data residency, 24x7 support, "
                "cloud networking capability, and security operations controls. "
            ) * 5,
        }
        for idx in range(1, 500)
    ]
    capabilities = [
        {
            "text": (
                "Delivered managed SD-WAN, cloud interconnect, SOC, compliance, "
                "and mobility programmes across India. "
            ) * 3
        }
        for _ in range(10)
    ]

    rfp_text = agent._format_sections(sections)
    policy_text = agent._format_relevant_policies(policies, rfp_text)
    capability_text = agent._format_capabilities(capabilities)
    prompt = agent._build_prompt(rfp_text, policy_text, capability_text)

    assert len(rfp_text) <= 4800
    assert len(policy_text) <= 3000
    assert len(capability_text) <= 2000
    assert len(prompt) < 10000
