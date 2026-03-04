"""
Tests: Individual agent behaviour.

A1 Intake is now implemented — it should raise FileNotFoundError for
a non-existent file.  All other agents still raise NotImplementedError.

Run with:
    pytest rfp_automation/tests/test_agents.py -v
"""

import json
import pytest
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.enums import PipelineStatus


def _empty_state() -> dict:
    return RFPGraphState(
        uploaded_file_path="/test/rfp.pdf",
        status=PipelineStatus.RECEIVED,
    ).model_dump()


class TestIntakeAgent:
    def test_raises_file_not_found_for_missing_file(self):
        """A1 is implemented — it validates the file exists."""
        from rfp_automation.agents import IntakeAgent

        agent = IntakeAgent()
        with pytest.raises(FileNotFoundError):
            agent.process(_empty_state())

    def test_raises_value_error_for_no_path(self):
        """A1 is implemented — it rejects empty file path."""
        from rfp_automation.agents import IntakeAgent

        agent = IntakeAgent()
        state = RFPGraphState(status=PipelineStatus.RECEIVED).model_dump()
        with pytest.raises(ValueError, match="No file path"):
            agent.process(state)


class TestStructuringAgent:
    """Tests for A2 Structuring Agent."""

    def _structuring_state(self, rfp_id="RFP-TEST1234") -> dict:
        """State with rfp_id set (A1 has already run)."""
        from rfp_automation.models.schemas import RFPMetadata

        return RFPGraphState(
            uploaded_file_path="/test/rfp.pdf",
            status=PipelineStatus.STRUCTURING,
            rfp_metadata=RFPMetadata(rfp_id=rfp_id),
            raw_text="This is test RFP content for structuring.",
        ).model_dump()

    def test_structuring_success(self, monkeypatch):
        """High-confidence LLM response → sections populated, status = GO_NO_GO."""
        from rfp_automation.agents import StructuringAgent

        mock_chunks = [
            {"id": "chunk_0", "score": 0.9, "text": "Project scope...", "chunk_index": 0, "metadata": {}},
            {"id": "chunk_1", "score": 0.9, "text": "Technical specs...", "chunk_index": 1, "metadata": {}},
        ]
        llm_response = json.dumps([
            {
                "section_id": "SEC-01",
                "title": "Project Scope",
                "category": "scope",
                "content_summary": "Describes the project scope.",
                "confidence": 0.92,
                "page_range": "1-3",
            },
            {
                "section_id": "SEC-02",
                "title": "Technical Requirements",
                "category": "technical",
                "content_summary": "Lists technical specs.",
                "confidence": 0.88,
                "page_range": "4-8",
            },
        ])

        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.MCPService",
            lambda: type("MockMCP", (), {
                "query_rfp_all_chunks": lambda self, rfp_id, top_k=100: mock_chunks,
                "fetch_all_rfp_chunks": lambda self, rfp_id: mock_chunks,
            })(),
        )
        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.llm_text_call",
            lambda prompt, deterministic=False: llm_response,
        )

        agent = StructuringAgent()
        result = agent.process(self._structuring_state())

        assert result["structuring_result"]["overall_confidence"] >= 0.6
        assert len(result["structuring_result"]["sections"]) == 2
        assert result["status"] == PipelineStatus.GO_NO_GO.value

    def test_structuring_low_confidence_increments_retry(self, monkeypatch):
        """Low-confidence LLM response → retry_count incremented, status stays STRUCTURING."""
        from rfp_automation.agents import StructuringAgent

        mock_chunks = [
            {"id": "chunk_0", "score": 0.5, "text": "Ambiguous content...", "chunk_index": 0, "metadata": {}},
        ]
        llm_response = json.dumps([
            {
                "section_id": "SEC-01",
                "title": "Unclear Section",
                "category": "scope",
                "content_summary": "Hard to classify.",
                "confidence": 0.3,
                "page_range": "",
            },
        ])

        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.MCPService",
            lambda: type("MockMCP", (), {
                "query_rfp_all_chunks": lambda self, rfp_id, top_k=100: mock_chunks,
                "fetch_all_rfp_chunks": lambda self, rfp_id: mock_chunks,
            })(),
        )
        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.llm_text_call",
            lambda prompt, deterministic=False: llm_response,
        )

        agent = StructuringAgent()
        result = agent.process(self._structuring_state())

        assert result["structuring_result"]["overall_confidence"] < 0.6
        assert result["structuring_result"]["retry_count"] == 1
        assert result["status"] == PipelineStatus.STRUCTURING.value

    def test_structuring_invalid_json_triggers_retry(self, monkeypatch):
        """Malformed LLM response → 0 sections, confidence = 0, retry incremented."""
        from rfp_automation.agents import StructuringAgent

        mock_chunks = [
            {"id": "chunk_0", "score": 0.9, "text": "Some content...", "chunk_index": 0, "metadata": {}},
        ]

        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.MCPService",
            lambda: type("MockMCP", (), {
                "query_rfp_all_chunks": lambda self, rfp_id, top_k=100: mock_chunks,
                "fetch_all_rfp_chunks": lambda self, rfp_id: mock_chunks,
            })(),
        )
        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.llm_text_call",
            lambda prompt, deterministic=False: "This is not valid JSON at all",
        )

        agent = StructuringAgent()
        result = agent.process(self._structuring_state())

        assert result["structuring_result"]["overall_confidence"] == 0.0
        assert result["structuring_result"]["retry_count"] == 1
        assert len(result["structuring_result"]["sections"]) == 0

    def test_structuring_no_rfp_id_raises(self):
        """Missing rfp_id → ValueError."""
        from rfp_automation.agents import StructuringAgent

        agent = StructuringAgent()
        state = RFPGraphState(
            status=PipelineStatus.STRUCTURING,
        ).model_dump()
        with pytest.raises(ValueError, match="No rfp_id"):
            agent.process(state)


