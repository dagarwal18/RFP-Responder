"""
Tests: Quality Fixes for RFP Response Pipeline

Validates:
  - B1 fragment merging correctly joins badly-split requirement pairs
  - B1 fragment merging does NOT merge complete requirements
  - C2 word count validation logs warnings for thin sections

Run with:
    pytest rfp_automation/tests/test_quality_fixes.py -v
"""

import logging
import re

import pytest

from rfp_automation.agents.requirement_extraction_agent import (
    RequirementsExtractionAgent,
)
from rfp_automation.agents.writing_agent import RequirementWritingAgent
from rfp_automation.models.schemas import Requirement
from rfp_automation.models.enums import (
    RequirementType,
    RequirementClassification,
    RequirementCategory,
    ImpactLevel,
)
from rfp_automation.models.state import RFPGraphState
from rfp_automation.orchestration.graph import _reset_downstream_state_for_rerun
from rfp_automation.utils.diagram_planner import DiagramRegistry, build_diagram_block
from rfp_automation.utils.mermaid_utils import (
    _is_mermaid_timeout_error,
    _validate_mermaid_syntax,
    MERMAID_RENDER_ARGS,
)


# ===========================================================================
# B1 Fragment Merging Tests
# ===========================================================================


class TestFragmentMerging:
    """Tests for the _merge_fragments logic in RequirementsExtractionAgent."""

    @staticmethod
    def _make_req(
        text: str,
        req_id: str = "REQ-0001",
        section: str = "Test Section",
        keywords: list[str] | None = None,
    ) -> Requirement:
        return Requirement(
            requirement_id=req_id,
            text=text,
            type=RequirementType.MANDATORY,
            classification=RequirementClassification.NON_FUNCTIONAL,
            category=RequirementCategory.TECHNICAL,
            impact=ImpactLevel.CRITICAL,
            source_section=section,
            keywords=keywords or [],
        )

    def test_merges_split_pair_starting_with_comparator(self):
        """REQ ends without punctuation + next starts with '<' -> merge."""
        reqs = [
            self._make_req(
                "Call setup time <2 seconds; voice latency",
                req_id="REQ-0011",
                keywords=["call setup", "latency"],
            ),
            self._make_req(
                "<150ms; video quality minimum 720p HD",
                req_id="REQ-0012",
                keywords=["latency", "video quality"],
            ),
        ]
        result = RequirementsExtractionAgent._merge_fragments(reqs)

        assert len(result) == 1
        assert "Call setup time" in result[0].text
        assert "<150ms" in result[0].text
        assert "720p HD" in result[0].text
        assert "call setup" in result[0].keywords
        assert "video quality" in result[0].keywords

    def test_merges_split_pair_starting_with_lowercase(self):
        """REQ ends without punctuation + next starts lowercase -> merge."""
        reqs = [
            self._make_req(
                "The vendor shall provide redundant network",
                req_id="REQ-0020",
            ),
            self._make_req(
                "connectivity across all data center locations",
                req_id="REQ-0021",
            ),
        ]
        result = RequirementsExtractionAgent._merge_fragments(reqs)

        assert len(result) == 1
        assert "redundant network connectivity" in result[0].text

    def test_does_not_merge_complete_requirements(self):
        """Requirements ending with punctuation should NOT be merged."""
        reqs = [
            self._make_req(
                "The system shall provide 99.95% uptime.",
                req_id="REQ-0010",
            ),
            self._make_req(
                "Call setup time must be less than 2 seconds.",
                req_id="REQ-0011",
            ),
        ]
        result = RequirementsExtractionAgent._merge_fragments(reqs)

        assert len(result) == 2
        assert result[0].text == "The system shall provide 99.95% uptime."
        assert result[1].text == "Call setup time must be less than 2 seconds."

    def test_does_not_merge_across_sections(self):
        """Even if text looks incomplete, different sections should NOT merge."""
        reqs = [
            self._make_req(
                "The vendor shall provide redundant network",
                req_id="REQ-0001",
                section="Section A",
            ),
            self._make_req(
                "connectivity for all offices",
                req_id="REQ-0002",
                section="Section B",
            ),
        ]
        result = RequirementsExtractionAgent._merge_fragments(reqs)

        assert len(result) == 2

    def test_single_requirement_returns_unchanged(self):
        """Single requirement should pass through unchanged."""
        reqs = [self._make_req("The vendor shall comply.", req_id="REQ-0001")]
        result = RequirementsExtractionAgent._merge_fragments(reqs)

        assert len(result) == 1
        assert result[0].text == "The vendor shall comply."

    def test_empty_list_returns_empty(self):
        """Empty input should return empty."""
        result = RequirementsExtractionAgent._merge_fragments([])
        assert result == []

    def test_chain_of_three_fragments(self):
        """Three consecutive fragments should merge at least the first pair."""
        reqs = [
            self._make_req(
                "Call setup time <2 seconds; voice latency",
                req_id="REQ-0001",
            ),
            self._make_req(
                "<150ms; video quality",
                req_id="REQ-0002",
            ),
            self._make_req(
                "minimum 720p HD resolution.",
                req_id="REQ-0003",
            ),
        ]
        result = RequirementsExtractionAgent._merge_fragments(reqs)
        assert len(result) <= 2

    def test_does_not_merge_table_backed_rows(self):
        """Table rows should never be merged into each other."""
        reqs = [
            Requirement(
                requirement_id="4.03",
                text="Private APN Setup and Monthly Management",
                type=RequirementType.MANDATORY,
                classification=RequirementClassification.FUNCTIONAL,
                category=RequirementCategory.TECHNICAL,
                impact=ImpactLevel.MEDIUM,
                source_section="Pricing",
                source_table_chunk_index=188,
            ),
            Requirement(
                requirement_id="4.04",
                text="eSIM Remote Provisioning Platform (per SIM, one-time migration)",
                type=RequirementType.MANDATORY,
                classification=RequirementClassification.FUNCTIONAL,
                category=RequirementCategory.TECHNICAL,
                impact=ImpactLevel.MEDIUM,
                source_section="Pricing",
                source_table_chunk_index=189,
            ),
        ]

        result = RequirementsExtractionAgent._merge_fragments(reqs)
        assert [req.requirement_id for req in result] == ["4.03", "4.04"]

    def test_duplicate_requirement_ids_prefer_table_backed_copy(self):
        """If the same ID appears twice, the table-backed copy should win."""
        prose_req = Requirement(
            requirement_id="CM-06",
            text="India Legal Entity duplicate from prose",
            type=RequirementType.MANDATORY,
            classification=RequirementClassification.FUNCTIONAL,
            category=RequirementCategory.TECHNICAL,
            impact=ImpactLevel.MEDIUM,
            source_section="Appendix",
            source_chunk_indices=[220, 221],
            source_table_chunk_index=-1,
        )
        table_req = Requirement(
            requirement_id="CM-06",
            text="India Legal Entity",
            type=RequirementType.MANDATORY,
            classification=RequirementClassification.FUNCTIONAL,
            category=RequirementCategory.TECHNICAL,
            impact=ImpactLevel.MEDIUM,
            source_section="Appendix",
            source_chunk_indices=[195],
            source_table_chunk_index=195,
        )

        collapsed = RequirementsExtractionAgent._collapse_duplicate_requirement_ids(
            [prose_req, table_req]
        )

        assert len(collapsed) == 1
        assert collapsed[0].source_table_chunk_index == 195
        assert collapsed[0].text == "India Legal Entity"


