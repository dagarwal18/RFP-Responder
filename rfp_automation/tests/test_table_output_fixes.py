import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from rfp_automation.agents.architecture_agent import ArchitecturePlanningAgent
from rfp_automation.agents.narrative_agent import NarrativeAssemblyAgent
from rfp_automation.agents.requirement_extraction_agent import RequirementsExtractionAgent
from rfp_automation.agents.writing_agent import RequirementWritingAgent
from rfp_automation.models.schemas import ResponseSection

_MD_TO_PDF_PATH = Path(__file__).resolve().parents[2] / "scripts" / "md_to_pdf.py"
_MD_TO_PDF_SPEC = importlib.util.spec_from_file_location("md_to_pdf", _MD_TO_PDF_PATH)
assert _MD_TO_PDF_SPEC and _MD_TO_PDF_SPEC.loader
_MD_TO_PDF = importlib.util.module_from_spec(_MD_TO_PDF_SPEC)
_MD_TO_PDF_SPEC.loader.exec_module(_MD_TO_PDF)
_scrub_markdown = _MD_TO_PDF._scrub_markdown


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
        {"requirement_id": "1.01", "source_table_chunk_index": 188},
        {"requirement_id": "4.04", "source_table_chunk_index": 189},
        {"requirement_id": "CM-06", "source_table_chunk_index": 195},
    ]
    sections = [
        ResponseSection(
            section_id="SEC-04",
            title="SD-WAN Architecture & Implementation",
            section_type="requirement_driven",
            requirement_ids=["TR-001", "1.01", "CM-06"],
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

    assert "Technical Implementation" in by_title
    assert by_title["Technical Implementation"].requirement_ids[:2] == ["TR-001", "TR-002"]
    assert by_title["Pricing Schedule Matrix"].requirement_ids == ["1.01", "4.04"]
    assert by_title["Appendix Forms & Declarations"].requirement_ids == ["CM-06"]
    assert len(section_ids) == len(set(section_ids))


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