class TestGoNoGoAgent:

    @staticmethod
    def _go_no_go_state():
        """State with rfp_id and sections ready for A3."""
        from rfp_automation.models.schemas import RFPMetadata, StructuringResult, RFPSection
        return RFPGraphState(
            status=PipelineStatus.GO_NO_GO,
            rfp_metadata=RFPMetadata(rfp_id="RFP-TEST-001", title="Test RFP"),
            structuring_result=StructuringResult(
                sections=[
                    RFPSection(
                        section_id="SEC-01",
                        title="Security Requirements",
                        category="compliance",
                        content_summary="Must have ISO 27001. Data at rest encryption required.",
                        confidence=0.9,
                    ),
                ],
                overall_confidence=0.9,
            ),
        ).model_dump()

    def test_go_decision_aligned(self, monkeypatch):
        """All requirements align → GO decision, correct counts."""
        from rfp_automation.agents import GoNoGoAgent

        llm_response = json.dumps({
            "strategic_fit_score": 8.0,
            "technical_feasibility_score": 9.0,
            "regulatory_risk_score": 2.0,
            "decision": "GO",
            "justification": "All requirements satisfied",
            "red_flags": [],
            "policy_violations": [],
            "requirement_mappings": [
                {
                    "requirement_id": "RFP-REQ-001",
                    "requirement_text": "Must have ISO 27001",
                    "source_section": "Security Requirements",
                    "mapping_status": "ALIGNS",
                    "matched_policy": "ISO 27001 certified",
                    "matched_policy_id": "POL-001",
                    "confidence": 0.95,
                    "reasoning": "Direct certification match",
                },
                {
                    "requirement_id": "RFP-REQ-002",
                    "requirement_text": "Data at rest encryption",
                    "source_section": "Security Requirements",
                    "mapping_status": "ALIGNS",
                    "matched_policy": "AES-256 encryption at rest",
                    "matched_policy_id": "POL-002",
                    "confidence": 0.90,
                    "reasoning": "Policy covers this",
                },
            ],
        })

        mock_mcp = type("MockMCP", (), {
            "query_rfp_all_chunks": lambda self, rfp_id, top_k=50: [],
            "get_extracted_policies": lambda self: [{"policy_text": "ISO 27001 certified", "policy_id": "POL-001"}],
            "query_knowledge": lambda self, q, top_k=10: [],
        })()

        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.MCPService", lambda: mock_mcp)
        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.llm_text_call", lambda prompt, deterministic=False: llm_response)

        agent = GoNoGoAgent()
        result = agent.process(self._go_no_go_state())

        assert result["go_no_go_result"]["decision"] == "GO"
        assert result["go_no_go_result"]["aligned_count"] == 2
        assert result["go_no_go_result"]["violated_count"] == 0
        assert result["go_no_go_result"]["total_requirements"] == 2
        assert result["status"] == PipelineStatus.EXTRACTING_REQUIREMENTS.value

    def test_no_go_decision_violations(self, monkeypatch):
        """VIOLATES entries → NO_GO decision."""
        from rfp_automation.agents import GoNoGoAgent

        llm_response = json.dumps({
            "strategic_fit_score": 4.0,
            "technical_feasibility_score": 3.0,
            "regulatory_risk_score": 8.0,
            "decision": "NO_GO",
            "justification": "Critical policy violation",
            "red_flags": ["Cannot meet encryption requirement"],
            "policy_violations": ["Data must not leave premises"],
            "requirement_mappings": [
                {
                    "requirement_id": "RFP-REQ-001",
                    "requirement_text": "Cloud hosting required",
                    "source_section": "Infrastructure",
                    "mapping_status": "VIOLATES",
                    "matched_policy": "No cloud hosting allowed",
                    "matched_policy_id": "POL-010",
                    "confidence": 0.99,
                    "reasoning": "Direct contradiction",
                },
            ],
        })

        mock_mcp = type("MockMCP", (), {
            "query_rfp_all_chunks": lambda self, rfp_id, top_k=50: [],
            "get_extracted_policies": lambda self: [],
            "query_knowledge": lambda self, q, top_k=10: [],
        })()

        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.MCPService", lambda: mock_mcp)
        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.llm_text_call", lambda prompt, deterministic=False: llm_response)

        agent = GoNoGoAgent()
        result = agent.process(self._go_no_go_state())

        assert result["go_no_go_result"]["decision"] == "NO_GO"
        assert result["go_no_go_result"]["violated_count"] == 1
        assert result["status"] == PipelineStatus.NO_GO.value

    def test_mixed_mapping_counts(self, monkeypatch):
        """Mixed ALIGNS/RISK/NO_MATCH → verify correct count breakdown."""
        from rfp_automation.agents import GoNoGoAgent

        llm_response = json.dumps({
            "strategic_fit_score": 7.0,
            "technical_feasibility_score": 6.0,
            "regulatory_risk_score": 4.0,
            "decision": "GO",
            "justification": "Mostly aligned",
            "red_flags": [],
            "policy_violations": [],
            "requirement_mappings": [
                {"requirement_id": "R1", "requirement_text": "A", "source_section": "S",
                 "mapping_status": "ALIGNS", "matched_policy": "P1", "matched_policy_id": "POL-001",
                 "confidence": 0.9, "reasoning": "match"},
                {"requirement_id": "R2", "requirement_text": "B", "source_section": "S",
                 "mapping_status": "RISK", "matched_policy": "P2", "matched_policy_id": "POL-002",
                 "confidence": 0.5, "reasoning": "partial"},
                {"requirement_id": "R3", "requirement_text": "C", "source_section": "S",
                 "mapping_status": "NO_MATCH", "matched_policy": "", "matched_policy_id": "",
                 "confidence": 0.0, "reasoning": "none found"},
                {"requirement_id": "R4", "requirement_text": "D", "source_section": "S",
                 "mapping_status": "ALIGNS", "matched_policy": "P3", "matched_policy_id": "POL-003",
                 "confidence": 0.85, "reasoning": "match"},
            ],
        })

        mock_mcp = type("MockMCP", (), {
            "query_rfp_all_chunks": lambda self, rfp_id, top_k=50: [],
            "get_extracted_policies": lambda self: [],
            "query_knowledge": lambda self, q, top_k=10: [],
        })()

        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.MCPService", lambda: mock_mcp)
        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.llm_text_call", lambda prompt, deterministic=False: llm_response)

        agent = GoNoGoAgent()
        result = agent.process(self._go_no_go_state())

        r = result["go_no_go_result"]
        assert r["total_requirements"] == 4
        assert r["aligned_count"] == 2
        assert r["risk_count"] == 1
        assert r["no_match_count"] == 1
        assert r["violated_count"] == 0

    def test_mappings_fully_populated(self, monkeypatch):
        """Verify all RequirementMapping fields are present and typed correctly."""
        from rfp_automation.agents import GoNoGoAgent

        llm_response = json.dumps({
            "strategic_fit_score": 7.0,
            "technical_feasibility_score": 7.0,
            "regulatory_risk_score": 3.0,
            "decision": "GO",
            "justification": "OK",
            "red_flags": [],
            "policy_violations": [],
            "requirement_mappings": [
                {
                    "requirement_id": "RFP-REQ-001",
                    "requirement_text": "Need SOC 2 Type II",
                    "source_section": "Compliance",
                    "mapping_status": "ALIGNS",
                    "matched_policy": "SOC 2 Type II certified",
                    "matched_policy_id": "POL-005",
                    "confidence": 0.98,
                    "reasoning": "Direct cert match",
                },
            ],
        })

        mock_mcp = type("MockMCP", (), {
            "query_rfp_all_chunks": lambda self, rfp_id, top_k=50: [],
            "get_extracted_policies": lambda self: [],
            "query_knowledge": lambda self, q, top_k=10: [],
        })()

        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.MCPService", lambda: mock_mcp)
        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.llm_text_call", lambda prompt, deterministic=False: llm_response)

        agent = GoNoGoAgent()
        result = agent.process(self._go_no_go_state())

        mapping = result["go_no_go_result"]["requirement_mappings"][0]
        assert mapping["requirement_id"] == "RFP-REQ-001"
        assert mapping["requirement_text"] == "Need SOC 2 Type II"
        assert mapping["mapping_status"] == "ALIGNS"
        assert mapping["matched_policy_id"] == "POL-005"
        assert isinstance(mapping["confidence"], float)
        assert mapping["confidence"] > 0.0

    def test_missing_rfp_id_raises(self):
        """No rfp_id in state → ValueError."""
        from rfp_automation.agents import GoNoGoAgent

        agent = GoNoGoAgent()
        state = RFPGraphState(
            status=PipelineStatus.GO_NO_GO,
        ).model_dump()
        with pytest.raises(ValueError, match="No rfp_id"):
            agent.process(state)