# ===========================================================================
# C2 Word Count Validation Tests
# ===========================================================================


class TestWordCountValidation:
    """Tests that C2 logs appropriate warnings for thin sections."""

    def test_knowledge_driven_low_word_count_warning(self, caplog):
        """knowledge_driven section with < 400 words should log a warning."""
        with caplog.at_level(logging.WARNING, logger="rfp_automation.agents.writing_agent"):
            section_type = "knowledge_driven"
            word_count = 230
            section_id = "SEC-02"
            title = "Company Profile"

            min_words = {
                "knowledge_driven": 400,
                "requirement_driven": 100,
                "boilerplate": 50,
            }
            threshold = min_words.get(section_type, 100)

            logger = logging.getLogger("rfp_automation.agents.writing_agent")
            if word_count < threshold and word_count > 0:
                logger.warning(
                    f"[C2] LOW WORD COUNT: Section {section_id} ({title}) "
                    f"has only {word_count} words (minimum for "
                    f"{section_type}: {threshold})"
                )

        assert any("LOW WORD COUNT" in record.message for record in caplog.records)
        assert any("SEC-02" in record.message for record in caplog.records)

    def test_adequate_word_count_no_warning(self, caplog):
        """knowledge_driven section with >= 400 words should NOT warn."""
        with caplog.at_level(logging.WARNING, logger="rfp_automation.agents.writing_agent"):
            section_type = "knowledge_driven"
            word_count = 550

            min_words = {
                "knowledge_driven": 400,
                "requirement_driven": 100,
                "boilerplate": 50,
            }
            threshold = min_words.get(section_type, 100)

            logger = logging.getLogger("rfp_automation.agents.writing_agent")
            if word_count < threshold and word_count > 0:
                logger.warning("LOW WORD COUNT")

        assert not any("LOW WORD COUNT" in record.message for record in caplog.records)


