import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from rfp_automation.agents.architecture_agent import ArchitecturePlanningAgent
from rfp_automation.agents.legal_agent import LegalAgent
from rfp_automation.agents.narrative_agent import NarrativeAssemblyAgent
from rfp_automation.agents.requirement_extraction_agent import RequirementsExtractionAgent
from rfp_automation.agents.writing_agent import RequirementWritingAgent
from rfp_automation.agents.final_readiness_agent import FinalReadinessAgent
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import AssembledProposal, CommercialResult, LegalResult
from rfp_automation.models.schemas import ResponseSection
from rfp_automation.utils.mermaid_utils import _sanitize_mermaid_code

_MD_TO_PDF_PATH = Path(__file__).resolve().parents[2] / "scripts" / "md_to_pdf.py"
_MD_TO_PDF_SPEC = importlib.util.spec_from_file_location("md_to_pdf", _MD_TO_PDF_PATH)
assert _MD_TO_PDF_SPEC and _MD_TO_PDF_SPEC.loader
_MD_TO_PDF = importlib.util.module_from_spec(_MD_TO_PDF_SPEC)
_MD_TO_PDF_SPEC.loader.exec_module(_MD_TO_PDF)
_scrub_markdown = _MD_TO_PDF._scrub_markdown
_inject_table_width_hints = _MD_TO_PDF._inject_table_width_hints


def test_vendor_fill_detection_requires_real_fill_signals():
    agent = RequirementWritingAgent()

    informational = (
        "# | Criterion | Description | Evidence Required\n"
        "1 | Annual Revenue | Must exceed INR 500 Crore | Audited statements"
    )
    pricing_fill = (
        "Line # | Item Description | Category | Unit Type | NRC (One-Time) INR | MRC / Annual INR\n"
        "1.01 | SD-WAN CPE Hardware | SD-WAN | Per device / month | — | [Vendor to fill]"
    )

    assert agent._is_vendor_fill_table(pricing_fill, "fill_in_table") is True
    assert agent._is_vendor_fill_table(informational, "fill_in_table") is False


def test_extract_table_header_lines_does_not_copy_source_rows():
    agent = RequirementWritingAgent()
    table_text = (
        "TR-ID | Requirement | Description | Compliance | C/PC/NC | Vendor to fill\n"
        "TR-005 | OEM Hardware | Vendor MUST specify OEM | Mandatory | [C / PC / NC] | [Vendor to fill — Name OEM]\n"
        "TR-006 | QoS | Support 8 classes | Mandatory | [C / PC / NC] | [Vendor to fill]\n"
    )

    assert agent._extract_table_header_lines(table_text) == [
        "TR-ID | Requirement | Description | Compliance | C/PC/NC | Vendor to fill"
    ]


def test_narrative_cleanup_preserves_table_placeholders(monkeypatch):
    agent = NarrativeAssemblyAgent()
    fake_module = types.ModuleType("knowledge_store")
    fake_module.KnowledgeStore = lambda: SimpleNamespace(query_company_profile=lambda: {})
    monkeypatch.setitem(
        sys.modules,
        "rfp_automation.mcp.vector_store.knowledge_store",
        fake_module,
    )
    monkeypatch.setattr(
        "rfp_automation.agents.narrative_agent.get_settings",
        lambda: SimpleNamespace(company_name=""),
    )

    text = (
        "Cover note [TBD]\n\n"
        "Req | Vendor Response\n"
        "TR-001 | [Vendor to fill]\n"
    )
    cleaned = agent._clean_known_placeholders(text, {"issue_date": "2026-03-24"})

    assert "**⚠ [TBD — Requires Manual Input]**" in cleaned
    assert "[Vendor to fill]" in cleaned


def test_scrub_markdown_drops_headerless_malformed_table_fragments():
    md_text = (
        "# | Criterion | Description | Evidence Required\n"
        "1 | Annual Revenue | Revenue must exceed INR 500 Crore | Audited financial statements\n"
        "|---|---|---|---|\n"
        "| 1 | Annual Revenue | Revenue must exceed INR 500 Crore | Audited financial statements | Y | Our revenue exceeds the threshold. | - | Compliant |\n"
    )

    scrubbed = _scrub_markdown(md_text)

    assert "Compliant" not in scrubbed
    assert scrubbed.count("Annual Revenue") == 1