# ═══════════════════════════════════════════════════════════
# B1 Requirements Extraction Agent
# ═══════════════════════════════════════════════════════════


class TestRequirementsExtractionAgent:
    """Tests for B1 Requirements Extraction Agent (overhauled)."""

    @staticmethod
    def _mock_chunks():
        """Deterministic chunk data simulating MCP fetch_all_rfp_chunks."""
        return [
            {
                "id": "chunk_0", "chunk_index": 0,
                "section_hint": "Technical Requirements",
                "text": "The system must support SSO via SAML 2.0. "
                        "Data encryption at rest is required.",
                "content_type": "text", "page_start": 1, "page_end": 1,
                "metadata": {},
            },
            {
                "id": "chunk_1", "chunk_index": 1,
                "section_hint": "Performance Requirements",
                "text": "The system should handle 10,000 concurrent users.",
                "content_type": "text", "page_start": 2, "page_end": 2,
                "metadata": {},
            },
        ]

    @staticmethod
    def _extraction_state():
        from rfp_automation.models.schemas import (
            RFPMetadata, StructuringResult, RFPSection,
        )
        return RFPGraphState(
            status=PipelineStatus.EXTRACTING_REQUIREMENTS,
            rfp_metadata=RFPMetadata(rfp_id="RFP-TEST-001"),
            structuring_result=StructuringResult(
                sections=[
                    RFPSection(
                        section_id="SEC-01", title="Technical Requirements",
                        category="technical",
                        content_summary="The system must support SSO via SAML 2.0. "
                                        "Data encryption at rest is required.",
                        confidence=0.9,
                    ),
                    RFPSection(
                        section_id="SEC-02", title="Performance Requirements",
                        category="technical",
                        content_summary="The system should handle 10,000 concurrent users.",
                        confidence=0.85,
                    ),
                ],
                overall_confidence=0.88,
            ),
        ).model_dump()

    def test_extraction_success(self, monkeypatch):
        """Valid LLM response -> requirements populated, correct status."""
        from rfp_automation.agents import RequirementsExtractionAgent

        llm_responses = [
            json.dumps([
                {"requirement_id": "REQ-0001", "text": "The system must support SSO via SAML 2.0",
                 "type": "MANDATORY", "classification": "FUNCTIONAL",
                 "category": "TECHNICAL", "impact": "HIGH", "keywords": ["SSO", "SAML"]},
                {"requirement_id": "REQ-0002", "text": "Data encryption at rest is required",
                 "type": "MANDATORY", "classification": "NON_FUNCTIONAL",
                 "category": "SECURITY", "impact": "CRITICAL", "keywords": ["encryption"]},
            ]),
            json.dumps([
                {"requirement_id": "REQ-0003", "text": "The system should handle 10,000 concurrent users",
                 "type": "OPTIONAL", "classification": "NON_FUNCTIONAL",
                 "category": "TECHNICAL", "impact": "HIGH", "keywords": ["scalability"]},
            ]),
        ]
        call_count = {"n": 0}

        def mock_llm(prompt, max_retries=1):
            idx = call_count["n"]
            call_count["n"] += 1
            return llm_responses[idx] if idx < len(llm_responses) else "[]"

        mock_chunks = TestRequirementsExtractionAgent._mock_chunks()
        mock_mcp = type("MockMCP", (), {
            "fetch_all_rfp_chunks": lambda self, rfp_id: mock_chunks,
        })()
        monkeypatch.setattr("rfp_automation.agents.requirement_extraction_agent.MCPService", lambda: mock_mcp)
        monkeypatch.setattr("rfp_automation.agents.requirement_extraction_agent.llm_deterministic_call", mock_llm)

        agent = RequirementsExtractionAgent()
        result = agent.process(self._extraction_state())

        assert len(result["requirements"]) >= 2
        assert result["requirements"][0]["requirement_id"] == "REQ-0001"
        assert result["requirements"][1]["requirement_id"] == "REQ-0002"
        assert result["status"] == PipelineStatus.VALIDATING_REQUIREMENTS.value

    def test_extraction_no_chunks(self, monkeypatch):
        """Empty chunk retrieval -> 0 requirements, no error."""
        from rfp_automation.agents import RequirementsExtractionAgent

        mock_mcp = type("MockMCP", (), {
            "fetch_all_rfp_chunks": lambda self, rfp_id: [],
        })()
        monkeypatch.setattr("rfp_automation.agents.requirement_extraction_agent.MCPService", lambda: mock_mcp)

        agent = RequirementsExtractionAgent()
        result = agent.process(self._extraction_state())
        assert result["requirements"] == []
        assert result["status"] == PipelineStatus.VALIDATING_REQUIREMENTS.value

    def test_extraction_invalid_json(self, monkeypatch):
        """Malformed LLM response -> 0 requirements, no crash."""
        from rfp_automation.agents import RequirementsExtractionAgent

        mock_chunks = TestRequirementsExtractionAgent._mock_chunks()
        mock_mcp = type("MockMCP", (), {
            "fetch_all_rfp_chunks": lambda self, rfp_id: mock_chunks,
        })()
        monkeypatch.setattr("rfp_automation.agents.requirement_extraction_agent.MCPService", lambda: mock_mcp)
        monkeypatch.setattr("rfp_automation.agents.requirement_extraction_agent.llm_deterministic_call",
                            lambda prompt, max_retries=1: "This is not JSON at all!!!")

        agent = RequirementsExtractionAgent()
        result = agent.process(self._extraction_state())
        assert result["requirements"] == []

    def test_extraction_classification_types(self, monkeypatch):
        """Verify FUNCTIONAL and NON_FUNCTIONAL are correctly assigned."""
        from rfp_automation.agents import RequirementsExtractionAgent

        llm_response = json.dumps([
            {"requirement_id": "REQ-0001", "text": "System must provide user dashboard",
             "type": "MANDATORY", "classification": "FUNCTIONAL",
             "category": "FUNCTIONAL", "impact": "HIGH", "keywords": ["dashboard"]},
            {"requirement_id": "REQ-0002", "text": "System must respond within 200ms",
             "type": "MANDATORY", "classification": "NON_FUNCTIONAL",
             "category": "TECHNICAL", "impact": "HIGH", "keywords": ["performance"]},
        ])

        mock_chunks = [{
            "id": "chunk_0", "chunk_index": 0,
            "section_hint": "Mixed",
            "text": "System must provide user dashboard. System must respond within 200ms.",
            "content_type": "text", "page_start": 1, "page_end": 1,
            "metadata": {},
        }]
        mock_mcp = type("MockMCP", (), {
            "fetch_all_rfp_chunks": lambda self, rfp_id: mock_chunks,
        })()
        monkeypatch.setattr("rfp_automation.agents.requirement_extraction_agent.MCPService", lambda: mock_mcp)
        monkeypatch.setattr("rfp_automation.agents.requirement_extraction_agent.llm_deterministic_call",
                            lambda prompt, max_retries=1: llm_response)

        agent = RequirementsExtractionAgent()
        result = agent.process(self._extraction_state())
        assert len(result["requirements"]) == 2
        assert result["requirements"][0]["classification"] == "FUNCTIONAL"
        assert result["requirements"][1]["classification"] == "NON_FUNCTIONAL"

    def test_extraction_no_rfp_id_raises(self):
        """Missing rfp_id -> ValueError."""
        from rfp_automation.agents import RequirementsExtractionAgent

        agent = RequirementsExtractionAgent()
        state = RFPGraphState(status=PipelineStatus.EXTRACTING_REQUIREMENTS).model_dump()
        with pytest.raises(ValueError, match="No rfp_id"):
            agent.process(state)


