from types import SimpleNamespace

from rfp_automation.agents.narrative_agent import NarrativeAssemblyAgent, SectionGroup
from rfp_automation.models.schemas import RFPMetadata
from rfp_automation.services.review_service import ReviewService


def _mock_company_profile(monkeypatch) -> None:
    class MockKnowledgeStore:
        def query_company_profile(self):
            return {"company_name": "Vodafone Business"}

    monkeypatch.setattr(
        "rfp_automation.mcp.vector_store.knowledge_store.KnowledgeStore",
        MockKnowledgeStore,
    )


def test_clean_known_placeholders_strips_internal_refs_but_preserves_tables(monkeypatch):
    class MockKnowledgeStore:
        def query_company_profile(self):
            return {"company_name": "Vodafone Business"}

    monkeypatch.setattr(
        "rfp_automation.mcp.vector_store.knowledge_store.KnowledgeStore",
        MockKnowledgeStore,
    )

    agent = NarrativeAssemblyAgent()
    text = (
        "Our solution provides resilient connectivity (REQ-0001, KPI-01) and proven delivery evidence "
        "(KB-ABCDEF12_block_0004).\n\n"
        "To address, we will improve reliability. Regarding, we confirm compliance. "
        "Our platform is powered by, to provide flexible orchestration.\n\n"
        "[Section: Internal Planning]\n\n"
        "| Req. ID | Vendor Response |\n"
        "|---|---|\n"
        "| TR-001 | Compliant |\n"
    )
    cleaned = agent._clean_known_placeholders(
        text,
        RFPMetadata(client_name="Apex", rfp_title="Example RFP"),
    )

    assert "REQ-0001" not in cleaned
    assert "KPI-01" in cleaned
    assert "KB-ABCDEF12_block_0004" not in cleaned
    assert "[Section:" not in cleaned
    assert "To address," not in cleaned
    assert "Regarding," not in cleaned
    assert "powered by," not in cleaned
    assert "| TR-001 | Compliant |" in cleaned


def test_assemble_document_numbers_headings_and_skips_coverage_appendix(monkeypatch):
    _mock_company_profile(monkeypatch)
    agent = NarrativeAssemblyAgent()
    groups = [
        SectionGroup(
            parent_title="Technical Implementation",
            children=[
                SimpleNamespace(
                    section_id="SEC-01",
                    title="Technical Implementation — Architecture",
                    content="Architecture content.",
                ),
                SimpleNamespace(
                    section_id="SEC-02",
                    title="Technical Implementation — Security",
                    content="Security content.",
                ),
            ],
            is_split=True,
        ),
        SectionGroup(
            parent_title="Migration Plan",
            children=[
                SimpleNamespace(
                    section_id="SEC-03",
                    title="Migration Plan",
                    content="Migration content.",
                )
            ],
            is_split=False,
        ),
    ]

    assembled = agent._assemble_document(
        cover_letter="",
        executive_summary="Summary.",
        groups=groups,
        transitions={},
        coverage_appendix="Coverage appendix should stay internal.",
        rfp_metadata=RFPMetadata(client_name="Apex", rfp_title="Example RFP"),
        architecture_sections=[],
    )

    assert "## 1. Technical Implementation" in assembled
    assert "### 1.1 Architecture" in assembled
    assert "### 1.2 Security" in assembled
    assert "## 2. Migration Plan" in assembled
    assert "Appendix: Requirement Coverage Matrix" not in assembled


def test_assemble_document_numbers_embedded_headings(monkeypatch):
    _mock_company_profile(monkeypatch)
    agent = NarrativeAssemblyAgent()
    groups = [
        SectionGroup(
            parent_title="Pricing & Commercial Terms",
            children=[
                SimpleNamespace(
                    section_id="SEC-01",
                    title="Pricing & Commercial Terms",
                    content=(
                        "## Executive Pricing Summary\n\n"
                        "Summary.\n\n"
                        "## Commercial Terms\n\n"
                        "Terms."
                    ),
                )
            ],
            is_split=False,
        ),
        SectionGroup(
            parent_title="Appendix Forms & Declarations",
            children=[
                SimpleNamespace(
                    section_id="SEC-02",
                    title="Appendix Forms & Declarations — Compliance Forms",
                    content=(
                        "### Compliance Matrix\n\n"
                        "Matrix.\n\n"
                        "### Client Reference Form\n\n"
                        "Reference."
                    ),
                ),
                SimpleNamespace(
                    section_id="SEC-03",
                    title="Appendix Forms & Declarations — Additional Form",
                    content="Other content.",
                ),
            ],
            is_split=True,
        ),
    ]

    assembled = agent._assemble_document(
        cover_letter="",
        executive_summary="Summary.",
        groups=groups,
        transitions={},
        coverage_appendix="",
        rfp_metadata=RFPMetadata(client_name="Apex", rfp_title="Example RFP"),
        architecture_sections=[],
    )

    assert "## Executive Pricing Summary" in assembled
    assert "## Commercial Terms" in assembled
    assert "### Compliance Matrix" in assembled
    assert "### Client Reference Form" in assembled


def test_review_service_keeps_structured_markdown_as_single_block():
    mermaid_text = "Intro\n\n```mermaid\ngraph TD\n\nA-->B\n```"
    table_text = "| A | B |\n|---|---|\n| 1 | 2 |\n\nTrailing note"

    assert ReviewService._split_paragraphs(mermaid_text) == [mermaid_text]
    assert ReviewService._split_paragraphs(table_text) == [table_text]


def test_review_service_sanitizes_internal_refs_but_preserves_tables():
    text = (
        "We meet the requirement (REQ-0001) and track latency against KPI-01 using "
        "evidence from KB-ABC12345_block_0007.\n\n"
        "Including, operational support and To address, compliance improvements.\n\n"
        "[Section: Internal Header\n\n"
        "| Req. ID | Vendor Response |\n"
        "|---|---|\n"
        "| TR-001 | Compliant |\n"
    )

    cleaned = ReviewService._sanitize_response_text(text)

    assert "REQ-0001" not in cleaned
    assert "KPI-01" in cleaned
    assert "KB-ABC12345_block_0007" not in cleaned
    assert "[Section:" not in cleaned
    assert "Including," not in cleaned
    assert "To address," not in cleaned
    assert "| TR-001 | Compliant |" in cleaned