def test_architecture_normalizes_vendor_fill_sections():
    agent = ArchitecturePlanningAgent()
    requirements = [
        {"requirement_id": "TR-001", "source_table_chunk_index": 173},
        {"requirement_id": "TR-002", "source_table_chunk_index": 173},
        {"requirement_id": "REQ-0007", "source_table_chunk_index": 80},
        {"requirement_id": "1.01", "source_table_chunk_index": 188},
        {"requirement_id": "4.04", "source_table_chunk_index": 189},
        {"requirement_id": "CM-06", "source_table_chunk_index": 195},
    ]
    sections = [
        ResponseSection(
            section_id="SEC-04",
            title="SD-WAN Architecture & Implementation",
            section_type="requirement_driven",
            requirement_ids=["TR-001", "REQ-0007", "1.01", "CM-06"],
            priority=4,
        ),
        ResponseSection(
            section_id="SEC-05",
            title="Cloud Interconnect Solutions",
            section_type="requirement_driven",
            requirement_ids=["TR-002", "4.04"],
            priority=5,
        ),
    ]

    normalized = agent._normalize_vendor_fill_sections(requirements, sections)
    by_title = {section.title: section for section in normalized}
    section_ids = [section.section_id for section in normalized]

    tech_title = next(title for title in by_title if "Technical Compliance Matrix" in title)
    assert by_title[tech_title].requirement_ids[:2] == ["TR-001", "TR-002"]
    assert by_title["Pricing Schedule Matrix"].requirement_ids == ["1.01", "4.04"]
    assert by_title["Appendix Forms & Declarations"].requirement_ids == ["CM-06"]
    assert any("Network & Edge Architecture" in section.title for section in normalized)
    assert any("REQ-0007" in section.requirement_ids for section in normalized)
    assert len(section_ids) == len(set(section_ids))


def test_order_generated_rows_drops_unlabeled_extras_for_exact_table_batches():
    agent = RequirementWritingAgent()

    ordered = agent._order_generated_rows(
        data_lines=[
            "| TR-002 | Requirement B | Partial |",
            "| Extra note without id | keep me? | no |",
            "| TR-001 | Requirement A | Full |",
        ],
        batch_rids=["TR-001", "TR-002"],
    )

    assert ordered == [
        "| TR-001 | Requirement A | Full |",
        "| TR-002 | Requirement B | Partial |",
    ]


def test_final_markdown_contains_only_proposal_body():
    state = RFPGraphState(
        assembled_proposal=AssembledProposal(
            full_narrative=(
                "# Proposal Body\n\n"
                "## Technical Implementation Framework\n\n"
                "Overview text.\n\n"
                "```mermaid\nflowchart TD\n\n\n```\n\n"
                "## Technical Implementation\n\n"
                "### Technical Compliance Matrix\n\n"
                "| Req. ID | Description | Vendor Response |\n"
                "|---|---|---|\n"
                "| TR-001 | First row | C |\n\n"
                "> **Note:** [PIPELINE_STUB: Commercial Terms]\n\n"
                "> **Note:** [PIPELINE_STUB: Legal & Compliance]\n\n"
                "## Appendix Forms & Declarations\n\n"
                "### Compliance Matrix\n\n"
                "| Ref. | Requirement | Status |\n"
                "|---|---|---|\n"
                "| CM-05 | Placeholder row | [Vendor to fill] |\n\n"
                "| CM-05 | Final row | C |\n"
            )
        ),
        commercial_result=CommercialResult(
            commercial_narrative="Commercial narrative only."
        ),
        legal_result=LegalResult(
            legal_narrative="Legal narrative only."
        ),
    )

    markdown = FinalReadinessAgent._build_markdown(state, "2026-03-25T00:00:00Z")

    assert markdown.startswith("# Proposal Body")
    assert "## Technical Implementation Framework" not in markdown
    assert markdown.count("## Technical Implementation") == 1
    assert "```mermaid" not in markdown
    assert markdown.count("CM-05") == 1
    assert "| CM-05 | Final row | C |" in markdown
    assert "Pricing Line Items" not in markdown
    assert "Human Validation" not in markdown