# ═══════════════════════════════════════════════════════════
# B2 Requirements Validation Agent
# ═══════════════════════════════════════════════════════════


class TestRequirementsValidationAgent:
    """Tests for B2 Requirements Validation Agent."""

    @staticmethod
    def _validation_state(requirements=None):
        from rfp_automation.models.schemas import RFPMetadata, Requirement
        from rfp_automation.models.enums import (
            RequirementType, RequirementClassification,
            RequirementCategory, ImpactLevel,
        )
        if requirements is None:
            requirements = [
                Requirement(
                    requirement_id="REQ-001", text="System must support SSO via SAML 2.0",
                    type=RequirementType.MANDATORY,
                    classification=RequirementClassification.FUNCTIONAL,
                    category=RequirementCategory.TECHNICAL, impact=ImpactLevel.HIGH,
                    source_section="Technical Requirements",
                ),
                Requirement(
                    requirement_id="REQ-002", text="Data encryption at rest is required",
                    type=RequirementType.MANDATORY,
                    classification=RequirementClassification.NON_FUNCTIONAL,
                    category=RequirementCategory.SECURITY, impact=ImpactLevel.CRITICAL,
                    source_section="Security Requirements",
                ),
            ]
        return RFPGraphState(
            status=PipelineStatus.VALIDATING_REQUIREMENTS,
            rfp_metadata=RFPMetadata(rfp_id="RFP-TEST-001"),
            requirements=requirements,
        ).model_dump()

    def test_validation_high_confidence(self, monkeypatch):
        """Confidence >= 0.7 → validated requirements populated, no refinement."""
        from rfp_automation.agents import RequirementsValidationAgent

        monkeypatch.setattr("rfp_automation.agents.requirement_validation_agent.llm_text_call",
                            lambda prompt, deterministic=False: json.dumps({"confidence_score": 0.92, "issues": [], "requirement_notes": {}}))

        agent = RequirementsValidationAgent()
        result = agent.process(self._validation_state())

        vr = result["requirements_validation"]
        assert vr["confidence_score"] >= 0.7
        assert vr["total_requirements"] == 2
        assert vr["mandatory_count"] == 2
        assert vr["functional_count"] == 1
        assert vr["non_functional_count"] == 1
        assert result["status"] == PipelineStatus.ARCHITECTURE_PLANNING.value

    def test_validation_low_confidence_triggers_refinement(self, monkeypatch):
        """Confidence < 0.7 → agent calls LLM a second time for refinement."""
        from rfp_automation.agents import RequirementsValidationAgent

        call_count = {"n": 0}

        def mock_llm(prompt, deterministic=False):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return json.dumps({
                    "confidence_score": 0.45,
                    "issues": [{"issue_type": "ambiguity", "requirement_ids": ["REQ-001"],
                                "description": "Vague requirement", "severity": "warning"}],
                    "requirement_notes": {},
                })
            else:
                return json.dumps({"confidence_score": 0.78, "issues": [], "requirement_notes": {}})

        monkeypatch.setattr("rfp_automation.agents.requirement_validation_agent.llm_text_call", mock_llm)

        agent = RequirementsValidationAgent()
        result = agent.process(self._validation_state())

        assert call_count["n"] == 2
        assert result["requirements_validation"]["confidence_score"] >= 0.7
        assert result["status"] == PipelineStatus.ARCHITECTURE_PLANNING.value

    def test_validation_detects_issues(self, monkeypatch):
        """LLM flags duplicates and contradictions → correct issue counts."""
        from rfp_automation.agents import RequirementsValidationAgent

        monkeypatch.setattr("rfp_automation.agents.requirement_validation_agent.llm_text_call",
                            lambda prompt, deterministic=False: json.dumps({
                                "confidence_score": 0.75,
                                "issues": [
                                    {"issue_type": "duplicate", "requirement_ids": ["REQ-001", "REQ-002"],
                                     "description": "Both describe SSO", "severity": "warning"},
                                    {"issue_type": "contradiction", "requirement_ids": ["REQ-001", "REQ-002"],
                                     "description": "Conflicting hosting", "severity": "warning"},
                                    {"issue_type": "ambiguity", "requirement_ids": ["REQ-002"],
                                     "description": "Vague target", "severity": "warning"},
                                ],
                                "requirement_notes": {},
                            }))

        agent = RequirementsValidationAgent()
        result = agent.process(self._validation_state())

        vr = result["requirements_validation"]
        assert vr["duplicate_count"] == 1
        assert vr["contradiction_count"] == 1
        assert vr["ambiguity_count"] == 1
        assert len(vr["issues"]) == 3

    def test_validation_empty_requirements(self):
        """No requirements → passes through with empty result."""
        from rfp_automation.agents import RequirementsValidationAgent

        agent = RequirementsValidationAgent()
        result = agent.process(self._validation_state(requirements=[]))

        vr = result["requirements_validation"]
        assert vr["total_requirements"] == 0
        assert vr["confidence_score"] == 0.0
        assert result["status"] == PipelineStatus.ARCHITECTURE_PLANNING.value

    def test_refinement_guardrail_rejects_new_issues(self, monkeypatch):
        """If refinement returns MORE issues than original, discard it."""
        from rfp_automation.agents import RequirementsValidationAgent

        call_count = {"n": 0}

        def mock_llm(prompt, deterministic=False):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # Initial validation: 1 issue, low confidence
                return json.dumps({
                    "confidence_score": 0.45,
                    "issues": [{"issue_type": "ambiguity", "requirement_ids": ["REQ-001"],
                                "description": "Vague requirement", "severity": "warning"}],
                    "requirement_notes": {},
                })
            else:
                # Refinement: LLM tries to inject 3 issues (was 1)
                return json.dumps({
                    "confidence_score": 0.80,
                    "issues": [
                        {"issue_type": "ambiguity", "requirement_ids": ["REQ-001"],
                         "description": "Vague requirement", "severity": "warning"},
                        {"issue_type": "duplicate", "requirement_ids": ["REQ-001", "REQ-002"],
                         "description": "Hallucinated duplicate", "severity": "error"},
                        {"issue_type": "contradiction", "requirement_ids": ["REQ-002"],
                         "description": "Hallucinated contradiction", "severity": "error"},
                    ],
                    "requirement_notes": {},
                })

        monkeypatch.setattr("rfp_automation.agents.requirement_validation_agent.llm_text_call", mock_llm)

        agent = RequirementsValidationAgent()
        result = agent.process(self._validation_state())

        # Guardrail should have kept the original 1 issue & low confidence
        vr = result["requirements_validation"]
        assert len(vr["issues"]) == 1
        assert vr["confidence_score"] == 0.45

    def test_refinement_prompt_includes_rfp_context(self, monkeypatch):
        """When raw_text is available, refinement prompt should contain RFP excerpts."""
        from rfp_automation.agents import RequirementsValidationAgent
        from rfp_automation.models.schemas import RFPMetadata

        captured_prompts = []

        def mock_llm(prompt, deterministic=False):
            captured_prompts.append(prompt)
            if len(captured_prompts) == 1:
                return json.dumps({
                    "confidence_score": 0.45,
                    "issues": [{"issue_type": "ambiguity", "requirement_ids": ["REQ-001"],
                                "description": "Vague requirement", "severity": "warning"}],
                    "requirement_notes": {},
                })
            else:
                return json.dumps({"confidence_score": 0.78, "issues": [], "requirement_notes": {}})

        monkeypatch.setattr("rfp_automation.agents.requirement_validation_agent.llm_text_call", mock_llm)

        # Create state with raw_text
        state = self._validation_state()
        state["raw_text"] = "The vendor must provide 24/7 support. SAML 2.0 SSO is required."

        agent = RequirementsValidationAgent()
        agent.process(state)

        # Second prompt (refinement) should contain RFP text
        assert len(captured_prompts) == 2
        assert "24/7 support" in captured_prompts[1]
        assert "SAML 2.0" in captured_prompts[1]