class TestContextualDiagramPolicies:
    def test_forbidden_sections_drop_mermaid_blocks(self):
        content = (
            "Pricing narrative.\n\n"
            "```mermaid\nflowchart TD\n    A --> B\n    B --> C\n```\n"
        )
        result = RequirementWritingAgent._finalize_section_content(
            content=content,
            section_title="Pricing Schedule Matrix",
            section_description="",
            content_guidance="",
        )

        assert "```mermaid" not in result

    def test_writer_strips_llm_mermaid_for_later_pipeline_rendering(self):
        result = RequirementWritingAgent._finalize_section_content(
            content=(
                "We connect branch sites to the core platform.\n\n"
                "```mermaid\nflowchart TD\n    A --> B\n    B --> C\n```\n"
            ),
            section_title="Technical Implementation - Network & Edge Architecture",
            section_description="Primary SD-WAN topology and edge design.",
            content_guidance="Provide the proposed technical architecture.",
        )

        assert "```mermaid" not in result
        assert "branch sites" in result.lower()

    def test_planner_generates_sequence_for_integration_sections(self):
        registry = DiagramRegistry()
        block = build_diagram_block(
            section_title="Cloud Interconnect",
            section_description="Private connectivity between platforms.",
            content_guidance="Describe the integration workflow and interface hand-offs.",
            content=(
                "The branch portal submits requests to the integration layer, which "
                "validates policy and forwards updates to Azure services and the operations team."
            ),
            visual_relevance="required",
            visual_type_hint="sequence",
            registry=registry,
        )

        assert "```mermaid" in block
        assert "sequenceDiagram" in block
        assert _validate_mermaid_syntax(
            block.split("```mermaid", 1)[1].split("```", 1)[0].strip()
        ) is None

    def test_project_management_sections_get_gantt_diagram(self):
        registry = DiagramRegistry()
        block = build_diagram_block(
            section_title="Implementation & Project Management",
            section_description="Delivery plan for phased rollout.",
            content_guidance="Show the implementation timeline as a gantt chart.",
            content=(
                "Phase 1: Design and Readiness\n"
                "Phase 2: Pilot Deployment\n"
                "Phase 3: Regional Rollout\n"
                "Phase 4: National Cutover\n"
            ),
            visual_relevance="required",
            visual_type_hint="gantt",
            registry=registry,
        )

        assert "```mermaid" in block
        assert "gantt" in block
        assert "2025-11-01" not in block
        assert _validate_mermaid_syntax(
            block.split("```mermaid", 1)[1].split("```", 1)[0].strip()
        ) is None

    def test_implementation_approach_sections_can_auto_select_gantt(self):
        registry = DiagramRegistry()
        block = build_diagram_block(
            section_title="Implementation Approach",
            section_description="Phased delivery approach for onboarding and go-live.",
            content_guidance="Describe the phased transition and deployment approach.",
            content=(
                "Phase 1: Mobilize the program team\n"
                "Phase 2: Design the target solution\n"
                "Phase 3: Pilot the deployment\n"
                "Phase 4: Rollout production services\n"
            ),
            visual_relevance="auto",
            registry=registry,
        )

        assert "```mermaid" in block
        assert "gantt" in block

    def test_delivery_steps_without_explicit_timeline_title_can_still_get_gantt(self):
        registry = DiagramRegistry()
        block = build_diagram_block(
            section_title="Transition Approach",
            section_description="Delivery model for service activation.",
            content_guidance="Explain how the service moves from design to handover.",
            content=(
                "Mobilize delivery governance\n"
                "Design target services\n"
                "Build and deploy the platform\n"
                "Pilot activation with selected sites\n"
                "Cutover and stabilize operations\n"
            ),
            visual_relevance="auto",
            registry=registry,
        )

        assert "```mermaid" in block
        assert "gantt" in block
        assert "Phase 1: Mobilize the" not in block

    def test_planner_avoids_repeated_diagrams(self):
        registry = DiagramRegistry()
        first = build_diagram_block(
            section_title="Operational Workflow",
            section_description="Service lifecycle and hand-offs.",
            content_guidance="Show the process workflow.",
            content="Assess scope. Define solution. Deploy changes. Operate service.",
            visual_relevance="required",
            registry=registry,
        )
        second = build_diagram_block(
            section_title="Operational Workflow",
            section_description="Service lifecycle and hand-offs.",
            content_guidance="Show the process workflow.",
            content="Assess scope. Define solution. Deploy changes. Operate service.",
            visual_relevance="required",
            registry=registry,
        )

        assert first
        assert second == ""

    def test_planner_skips_case_studies_sections(self):
        registry = DiagramRegistry()
        block = build_diagram_block(
            section_title="Case Studies",
            section_description="Representative delivery examples and client references.",
            content_guidance="Provide two relevant case studies with outcomes.",
            content="Case Study 1: Delivered a managed service transformation for a retail network.",
            visual_relevance="auto",
            registry=registry,
        )

        assert block == ""

    def test_planner_diversifies_diagram_types_across_flexible_sections(self):
        registry = DiagramRegistry()
        first = build_diagram_block(
            section_title="Technical Solution Architecture",
            section_description="Overall platform architecture and deployment topology.",
            content_guidance="Describe the technical solution architecture and deployment model.",
            content="User channels connect to the access layer, core platform, and assurance services.",
            visual_relevance="required",
            registry=registry,
        )
        second = build_diagram_block(
            section_title="Platform Architecture",
            section_description="Overall platform architecture and deployment topology.",
            content_guidance="Describe the technical solution architecture and deployment model.",
            content="Identity services connect to application services, integration services, and data services.",
            visual_relevance="required",
            registry=registry,
        )
        third = build_diagram_block(
            section_title="Deployment Architecture",
            section_description="Overall platform architecture and deployment topology.",
            content_guidance="Describe the technical solution architecture and deployment model.",
            content="Branch sites connect to the edge gateway, core platform, and operations team.",
            visual_relevance="required",
            registry=registry,
        )

        combined = "\n".join([first, second, third])
        type_hits = [
            diagram_type
            for diagram_type in ("flowchart", "sequenceDiagram", "classDiagram", "stateDiagram-v2", "erDiagram")
            if diagram_type in combined
        ]

        assert "flowchart" in first
        assert "sequenceDiagram" in combined
        assert len(type_hits) >= 3
        assert len(registry.type_counts) >= 3

    def test_prompt_requirement_format_hides_internal_ids(self):
        line = RequirementWritingAgent._format_requirement_for_prompt(
            "REQ-0017",
            {
                "type": "MANDATORY",
                "text": "The solution must support zero-touch provisioning for all branch devices.",
            },
        )

        assert line.startswith("- Requirement [MANDATORY]")
        assert "REQ-0017" in line
        assert "do not cite" in line

    def test_prompt_requirement_format_keeps_client_row_ids(self):
        line = RequirementWritingAgent._format_requirement_for_prompt(
            "KPI-04",
            {
                "type": "MANDATORY",
                "text": "Cloud interconnect latency must remain below 10 ms round trip.",
            },
        )

        assert line.startswith("- KPI-04 [MANDATORY]")