def test_extract_relevant_table_text_keeps_only_requested_rows():
    agent = RequirementWritingAgent()
    table_text = (
        "Item ID | Description | Vendor to fill | Vendor to fill\n"
        "2.02 | AWS Direct Connect | [Vendor to fill] | [Vendor to fill]\n"
        "4.04 | eSIM Remote Provisioning Platform | [Vendor to fill] | -\n"
    )

    filtered = agent._extract_relevant_table_text(table_text, ["4.04"])

    assert "4.04" in filtered
    assert "2.02" not in filtered


def test_coverage_downgrades_unresolved_table_rows():
    agent = RequirementWritingAgent()
    matrix = agent._build_coverage_matrix(
        req_map={
            "CM-06": {"source_table_chunk_index": 195},
            "4.04": {"source_table_chunk_index": 189},
        },
        all_addressed={
            "CM-06": ["SEC-95"],
            "4.04": ["SEC-90"],
        },
        c1_assignments={
            "CM-06": ["SEC-95"],
            "4.04": ["SEC-90"],
        },
        section_content_by_id={
            "SEC-95": "| CM-06 | India Legal Entity | C | [Appendix B] | Our company, [Proposing Company], is registered in India. |",
            "SEC-90": "| 4.04 | eSIM Remote Provisioning Platform | INR 100 | - |",
        },
    )
    by_id = {entry.requirement_id: entry.coverage_quality for entry in matrix}

    assert by_id["CM-06"] == "partial"
    assert by_id["4.04"] == "full"


def test_requirement_extraction_recovers_skipped_table_row_ids():
    agent = RequirementsExtractionAgent()
    recovered = agent._recover_missing_table_rows(
        table_text=(
            "Item ID | Description | Service Type | Pricing Model | Vendor to fill | Vendor to fill\n"
            "4.04 | eSIM Remote Provisioning Platform (per SIM, one-time migration) | IoT Mobility | Per SIM | [Vendor to fill] | -\n"
        ),
        section_name="Pricing",
        parsed=[],
        chunk_indices=[189],
    )

    assert [req.requirement_id for req in recovered] == ["4.04"]


def test_table_extraction_falls_back_to_row_recovery_on_llm_error(monkeypatch):
    agent = RequirementsExtractionAgent()

    monkeypatch.setattr(
        "rfp_automation.agents.requirement_extraction_agent.llm_deterministic_call",
        lambda _prompt: (_ for _ in ()).throw(RuntimeError("rate limit")),
    )

    recovered = agent._extract_from_table(
        table_text=(
            "Item ID | Description | Service Type | Pricing Model | Vendor to fill | Vendor to fill\n"
            "4.04 | eSIM Remote Provisioning Platform (per SIM, one-time migration) | IoT Mobility | Per SIM | [Vendor to fill] | -\n"
        ),
        section_name="Pricing",
        template="",
        chunk_indices=[189],
    )

    assert [req.requirement_id for req in recovered] == ["4.04"]