# ═══════════════════════════════════════════════════════════
# B1 Section-Based Grouping
# ═══════════════════════════════════════════════════════════


class TestSectionGrouping:
    """Tests for B1 _group_by_section."""

    def test_section_grouping_basic(self):
        """Chunks with different section_hints → grouped by hint."""
        from rfp_automation.agents.requirement_extraction_agent import RequirementsExtractionAgent

        chunks = [
            {"id": "c0", "chunk_index": 0, "section_hint": "Section A", "text": "text 0"},
            {"id": "c1", "chunk_index": 1, "section_hint": "Section A", "text": "text 1"},
            {"id": "c2", "chunk_index": 2, "section_hint": "Section B", "text": "text 2"},
        ]

        groups = RequirementsExtractionAgent._group_by_section(chunks)

        assert len(groups) == 2
        assert "Section A" in groups
        assert "Section B" in groups
        assert len(groups["Section A"]) == 2
        assert len(groups["Section B"]) == 1

    def test_section_grouping_no_hint(self):
        """Chunks without section_hint get grouped into 'Untitled Section'."""
        from rfp_automation.agents.requirement_extraction_agent import RequirementsExtractionAgent

        chunks = [
            {"id": "c0", "chunk_index": 0, "text": "text 0"},
            {"id": "c1", "chunk_index": 1, "text": "text 1"},
        ]

        groups = RequirementsExtractionAgent._group_by_section(chunks)

        assert len(groups) == 1
        assert "Untitled Section" in groups
        assert len(groups["Untitled Section"]) == 2


# ═══════════════════════════════════════════════════════════
# C1 Architecture Planning Agent
# ═══════════════════════════════════════════════════════════