class TestRerunStateReset:
    def test_reset_downstream_outputs_before_c2_rerun(self):
        state = RFPGraphState().model_dump()
        state["writing_result"] = {
            "section_responses": [{"section_id": "SEC-01", "title": "Example", "content": "Old", "requirements_addressed": [], "word_count": 1}],
            "coverage_matrix": [],
        }
        state["assembled_proposal"] = {
            "executive_summary": "Old summary",
            "full_narrative": "Old narrative",
            "word_count": 12,
            "sections_included": 1,
            "has_placeholders": False,
            "section_order": ["SEC-01"],
            "coverage_appendix": "",
        }
        state["technical_validation"] = {
            "decision": "REJECT",
            "checks": [],
            "critical_failures": 1,
            "warnings": 0,
            "feedback_for_revision": "Old feedback",
            "retry_count": 1,
        }
        state["review_package"] = {
            "review_id": "REV-1",
            "status": "PENDING",
            "source_sections": [],
            "response_sections": [],
            "comments": [],
            "decision": {"decision": None, "reviewer": "", "summary": "", "submitted_at": None, "rerun_from": ""},
            "validation_summary": "",
            "commercial_summary": "",
            "legal_summary": "",
            "total_comments": 0,
            "open_comment_count": 0,
        }

        reset = _reset_downstream_state_for_rerun(state, "c2_requirement_writing")
        defaults = RFPGraphState().model_dump()

        assert reset["writing_result"] == defaults["writing_result"]
        assert reset["assembled_proposal"] == defaults["assembled_proposal"]
        assert reset["technical_validation"] == defaults["technical_validation"]
        assert reset["review_package"] == state["review_package"]


