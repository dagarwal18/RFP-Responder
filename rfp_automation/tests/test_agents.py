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
            lambda: type("MockMCP", (), {"query_rfp_all_chunks": lambda self, rfp_id, top_k=100: mock_chunks})(),
        )
        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.llm_text_call",
            lambda prompt: llm_response,
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
            lambda: type("MockMCP", (), {"query_rfp_all_chunks": lambda self, rfp_id, top_k=100: mock_chunks})(),
        )
        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.llm_text_call",
            lambda prompt: llm_response,
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
            lambda: type("MockMCP", (), {"query_rfp_all_chunks": lambda self, rfp_id, top_k=100: mock_chunks})(),
        )
        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.llm_text_call",
            lambda prompt: "This is not valid JSON at all",
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
        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.llm_text_call", lambda prompt: llm_response)

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
        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.llm_text_call", lambda prompt: llm_response)

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
        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.llm_text_call", lambda prompt: llm_response)

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
        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.llm_text_call", lambda prompt: llm_response)

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
    """Tests for B1 Requirements Extraction Agent."""

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
        """Valid LLM response → requirements populated, correct status."""
        from rfp_automation.agents import RequirementsExtractionAgent

        llm_responses = [
            json.dumps([
                {"requirement_id": "REQ-001", "text": "The system must support SSO via SAML 2.0",
                 "type": "MANDATORY", "classification": "FUNCTIONAL",
                 "category": "TECHNICAL", "impact": "HIGH", "keywords": ["SSO", "SAML"]},
                {"requirement_id": "REQ-002", "text": "Data encryption at rest is required",
                 "type": "MANDATORY", "classification": "NON_FUNCTIONAL",
                 "category": "SECURITY", "impact": "CRITICAL", "keywords": ["encryption"]},
            ]),
            json.dumps([
                {"requirement_id": "REQ-003", "text": "Handle 10,000 concurrent users",
                 "type": "OPTIONAL", "classification": "NON_FUNCTIONAL",
                 "category": "TECHNICAL", "impact": "HIGH", "keywords": ["scalability"]},
            ]),
        ]
        call_count = {"n": 0}

        def mock_llm(prompt):
            idx = call_count["n"]
            call_count["n"] += 1
            return llm_responses[idx]

        mock_mcp = type("MockMCP", (), {
            "query_rfp": lambda self, q, rfp_id, top_k=10: [],
        })()
        monkeypatch.setattr("rfp_automation.agents.requirement_extraction_agent.MCPService", lambda: mock_mcp)
        monkeypatch.setattr("rfp_automation.agents.requirement_extraction_agent.llm_text_call", mock_llm)

        agent = RequirementsExtractionAgent()
        result = agent.process(self._extraction_state())

        assert len(result["requirements"]) == 3
        assert result["requirements"][0]["requirement_id"] == "REQ-001"
        assert result["requirements"][2]["requirement_id"] == "REQ-003"
        assert result["status"] == PipelineStatus.VALIDATING_REQUIREMENTS.value

    def test_extraction_no_sections(self):
        """Empty structuring result → 0 requirements, no error."""
        from rfp_automation.agents import RequirementsExtractionAgent
        from rfp_automation.models.schemas import RFPMetadata, StructuringResult

        state = RFPGraphState(
            status=PipelineStatus.EXTRACTING_REQUIREMENTS,
            rfp_metadata=RFPMetadata(rfp_id="RFP-EMPTY"),
            structuring_result=StructuringResult(sections=[], overall_confidence=0.0),
        ).model_dump()

        agent = RequirementsExtractionAgent()
        result = agent.process(state)
        assert result["requirements"] == []
        assert result["status"] == PipelineStatus.VALIDATING_REQUIREMENTS.value

    def test_extraction_invalid_json(self, monkeypatch):
        """Malformed LLM response → 0 requirements, no crash."""
        from rfp_automation.agents import RequirementsExtractionAgent

        mock_mcp = type("MockMCP", (), {
            "query_rfp": lambda self, q, rfp_id, top_k=10: [],
        })()
        monkeypatch.setattr("rfp_automation.agents.requirement_extraction_agent.MCPService", lambda: mock_mcp)
        monkeypatch.setattr("rfp_automation.agents.requirement_extraction_agent.llm_text_call",
                            lambda prompt: "This is not JSON at all!!!")

        agent = RequirementsExtractionAgent()
        result = agent.process(self._extraction_state())
        assert result["requirements"] == []

    def test_extraction_classification_types(self, monkeypatch):
        """Verify FUNCTIONAL and NON_FUNCTIONAL are correctly assigned."""
        from rfp_automation.agents import RequirementsExtractionAgent
        from rfp_automation.models.schemas import RFPMetadata, StructuringResult, RFPSection

        llm_response = json.dumps([
            {"requirement_id": "REQ-001", "text": "System must provide user dashboard",
             "type": "MANDATORY", "classification": "FUNCTIONAL",
             "category": "FUNCTIONAL", "impact": "HIGH", "keywords": ["dashboard"]},
            {"requirement_id": "REQ-002", "text": "System must respond within 200ms",
             "type": "MANDATORY", "classification": "NON_FUNCTIONAL",
             "category": "TECHNICAL", "impact": "HIGH", "keywords": ["performance"]},
        ])

        mock_mcp = type("MockMCP", (), {
            "query_rfp": lambda self, q, rfp_id, top_k=10: [],
        })()
        monkeypatch.setattr("rfp_automation.agents.requirement_extraction_agent.MCPService", lambda: mock_mcp)
        monkeypatch.setattr("rfp_automation.agents.requirement_extraction_agent.llm_text_call",
                            lambda prompt: llm_response)

        state = RFPGraphState(
            status=PipelineStatus.EXTRACTING_REQUIREMENTS,
            rfp_metadata=RFPMetadata(rfp_id="RFP-CLASS"),
            structuring_result=StructuringResult(
                sections=[RFPSection(
                    section_id="SEC-01", title="Mixed", category="technical",
                    content_summary="Mixed requirements.", confidence=0.9,
                )], overall_confidence=0.9,
            ),
        ).model_dump()

        agent = RequirementsExtractionAgent()
        result = agent.process(state)
        assert len(result["requirements"]) == 2
        assert result["requirements"][0]["classification"] == "FUNCTIONAL"
        assert result["requirements"][1]["classification"] == "NON_FUNCTIONAL"

    def test_extraction_no_rfp_id_raises(self):
        """Missing rfp_id → ValueError."""
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
                            lambda prompt: json.dumps({"confidence_score": 0.92, "issues": [], "requirement_notes": {}}))

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

        def mock_llm(prompt):
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
                            lambda prompt: json.dumps({
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