def test_logical_table_groups_merge_consecutive_multipage_chunks():
    agent = RequirementWritingAgent()
    table_groups = {
        173: ["TR-001", "TR-002"],
        174: ["TR-003"],
        188: ["1.01"],
        189: ["2.02"],
        194: ["REF-1"],
        195: ["CM-06"],
    }
    table_chunks_by_index = {
        173: {"chunk_index": 173, "table_type": "fill_in_table", "section_hint": "RFP", "text": "Req. ID | Category | Description | Priority | Vendor Response | Vendor Remarks\nTR-001 | A | Desc | Mandatory | [C / PC / NC] | [Vendor to fill]"},
        174: {"chunk_index": 174, "table_type": "fill_in_table", "section_hint": "RFP", "text": "TR-ID | Requirement | Description | Compliance | C/PC/NC | Vendor to fill\nTR-003 | A | Desc | Mandatory | [C / PC / NC] | [Vendor to fill]"},
        188: {"chunk_index": 188, "table_type": "fill_in_table", "section_hint": "RFP", "text": "Line # | Item Description | Category | Unit Type | NRC | MRC\n1.01 | SD-WAN | SD-WAN | Per month | - | [Vendor to fill]"},
        189: {"chunk_index": 189, "table_type": "fill_in_table", "section_hint": "RFP", "text": "Item ID | Description | Service Type | Pricing Model | Vendor to fill | Vendor to fill\n2.02 | AWS Direct Connect | Cloud | Per month | [Vendor to fill] | [Vendor to fill]"},
        194: {"chunk_index": 194, "table_type": "fill_in_table", "section_hint": "RFP", "text": "Client Name | Industry | Sites Deployed | Go-Live Date | Services Provided | Outcome Metrics | Reference Contact\n[Vendor to fill] | [Vendor to fill] | [Vendor to fill] | [Vendor to fill] | [Vendor to fill] | [Vendor to fill] | [Vendor to fill]"},
        195: {"chunk_index": 195, "table_type": "fill_in_table", "section_hint": "RFP", "text": "CM-Number | Requirement Description | Compliance Status | Reference | Vendor Response\nCM-06 | India Legal Entity | [C/PC/NC] | [Appendix B] | [Vendor to fill]"},
    }

    groups = agent._build_logical_table_groups(table_groups, table_chunks_by_index)

    assert groups[0]["chunk_indices"] == [173, 174]
    assert groups[1]["chunk_indices"] == [188, 189]
    assert groups[2]["chunk_indices"] == [194]
    assert groups[3]["chunk_indices"] == [195]


def test_fill_single_table_appends_rows_once_and_in_order(monkeypatch):
    agent = RequirementWritingAgent()
    responses = iter([
        """{"content":"| Item ID | Description | Vendor Response |\n|---|---|---|\n| 1.01 | SD-WAN | Filled A |\n| 1.02 | Branch | Filled B |","requirements_addressed":["1.01","1.02"],"word_count":10}""",
        """{"content":"| Item ID | Description | Vendor Response |\n|---|---|---|\n| 1.01 | SD-WAN | Filled A |\n| 1.02 | Branch | Filled B |\n| 2.01 | Cloud | Filled C |\n| 2.02 | SOC | Filled D |","requirements_addressed":["2.01","2.02"],"word_count":10}""",
    ])

    monkeypatch.setattr(
        "rfp_automation.agents.writing_agent.llm_large_text_call",
        lambda prompt, deterministic=True: next(responses),
    )
    monkeypatch.setattr(
        "rfp_automation.agents.writing_agent.time.sleep",
        lambda *_args, **_kwargs: None,
    )

    content, addressed, _ = agent._fill_single_table(
        table_text=(
            "Item ID | Description | Vendor Response\n"
            "1.01 | SD-WAN | [Vendor to fill]\n"
            "1.02 | Branch | [Vendor to fill]\n"
            "2.01 | Cloud | [Vendor to fill]\n"
            "2.02 | SOC | [Vendor to fill]\n"
        ),
        req_ids=["1.01", "1.02", "2.01", "2.02"],
        req_map={rid: {"requirement_id": rid, "text": rid, "type": "MANDATORY"} for rid in ["1.01", "1.02", "2.01", "2.02"]},
        section=ResponseSection(section_id="SEC-90", title="Pricing Schedule Matrix"),
        capabilities="",
        rfp_instructions="",
        rfp_metadata_block="",
        prev_ctx="",
        next_ctx="",
        section_feedback="",
        section_id="SEC-90",
        title="Pricing Schedule Matrix",
        section_type="requirement_driven",
        batch_size=2,
        original_headers=["Item ID | Description | Vendor Response"],
    )

    assert content.count("1.01") == 1
    assert content.count("1.02") == 1
    assert content.count("2.01") == 1
    assert content.count("2.02") == 1
    assert content.index("1.01") < content.index("1.02") < content.index("2.01") < content.index("2.02")
    assert addressed == ["1.01", "1.02", "2.01", "2.02"]