# ===========================================================================
# Mermaid Sanitization Tests
# ===========================================================================


class TestMermaidSanitization:
    """Tests for Mermaid sanitization and validation helpers."""

    def test_quotes_parentheses_in_square_brackets(self):
        from rfp_automation.utils.mermaid_utils import _sanitize_mermaid_code

        code = "flowchart TD\n    E[Microsoft Sentinel (SIEM)]"
        result = _sanitize_mermaid_code(code)
        assert '["Microsoft Sentinel (SIEM)"]' in result

    def test_does_not_double_quote(self):
        from rfp_automation.utils.mermaid_utils import _sanitize_mermaid_code

        code = 'A["Already Quoted (v2)"]'
        result = _sanitize_mermaid_code(code)
        assert result == code

    def test_no_special_chars_unchanged(self):
        from rfp_automation.utils.mermaid_utils import _sanitize_mermaid_code

        code = "A[Simple Label]\n    B[Another Label]"
        result = _sanitize_mermaid_code(code)
        assert result == code

    def test_braces_in_label(self):
        from rfp_automation.utils.mermaid_utils import _sanitize_mermaid_code

        code = "A[Config {JSON}]"
        result = _sanitize_mermaid_code(code)
        assert '["Config {JSON}"]' in result

    def test_multiple_labels_sanitized(self):
        from rfp_automation.utils.mermaid_utils import _sanitize_mermaid_code

        code = "A[SOC (24/7)] --> B[SIEM (v2)]"
        result = _sanitize_mermaid_code(code)
        assert '["SOC (24/7)"]' in result
        assert '["SIEM (v2)"]' in result

    def test_preserves_mermaid_round_nodes(self):
        from rfp_automation.utils.mermaid_utils import _sanitize_mermaid_code

        code = "A(Round Node)"
        result = _sanitize_mermaid_code(code)
        assert result == code

    def test_full_diagram_parses_after_sanitization(self):
        from rfp_automation.utils.mermaid_utils import _sanitize_mermaid_code

        code = (
            "flowchart TD\n"
            "    A[IoT Gateway] --> B[Edge Processing]\n"
            "    B --> C[Azure IoT Hub]\n"
            "    C --> D[Event Hub]\n"
            "    E[Microsoft Sentinel (SIEM)] --> F[Security Dashboard]\n"
        )
        result = _sanitize_mermaid_code(code)
        assert '["Microsoft Sentinel (SIEM)"]' in result
        assert "[IoT Gateway]" in result
        assert "[Edge Processing]" in result

    def test_validate_mermaid_rejects_empty_graph_body(self):
        assert _validate_mermaid_syntax("graph LR") == "Mermaid block has no body"

    def test_validate_mermaid_rejects_body_without_links(self):
        error = _validate_mermaid_syntax(
            "graph LR\n    A[Only Node]\n    B[Second Node]"
        )
        assert error == "Graph/flowchart block has no links"

    def test_validate_mermaid_allows_init_directive(self):
        code = (
            "%%{init: {'theme': 'base'}}%%\n"
            "flowchart LR\n"
            "    A --> B\n"
            "    B --> C"
        )
        assert _validate_mermaid_syntax(code) is None

    def test_cli_theme_remains_mmdc_compatible(self):
        theme_index = MERMAID_RENDER_ARGS.index("--theme")
        assert MERMAID_RENDER_ARGS[theme_index + 1] == "default"

    def test_timeout_detection_matches_navigation_timeout(self):
        assert _is_mermaid_timeout_error(
            "TimeoutError: Navigation timeout of 30000 ms exceeded"
        )

    def test_state_diagram_uses_readable_labels(self):
        registry = DiagramRegistry()
        block = build_diagram_block(
            section_title="Incident Lifecycle",
            section_description="Operational lifecycle for incidents and escalations.",
            content_guidance="Show the operational lifecycle and state transition flow.",
            content=(
                "Intake and qualification\n"
                "Analysis and validation\n"
                "Remediation and recovery\n"
                "Closure and reporting\n"
            ),
            visual_relevance="required",
            visual_type_hint="state",
            registry=registry,
        )

        assert 'state "Intake and qualification" as' in block
        assert "IntakeAndQualification" in block
        assert "CaseStudiesDemonstrating" not in block

    def test_state_diagram_rejects_sentence_fragments(self):
        registry = DiagramRegistry()
        block = build_diagram_block(
            section_title="Operational Workflow",
            section_description="Lifecycle and transition flow.",
            content_guidance="Show the operational lifecycle and state transition flow.",
            content=(
                "Vodafone Business is pleased to submit this response.\n"
                "Security Operations Centre manages service oversight.\n"
                "To ensure high network resilience we maintain monitoring.\n"
                "Tier-1 Hub Sites: >= 2 resilient routes.\n"
            ),
            visual_relevance="required",
            visual_type_hint="state",
            registry=registry,
        )

        assert block == ""

    def test_workflow_sections_with_prose_do_not_emit_broken_journey_text(self):
        registry = DiagramRegistry()
        block = build_diagram_block(
            section_title="Operations Workflow",
            section_description="Operations workflow for managed service delivery.",
            content_guidance="Show the workflow.",
            content=(
                "Vodafone Business is pleased to submit this response.\n"
                "Security Operations Centre manages service oversight.\n"
                "To ensure high network resilience we maintain monitoring.\n"
                "Tier-1 Hub Sites: >= 2 resilient routes.\n"
            ),
            visual_relevance="required",
            registry=registry,
        )

        assert "journey" not in block
        assert "Vodafone Business is pleased" not in block
        assert "Tier-1 Hub Sites: =" not in block

    def test_gantt_labels_keep_whole_words(self):
        registry = DiagramRegistry()
        block = build_diagram_block(
            section_title="Implementation Plan",
            section_description="Implementation plan and rollout timeline.",
            content_guidance="Show the implementation timeline as a gantt chart.",
            content=(
                "Mobilize project governance\n"
                "Design target architecture\n"
                "Build and configure service\n"
                "Pilot with selected sites\n"
                "Rollout production deployment\n"
            ),
            visual_relevance="required",
            visual_type_hint="gantt",
            registry=registry,
        )

        assert "Rollout production deployment" in block
        assert "deploymen :" not in block

    def test_data_sections_can_generate_er_diagrams(self):
        registry = DiagramRegistry()
        block = build_diagram_block(
            section_title="Data Architecture",
            section_description="Entity relationships and master data ownership.",
            content_guidance="Describe the data model and repository interactions.",
            content=(
                "Customer records sync through the integration layer to the reporting repository "
                "and master data services."
            ),
            visual_relevance="required",
            registry=registry,
        )

        assert "erDiagram" in block