class TestArchitecturePlanningAgent:
    """Tests for C1 Architecture Planning Agent (redesigned - full blueprint)."""

    @staticmethod
    def _architecture_state(requirements=None):
        from rfp_automation.models.schemas import (
            RFPMetadata, Requirement, RequirementsValidationResult,
            StructuringResult, RFPSection,
        )
        from rfp_automation.models.enums import (
            RequirementType, RequirementClassification,
            RequirementCategory, ImpactLevel,
        )
        if requirements is None:
            requirements = [
                Requirement(
                    requirement_id="REQ-001", text="System must support SSO via SAML 2.0",
                    type=RequirementType.MANDATORY,
                    classification=RequirementClassification.FUNCTIONAL,
                    category=RequirementCategory.TECHNICAL, impact=ImpactLevel.HIGH,
                    source_section="Technical Requirements",
                ),
                Requirement(
                    requirement_id="REQ-002", text="Data encryption at rest is required",
                    type=RequirementType.MANDATORY,
                    classification=RequirementClassification.NON_FUNCTIONAL,
                    category=RequirementCategory.SECURITY, impact=ImpactLevel.CRITICAL,
                    source_section="Security Requirements",
                ),
                Requirement(
                    requirement_id="REQ-003", text="System should support 10k users",
                    type=RequirementType.OPTIONAL,
                    classification=RequirementClassification.NON_FUNCTIONAL,
                    category=RequirementCategory.TECHNICAL, impact=ImpactLevel.MEDIUM,
                    source_section="Performance Requirements",
                ),
            ]
        return RFPGraphState(
            status=PipelineStatus.ARCHITECTURE_PLANNING,
            rfp_metadata=RFPMetadata(rfp_id="RFP-TEST-001"),
            requirements=requirements,
            requirements_validation=RequirementsValidationResult(
                validated_requirements=requirements,
                total_requirements=len(requirements),
            ),
            structuring_result=StructuringResult(
                sections=[
                    RFPSection(
                        section_id="SEC-01", title="Technical Requirements",
                        category="technical",
                        content_summary="Authentication, encryption, and performance specs.",
                        confidence=0.9,
                    ),
                    RFPSection(
                        section_id="SEC-02", title="Submission Instructions",
                        category="submission",
                        content_summary="Proposal format, deadline, required forms.",
                        confidence=0.85,
                    ),
                ],
                overall_confidence=0.88,
            ),
        ).model_dump()

    @staticmethod
    def _mock_mcp():
        return type("MockMCP", (), {
            "query_knowledge": lambda self, q, top_k=5: [
                {"text": "ISO 27001 certified operations", "metadata": {}},
            ],
            "query_rfp": lambda self, q, rfp_id="", top_k=5: [
                {"text": "Proposals must include cover letter and compliance matrix.", "metadata": {}},
            ],
        })()

    def test_architecture_success(self, monkeypatch):
        """Valid LLM response with section_types → full blueprint, correct status."""
        from rfp_automation.agents import ArchitecturePlanningAgent

        llm_response = json.dumps({
            "rfp_response_instructions": "Follow format from Section 3",
            "sections": [
                {
                    "section_id": "SEC-01",
                    "title": "Cover Letter",
                    "section_type": "boilerplate",
                    "description": "Formal submission letter",
                    "content_guidance": "Confirm 120-day validity",
                    "requirement_ids": [],
                    "mapped_capabilities": [],
                    "priority": 1,
                    "source_rfp_section": "Submission Instructions",
                },
                {
                    "section_id": "SEC-02",
                    "title": "Security & Compliance",
                    "section_type": "requirement_driven",
                    "description": "Address all security requirements",
                    "content_guidance": "",
                    "requirement_ids": ["REQ-001", "REQ-002"],
                    "mapped_capabilities": ["ISO 27001", "AES-256"],
                    "priority": 2,
                    "source_rfp_section": "Technical Requirements",
                },
            ],
        })

        monkeypatch.setattr("rfp_automation.agents.architecture_agent.MCPService",
                            lambda: self._mock_mcp())
        monkeypatch.setattr("rfp_automation.agents.architecture_agent.llm_text_call",
                            lambda prompt, deterministic=False: llm_response)

        agent = ArchitecturePlanningAgent()
        result = agent.process(self._architecture_state())

        plan = result["architecture_plan"]
        assert plan["total_sections"] == 2
        assert plan["sections"][0]["section_type"] == "boilerplate"
        assert plan["sections"][1]["section_type"] == "requirement_driven"
        assert plan["sections"][0]["description"] == "Formal submission letter"
        assert "REQ-001" in plan["sections"][1]["requirement_ids"]
        assert plan["rfp_response_instructions"] == "Follow format from Section 3"
        assert result["status"] == PipelineStatus.WRITING_RESPONSES.value

    def test_architecture_coverage_gaps(self, monkeypatch):
        """Missing mandatory requirement → appears in coverage_gaps."""
        from rfp_automation.agents import ArchitecturePlanningAgent

        # LLM only assigns REQ-001, missing REQ-002 (mandatory)
        llm_response = json.dumps({
            "rfp_response_instructions": "",
            "sections": [
                {
                    "section_id": "SEC-01",
                    "title": "Authentication",
                    "section_type": "requirement_driven",
                    "description": "SSO implementation",
                    "requirement_ids": ["REQ-001"],
                    "mapped_capabilities": ["SSO support"],
                    "priority": 1,
                },
                {
                    "section_id": "SEC-02",
                    "title": "Company Profile",
                    "section_type": "knowledge_driven",
                    "description": "Company overview",
                    "requirement_ids": [],
                    "mapped_capabilities": ["10 years experience"],
                    "priority": 2,
                },
            ],
        })

        monkeypatch.setattr("rfp_automation.agents.architecture_agent.MCPService",
                            lambda: self._mock_mcp())
        monkeypatch.setattr("rfp_automation.agents.architecture_agent.llm_text_call",
                            lambda prompt, deterministic=False: llm_response)

        agent = ArchitecturePlanningAgent()
        result = agent.process(self._architecture_state())

        plan = result["architecture_plan"]
        assert "REQ-002" in plan["coverage_gaps"]
        # REQ-003 is OPTIONAL, should NOT appear in coverage_gaps
        assert "REQ-003" not in plan["coverage_gaps"]

    def test_architecture_all_section_types(self, monkeypatch):
        """Verify all 5 section types are parsed correctly."""
        from rfp_automation.agents import ArchitecturePlanningAgent

        llm_response = json.dumps({
            "rfp_response_instructions": "",
            "sections": [
                {"section_id": "SEC-01", "title": "Cover Letter",
                 "section_type": "boilerplate", "description": "Cover", "priority": 1,
                 "requirement_ids": [], "mapped_capabilities": []},
                {"section_id": "SEC-02", "title": "Company Profile",
                 "section_type": "knowledge_driven", "description": "Profile", "priority": 2,
                 "requirement_ids": [], "mapped_capabilities": ["10 years exp"]},
                {"section_id": "SEC-03", "title": "Technical Solution",
                 "section_type": "requirement_driven", "description": "Solution", "priority": 3,
                 "requirement_ids": ["REQ-001", "REQ-002"], "mapped_capabilities": ["SSO", "AES"]},
                {"section_id": "SEC-04", "title": "Pricing",
                 "section_type": "commercial", "description": "Costs", "priority": 4,
                 "requirement_ids": [], "mapped_capabilities": []},
                {"section_id": "SEC-05", "title": "Legal Terms",
                 "section_type": "legal", "description": "Terms", "priority": 5,
                 "requirement_ids": [], "mapped_capabilities": []},
            ],
        })

        monkeypatch.setattr("rfp_automation.agents.architecture_agent.MCPService",
                            lambda: self._mock_mcp())
        monkeypatch.setattr("rfp_automation.agents.architecture_agent.llm_text_call",
                            lambda prompt, deterministic=False: llm_response)

        agent = ArchitecturePlanningAgent()
        result = agent.process(self._architecture_state())

        plan = result["architecture_plan"]
        types = [s["section_type"] for s in plan["sections"]]
        assert "boilerplate" in types
        assert "knowledge_driven" in types
        assert "requirement_driven" in types
        assert "commercial" in types
        assert "legal" in types
        assert plan["total_sections"] == 5

    def test_architecture_invalid_json(self, monkeypatch):
        """Malformed LLM response → empty sections, 0 total_sections."""
        from rfp_automation.agents import ArchitecturePlanningAgent

        monkeypatch.setattr("rfp_automation.agents.architecture_agent.MCPService",
                            lambda: self._mock_mcp())
        monkeypatch.setattr("rfp_automation.agents.architecture_agent.llm_text_call",
                            lambda prompt, deterministic=False: "This is not valid JSON at all!!!")

        agent = ArchitecturePlanningAgent()
        result = agent.process(self._architecture_state())

        plan = result["architecture_plan"]
        assert plan["total_sections"] == 0
        assert len(plan["sections"]) == 0
        assert result["status"] == PipelineStatus.WRITING_RESPONSES.value

    def test_architecture_no_rfp_id_raises(self):
        """Missing rfp_id → ValueError."""
        from rfp_automation.agents import ArchitecturePlanningAgent

        agent = ArchitecturePlanningAgent()
        state = RFPGraphState(
            status=PipelineStatus.ARCHITECTURE_PLANNING,
        ).model_dump()
        with pytest.raises(ValueError, match="No rfp_id"):
            agent.process(state)

    def test_architecture_empty_requirements(self, monkeypatch):
        """No requirements → still produces RFP-driven sections (boilerplate, etc)."""
        from rfp_automation.agents import ArchitecturePlanningAgent

        llm_response = json.dumps({
            "rfp_response_instructions": "",
            "sections": [
                {"section_id": "SEC-01", "title": "Cover Letter",
                 "section_type": "boilerplate", "description": "Formal letter", "priority": 1,
                 "requirement_ids": [], "mapped_capabilities": []},
            ],
        })

        monkeypatch.setattr("rfp_automation.agents.architecture_agent.MCPService",
                            lambda: self._mock_mcp())
        monkeypatch.setattr("rfp_automation.agents.architecture_agent.llm_text_call",
                            lambda prompt, deterministic=False: llm_response)

        agent = ArchitecturePlanningAgent()
        result = agent.process(self._architecture_state(requirements=[]))

        plan = result["architecture_plan"]
        # Even with 0 requirements, RFP-driven sections should appear
        assert plan["total_sections"] >= 1
        assert plan["coverage_gaps"] == []
        assert result["status"] == PipelineStatus.WRITING_RESPONSES.value

    def test_architecture_legacy_array_format(self, monkeypatch):
        """Backward compat: LLM returns bare JSON array → still parses."""
        from rfp_automation.agents import ArchitecturePlanningAgent

        llm_response = json.dumps([
            {
                "section_id": "SEC-01",
                "title": "Technical Solution",
                "section_type": "requirement_driven",
                "description": "Technical details",
                "requirement_ids": ["REQ-001", "REQ-002"],
                "mapped_capabilities": ["SSO"],
                "priority": 1,
            },
        ])

        monkeypatch.setattr("rfp_automation.agents.architecture_agent.MCPService",
                            lambda: self._mock_mcp())
        monkeypatch.setattr("rfp_automation.agents.architecture_agent.llm_text_call",
                            lambda prompt, deterministic=False: llm_response)

        agent = ArchitecturePlanningAgent()
        result = agent.process(self._architecture_state())

        plan = result["architecture_plan"]
        assert plan["total_sections"] == 1
        assert plan["rfp_response_instructions"] == ""