def test_prose_sections_strip_markdown_tables():
    agent = RequirementWritingAgent()
    content = (
        "Narrative intro.\n\n"
        "| Req ID | Response |\n"
        "|---|---|\n"
        "| KPI-01 | Hallucinated row |\n\n"
        "Closing paragraph."
    )

    stripped = agent._strip_markdown_tables(content)

    assert "KPI-01" not in stripped
    assert "Narrative intro." in stripped
    assert "Closing paragraph." in stripped


def test_scrub_markdown_preserves_valid_wide_tables():
    md_text = (
        "### Pricing Schedule Matrix\n\n"
        "Item ID | Description | Service Type | Pricing Model | NRC | MRC\n"
        "1.01 | SD-WAN CPE | Network | Per site | 1000 | 100\n"
        "1.02 | Managed Router | Network | Per site | 500 | 50\n"
    )

    scrubbed = _scrub_markdown(md_text)

    assert "```text" not in scrubbed
    assert "| Item ID | Description | Service Type | Pricing Model | NRC | MRC |" in scrubbed
    assert "| 1.01 | SD-WAN CPE | Network | Per site | 1000 | 100 |" in scrubbed


def test_inject_table_width_hints_adds_colgroup_for_six_column_tables():
    html = (
        "<table><thead><tr>"
        "<th>Req. ID</th><th>Category</th><th>Description</th>"
        "<th>Priority</th><th>Vendor Response</th><th>Vendor Remarks</th>"
        "</tr></thead><tbody><tr>"
        "<td>TR-001</td><td>SD-WAN</td><td>Desc</td><td>Mandatory</td><td>Yes</td><td>Short</td>"
        "</tr></tbody></table>"
    )

    rewritten = _inject_table_width_hints(html)

    assert '<table style="width:100%; table-layout:fixed;">' in rewritten
    assert rewritten.count("<col width=") == 6


def test_scrub_markdown_splits_large_tables_into_renderable_chunks():
    rows = "\n".join(
        f"{idx}.01 | Item {idx} | Service | Per month | 100 | 10"
        for idx in range(1, 11)
    )
    md_text = (
        "Item ID | Description | Service Type | Pricing Model | NRC | MRC\n"
        f"{rows}\n"
    )

    scrubbed = _scrub_markdown(md_text)

    assert scrubbed.count("| Item ID | Description | Service Type | Pricing Model | NRC | MRC |") == 2


def test_sanitize_mermaid_code_repairs_gantt_ranges():
    code = (
        "gantt\n"
        "title Migration Timeline\n"
        "desc 300-site migration within 18 months\n"
        "section Deployment\n"
        "Pilot Migration : 2025-11-01, 2025-11-30\n"
        "National Rollout : 2025-12-01, 2026-06-30\n"
    )

    sanitized = _sanitize_mermaid_code(code)

    assert "desc 300-site migration within 18 months" not in sanitized
    assert "dateFormat YYYY-MM-DD" in sanitized
    assert "Pilot Migration : task_1, 2025-11-01, 2025-11-30" in sanitized
    assert "National Rollout : task_2, 2025-12-01, 2026-06-30" in sanitized


def test_legal_agent_prefers_raw_clause_text_over_generic_summary():
    agent = LegalAgent()
    state = SimpleNamespace(
        structuring_result=SimpleNamespace(
            sections=[
                SimpleNamespace(
                    category="legal",
                    title="Legal Disclaimer and Confidentiality Notice",
                    content_summary="Includes legal disclaimers and confidentiality obligations.",
                )
            ]
        )
    )
    fake_mcp = SimpleNamespace(
        fetch_all_rfp_chunks=lambda _rfp_id: [
            {
                "content_type": "text",
                "section_hint": "Legal Disclaimer and Confidentiality Notice",
                "text": "Apex reserves the right to reject any or all proposals without incurring any liability to responding vendors.",
            },
            {
                "content_type": "text",
                "section_hint": "Project Overview",
                "text": "The programme includes SD-WAN rollout across 300 sites.",
            },
        ],
        query_rfp=lambda *_args, **_kwargs: [],
    )

    clauses = agent._extract_clauses(state, fake_mcp, "RFP-TEST")

    assert any("without incurring any liability" in clause for clause in clauses)
    assert not any("300 sites" in clause for clause in clauses)