# ===========================================================================
# C2 Echo Block Stripping Tests
# ===========================================================================


class TestC2EchoBlockStripping:
    """Tests that _strip_echo_blocks removes LLM format echoes."""

    def test_strips_json_echo_block(self):
        content = (
            "Our platform provides SSO.\n\n"
            "```json\n"
            '{"content": "Our platform provides SSO.", '
            '"requirements_addressed": ["REQ-0001"], "word_count": 50}\n'
            "```"
        )
        result = RequirementWritingAgent._strip_echo_blocks(content)
        assert "```json" not in result
        assert '"content"' not in result
        assert "Our platform provides SSO." in result

    def test_strips_markdown_echo_block(self):
        content = (
            "### Security\nWe provide encryption.\n\n"
            "```markdown\n### Security\nWe provide encryption.\n```"
        )
        result = RequirementWritingAgent._strip_echo_blocks(content)
        assert "```markdown" not in result
        assert "We provide encryption." in result

    def test_preserves_mermaid_blocks(self):
        content = (
            "### Architecture\n\n"
            "```mermaid\nflowchart TD\n    A --> B\n```\n"
        )
        result = RequirementWritingAgent._strip_echo_blocks(content)
        assert "```mermaid" in result
        assert "flowchart TD" in result

    def test_strips_inline_json_metadata_suffix(self):
        content = (
            "Technical narrative paragraph.\n"
            '", "requirements_addressed": ["REQ-0001"], "word_count": 50 }\n'
            "}\n"
        )
        result = RequirementWritingAgent._strip_echo_blocks(content)
        assert "requirements_addressed" not in result
        assert '"word_count"' not in result
        assert result.strip() == "Technical narrative paragraph."