# ═══════════════════════════════════════════════════════════
# C2 Requirement Writing Agent
# ═══════════════════════════════════════════════════════════


class TestWritingAgent:
    """Tests for C2 Requirement Writing Agent."""

    @staticmethod
    def _writing_state(sections=None, requirements=None):
        from rfp_automation.models.schemas import (
            RFPMetadata, Requirement, RequirementsValidationResult,
            ArchitecturePlan, ResponseSection,
        )
        from rfp_automation.models.enums import (
            RequirementType, RequirementClassification,
            RequirementCategory, ImpactLevel,
        )
        if requirements is None:
            requirements = [
                Requirement(
                    requirement_id="REQ-001", text="System must support SSO via SAML 2.0",
                    type=RequirementType.MANDATORY,
                    classification=RequirementClassification.FUNCTIONAL,
                    category=RequirementCategory.TECHNICAL, impact=ImpactLevel.HIGH,
                    source_section="Technical Requirements",
                    keywords=["SSO", "SAML"],
                ),
                Requirement(
                    requirement_id="REQ-002", text="Data encryption at rest is required",
                    type=RequirementType.MANDATORY,
                    classification=RequirementClassification.NON_FUNCTIONAL,
                    category=RequirementCategory.SECURITY, impact=ImpactLevel.CRITICAL,
                    source_section="Security Requirements",
                    keywords=["encryption", "security"],
                ),
            ]
        if sections is None:
            sections = [
                ResponseSection(
                    section_id="SEC-01", title="Technical Solution",
                    section_type="requirement_driven",
                    description="Address all technical requirements",
                    content_guidance="Include architecture diagram",
                    requirement_ids=["REQ-001", "REQ-002"],
                    mapped_capabilities=["SSO support", "AES-256 encryption"],
                    priority=1,
                ),
                ResponseSection(
                    section_id="SEC-02", title="Company Profile",
                    section_type="knowledge_driven",
                    description="Company overview and experience",
                    requirement_ids=[],
                    mapped_capabilities=["10 years experience"],
                    priority=4,
                ),
            ]
        return RFPGraphState(
            status=PipelineStatus.WRITING_RESPONSES,
            rfp_metadata=RFPMetadata(rfp_id="RFP-TEST-001"),
            requirements=requirements,
            requirements_validation=RequirementsValidationResult(
                validated_requirements=requirements,
                total_requirements=len(requirements),
            ),
            architecture_plan=ArchitecturePlan(
                sections=sections,
                total_sections=len(sections),
                rfp_response_instructions="Follow format from Section 3",
            ),
        ).model_dump()

    @staticmethod
    def _mock_mcp():
        return type("MockMCP", (), {
            "query_knowledge": lambda self, q, top_k=3: [
                {"text": "ISO 27001 certified operations", "metadata": {}},
            ],
        })()

    def test_writing_success(self, monkeypatch):
        """Valid LLM response → section responses populated, status = ASSEMBLING_NARRATIVE."""
        from rfp_automation.agents import RequirementWritingAgent

        responses = {
            "Technical Solution": json.dumps({
                "content": "Our platform provides SSO via SAML 2.0 and AES-256 encryption.",
                "requirements_addressed": ["REQ-001", "REQ-002"],
                "word_count": 45,
            }),
            "Company Profile": json.dumps({
                "content": "We have 10 years of enterprise experience.",
                "requirements_addressed": [],
                "word_count": 8,
            }),
        }

        def mock_llm(prompt, deterministic=False):
            for title, resp in responses.items():
                if title in prompt:
                    return resp
            return json.dumps({"content": "Default.", "requirements_addressed": [], "word_count": 1})

        monkeypatch.setattr("rfp_automation.agents.writing_agent.MCPService",
                            lambda: self._mock_mcp())
        monkeypatch.setattr("rfp_automation.agents.writing_agent.llm_text_call", mock_llm)

        agent = RequirementWritingAgent()
        result = agent.process(self._writing_state())

        wr = result["writing_result"]
        assert len(wr["section_responses"]) == 2
        assert wr["section_responses"][0]["content"] != ""
        assert "REQ-001" in wr["section_responses"][0]["requirements_addressed"]
        assert result["status"] == PipelineStatus.ASSEMBLING_NARRATIVE.value

    def test_writing_coverage_matrix(self, monkeypatch):
        """Addressed requirements → 'full'; unaddressed → 'missing'."""
        from rfp_automation.agents import RequirementWritingAgent

        # LLM only confirms REQ-001, not REQ-002
        def mock_llm(prompt, deterministic=False):
            return json.dumps({
                "content": "SSO via SAML 2.0.",
                "requirements_addressed": ["REQ-001"],
                "word_count": 5,
            })

        monkeypatch.setattr("rfp_automation.agents.writing_agent.MCPService",
                            lambda: self._mock_mcp())
        monkeypatch.setattr("rfp_automation.agents.writing_agent.llm_text_call", mock_llm)

        agent = RequirementWritingAgent()
        result = agent.process(self._writing_state())

        matrix = result["writing_result"]["coverage_matrix"]
        coverage_by_id = {c["requirement_id"]: c for c in matrix}
        assert coverage_by_id["REQ-001"]["coverage_quality"] == "full"
        assert coverage_by_id["REQ-002"]["coverage_quality"] == "missing"

    def test_writing_skips_commercial_legal(self, monkeypatch):
        """Commercial and legal sections get placeholder content, not LLM calls."""
        from rfp_automation.agents import RequirementWritingAgent
        from rfp_automation.models.schemas import ResponseSection

        sections = [
            ResponseSection(
                section_id="SEC-01", title="Technical Solution",
                section_type="requirement_driven",
                description="Tech details",
                requirement_ids=["REQ-001"],
                priority=1,
            ),
            ResponseSection(
                section_id="SEC-02", title="Pricing",
                section_type="commercial",
                description="Cost breakdown",
                requirement_ids=[],
                priority=3,
            ),
            ResponseSection(
                section_id="SEC-03", title="Legal Terms",
                section_type="legal",
                description="Contract terms",
                requirement_ids=[],
                priority=4,
            ),
        ]

        call_count = {"n": 0}

        def mock_llm(prompt, deterministic=False):
            call_count["n"] += 1
            return json.dumps({
                "content": "Technical content here.",
                "requirements_addressed": ["REQ-001"],
                "word_count": 3,
            })

        monkeypatch.setattr("rfp_automation.agents.writing_agent.MCPService",
                            lambda: self._mock_mcp())
        monkeypatch.setattr("rfp_automation.agents.writing_agent.llm_text_call", mock_llm)

        agent = RequirementWritingAgent()
        result = agent.process(self._writing_state(sections=sections))

        # LLM called only once (for the requirement_driven section)
        assert call_count["n"] == 1

        wr = result["writing_result"]
        assert len(wr["section_responses"]) == 3
        # Commercial and legal have placeholder content
        commercial = [s for s in wr["section_responses"] if s["section_id"] == "SEC-02"][0]
        legal = [s for s in wr["section_responses"] if s["section_id"] == "SEC-03"][0]
        assert "COMMERCIAL" in commercial["content"]
        assert "LEGAL" in legal["content"]

    def test_writing_empty_plan(self, monkeypatch):
        """Empty architecture plan → empty WritingResult, no crash."""
        from rfp_automation.agents import RequirementWritingAgent

        agent = RequirementWritingAgent()
        result = agent.process(self._writing_state(sections=[]))

        wr = result["writing_result"]
        assert wr["section_responses"] == []
        assert wr["coverage_matrix"] == []
        assert result["status"] == PipelineStatus.ASSEMBLING_NARRATIVE.value

    def test_writing_no_rfp_id_raises(self):
        """Missing rfp_id → ValueError."""
        from rfp_automation.agents import RequirementWritingAgent

        agent = RequirementWritingAgent()
        state = RFPGraphState(
            status=PipelineStatus.WRITING_RESPONSES,
        ).model_dump()
        with pytest.raises(ValueError, match="No rfp_id"):
            agent.process(state)

    def test_writing_llm_failure_graceful(self, monkeypatch):
        """LLM returns empty → section gets empty content, pipeline continues."""
        from rfp_automation.agents import RequirementWritingAgent

        monkeypatch.setattr("rfp_automation.agents.writing_agent.MCPService",
                            lambda: self._mock_mcp())
        monkeypatch.setattr("rfp_automation.agents.writing_agent.llm_text_call",
                            lambda prompt, deterministic=False: "")

        agent = RequirementWritingAgent()
        result = agent.process(self._writing_state())

        wr = result["writing_result"]
        # Sections should exist but with empty content
        assert len(wr["section_responses"]) == 2
        assert result["status"] == PipelineStatus.ASSEMBLING_NARRATIVE.value