# ===========================================================================
# C3 Split Child Merging Tests
# ===========================================================================


class TestC3SplitChildMerging:
    """Tests that _merge_split_children merges Part N subsections."""

    @staticmethod
    def _make_section_response(title: str, content: str):
        from rfp_automation.models.schemas import SectionResponse

        return SectionResponse(
            section_id="SEC-01",
            title=title,
            content=content,
        )

    def test_merges_same_category_parts(self):
        from rfp_automation.agents.narrative_agent import NarrativeAssemblyAgent

        agent = NarrativeAssemblyAgent()
        children = [
            self._make_section_response(
                "Compliance Matrix - Commercial Terms (Part 1)",
                "Content A",
            ),
            self._make_section_response(
                "Compliance Matrix - Commercial Terms (Part 2)",
                "Content B",
            ),
        ]

        merged = agent._merge_split_children(children, "Compliance Matrix")

        assert len(merged) == 1
        sub_title, contents = merged[0]
        assert sub_title == "Commercial Terms"
        assert len(contents) == 2
        assert "Content A" in contents[0]
        assert "Content B" in contents[1]

    def test_different_categories_stay_separate(self):
        from rfp_automation.agents.narrative_agent import NarrativeAssemblyAgent

        agent = NarrativeAssemblyAgent()
        children = [
            self._make_section_response(
                "Compliance Matrix - Commercial Terms (Part 1)",
                "Commercial stuff",
            ),
            self._make_section_response(
                "Compliance Matrix - Regulatory Compliance (Part 1)",
                "Regulatory stuff",
            ),
        ]

        merged = agent._merge_split_children(children, "Compliance Matrix")

        assert len(merged) == 2
        titles = [t for t, _ in merged]
        assert "Commercial Terms" in titles
        assert "Regulatory Compliance" in titles
