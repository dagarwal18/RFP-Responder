"""
Reusable data schemas for sub-structures embedded inside the graph state.
Each schema represents a clearly-bounded data object produced by one agent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from .enums import (
    RequirementType,
    RequirementClassification,
    RequirementCategory,
    ImpactLevel,
    RiskLevel,
    GoNoGoDecision,
    ValidationDecision,
    LegalDecision,
    ApprovalDecision,
    HumanValidationDecision,
    CommercialLegalGateDecision,
)


# ── A1 Intake ────────────────────────────────────────────


class RFPMetadata(BaseModel):
    """Basic metadata extracted by the Intake agent."""
    rfp_id: str = ""
    client_name: str = ""
    rfp_title: str = ""
    deadline: Optional[datetime] = None
    rfp_number: str = ""
    source_file_path: str = ""
    page_count: int = 0
    word_count: int = 0
    file_hash: str = ""
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    issue_date: Optional[str] = None
    deadline_text: Optional[str] = None
    received_at: datetime = Field(default_factory=datetime.utcnow)


# ── A2 Structuring ───────────────────────────────────────


class RFPSection(BaseModel):
    """A classified section of the RFP document."""
    section_id: str
    title: str
    category: str  # scope, technical, compliance, legal, submission, evaluation
    content_summary: str
    confidence: float = 0.0  # 0-1
    page_range: str = ""


class StructuringResult(BaseModel):
    sections: list[RFPSection] = []
    overall_confidence: float = 0.0
    retry_count: int = 0


# ── A3 Go / No-Go ────────────────────────────────────────


class RequirementMapping(BaseModel):
    """Maps a single RFP requirement to a company policy."""
    requirement_id: str = ""          # "RFP-REQ-001"
    requirement_text: str = ""        # verbatim from RFP
    source_section: str = ""          # RFP section
    mapping_status: str = "NO_MATCH"  # "ALIGNS" | "VIOLATES" | "RISK" | "NO_MATCH"
    matched_policy: str = ""          # policy text, "" if none
    matched_policy_id: str = ""       # policy_id, "" if none
    confidence: float = 0.0
    reasoning: str = ""


class GoNoGoResult(BaseModel):
    decision: GoNoGoDecision = GoNoGoDecision.GO
    strategic_fit_score: float = 0.0   # 1-10
    technical_feasibility_score: float = 0.0
    regulatory_risk_score: float = 0.0
    policy_violations: list[str] = []
    red_flags: list[str] = []
    justification: str = ""
    requirement_mappings: list[RequirementMapping] = []
    total_requirements: int = 0
    aligned_count: int = 0
    violated_count: int = 0
    risk_count: int = 0
    no_match_count: int = 0


# ── B1 Requirements Extraction ───────────────────────────


class Requirement(BaseModel):
    """A single requirement extracted from the RFP."""
    requirement_id: str
    text: str
    type: RequirementType = RequirementType.MANDATORY
    classification: RequirementClassification = RequirementClassification.FUNCTIONAL
    category: RequirementCategory = RequirementCategory.TECHNICAL
    impact: ImpactLevel = ImpactLevel.MEDIUM
    source_section: str = ""
    keywords: list[str] = []
    source_chunk_indices: list[int] = []  # chunk_index values for traceability
    source_table_chunk_index: int = -1    # specific table chunk this req came from (-1 = not from table)


# ── B2 Requirements Validation ───────────────────────────


class ValidationIssue(BaseModel):
    issue_type: str  # "duplicate" | "contradiction" | "ambiguity"
    requirement_ids: list[str]
    description: str
    severity: str = "warning"  # "warning" | "info"


class RequirementsValidationResult(BaseModel):
    validated_requirements: list[Requirement] = []
    issues: list[ValidationIssue] = []
    confidence_score: float = 0.0
    total_requirements: int = 0
    mandatory_count: int = 0
    optional_count: int = 0
    functional_count: int = 0
    non_functional_count: int = 0
    duplicate_count: int = 0
    contradiction_count: int = 0
    ambiguity_count: int = 0


# ── C1 Architecture Planning ─────────────────────────────


class ResponseSection(BaseModel):
    """A planned section of the proposal response."""
    section_id: str
    title: str
    section_type: str = "requirement_driven"
    # "requirement_driven" | "knowledge_driven" | "commercial" | "legal" | "boilerplate"
    description: str = ""  # What this section should contain
    content_guidance: str = ""  # Specific instructions from the RFP on what goes here
    visual_relevance: str = "auto"  # auto | none | optional | required
    visual_type_hint: str = ""  # architecture | sequence | gantt | state | journey | class | auto
    visual_notes: str = ""  # What the visual should emphasize
    visual_source_terms: list[str] = []  # Entities and phrases to reuse in visuals
    requirement_ids: list[str] = []
    mapped_capabilities: list[str] = []
    priority: int = 0
    source_rfp_section: str = ""  # The original RFP section this maps to


class ArchitecturePlan(BaseModel):
    sections: list[ResponseSection] = []
    coverage_gaps: list[str] = []  # requirement IDs not yet mapped
    total_sections: int = 0
    rfp_response_instructions: str = ""  # Raw text about how the RFP says to structure the response


# ── C2 Requirement Writing ───────────────────────────────


class SectionResponse(BaseModel):
    """Generated prose for one response section."""
    section_id: str
    title: str
    content: str = ""
    requirements_addressed: list[str] = []
    word_count: int = 0


class CoverageEntry(BaseModel):
    requirement_id: str
    addressed_in_section: str
    coverage_quality: str = "full"  # "full" | "partial" | "missing"


class WritingResult(BaseModel):
    section_responses: list[SectionResponse] = []
    coverage_matrix: list[CoverageEntry] = []


# ── C3 Narrative Assembly ────────────────────────────────


class AssembledProposal(BaseModel):
    executive_summary: str = ""
    full_narrative: str = ""
    word_count: int = 0
    sections_included: int = 0
    has_placeholders: bool = False
    section_order: list[str] = []          # ordered section IDs
    coverage_appendix: str = ""            # requirement traceability matrix text


# ── D1 Technical Validation ──────────────────────────────


class ValidationCheckResult(BaseModel):
    check_name: str  # "completeness" | "alignment" | "realism" | "consistency"
    passed: bool = True
    issues: list[str] = []
    description: str = ""  # LLM explanation of WHY this check passed/failed


class TechnicalValidationResult(BaseModel):
    decision: ValidationDecision = ValidationDecision.PASS
    checks: list[ValidationCheckResult] = []
    critical_failures: int = 0
    warnings: int = 0
    feedback_for_revision: str = ""
    retry_count: int = 0


# ── E1 Commercial ────────────────────────────────────────


class PricingLineItem(BaseModel):
    """A single line item in the pricing breakdown."""
    label: str                    # e.g. "Implementation Services"
    quantity: float
    unit: str                     # "hours", "units", "fixed"
    unit_rate: float
    total: float
    category: str                 # maps to RequirementCategory


class CommercialResult(BaseModel):
    decision: str = "APPROVED"    # APPROVED | FLAGGED | REJECTED
    total_price: float = 0.0
    currency: str = "USD"
    line_items: list[PricingLineItem] = []
    risk_margin_pct: float = 0.0
    payment_schedule: list[dict] = []   # [{"milestone": str, "amount": float, "due": str}]
    assumptions: list[str] = []
    exclusions: list[str] = []
    commercial_narrative: str = ""      # LLM-generated prose
    validation_flags: list[str] = []    # warnings from commercial_rules.py
    confidence: float = 0.0             # 0.0–1.0


# ── E2 Legal ──────────────────────────────────────────────


class ContractClauseRisk(BaseModel):
    clause_id: str
    clause_text: str
    risk_level: RiskLevel = RiskLevel.LOW
    concern: str = ""
    recommendation: str = ""     # "accept" | "negotiate" | "reject"


class ComplianceCheck(BaseModel):
    """Certification compliance check result."""
    certification: str
    held: bool = False
    required: bool = False
    gap_severity: str = "low"    # "low" | "medium" | "high" | "critical"


class LegalResult(BaseModel):
    decision: LegalDecision = LegalDecision.APPROVED
    clause_risks: list[ContractClauseRisk] = []
    compliance_checks: list[ComplianceCheck] = []
    compliance_status: dict[str, bool] = {}  # cert_name -> held? (backward compat)
    block_reasons: list[str] = []
    risk_register_summary: str = ""     # LLM-generated narrative
    legal_narrative: str = ""           # Substantive legal section for the proposal
    confidence: float = 0.0             # 0.0–1.0


# ── E1 + E2 Combined Gate ────────────────────────────────


class CommercialLegalGateResult(BaseModel):
    gate_decision: CommercialLegalGateDecision = CommercialLegalGateDecision.CLEAR
    commercial: CommercialResult = Field(default_factory=CommercialResult)
    legal: LegalResult = Field(default_factory=LegalResult)


# ── F1 Final Readiness ───────────────────────────────────


class ReviewParagraph(BaseModel):
    paragraph_id: str
    text: str = ""
    page_start: int = 0
    page_end: int = 0


class ReviewSection(BaseModel):
    section_id: str
    title: str
    domain: str = "source"  # "source" | "response"
    page_start: int = 0
    page_end: int = 0
    full_text: str = ""
    section_type: str = ""
    source_section_title: str = ""
    requirement_ids: list[str] = []
    paragraphs: list[ReviewParagraph] = []


class ReviewAnchor(BaseModel):
    anchor_level: str = "section"  # "section" | "paragraph"
    domain: str = "response"       # "source" | "response"
    section_id: str = ""
    section_title: str = ""
    paragraph_id: str = ""
    excerpt: str = ""


class ReviewComment(BaseModel):
    comment_id: str
    anchor: ReviewAnchor = Field(default_factory=ReviewAnchor)
    comment: str = ""
    severity: str = "medium"       # "low" | "medium" | "high" | "critical"
    rerun_hint: str = "auto"
    status: str = "open"
    author: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class HumanValidationDecisionRecord(BaseModel):
    decision: Optional[HumanValidationDecision] = None
    reviewer: str = ""
    summary: str = ""
    rerun_from: str = ""
    submitted_at: Optional[datetime] = None


class ReviewPackage(BaseModel):
    review_id: str = ""
    status: str = "PENDING"
    source_sections: list[ReviewSection] = []
    response_sections: list[ReviewSection] = []
    comments: list[ReviewComment] = []
    decision: HumanValidationDecisionRecord = Field(
        default_factory=HumanValidationDecisionRecord
    )
    validation_summary: str = ""
    commercial_summary: str = ""
    legal_summary: str = ""
    total_comments: int = 0
    open_comment_count: int = 0


class ApprovalPackage(BaseModel):
    decision_brief: str = ""
    proposal_summary: str = ""
    pricing_summary: str = ""
    risk_summary: str = ""
    coverage_summary: str = ""
    approval_decision: Optional[ApprovalDecision] = None
    approver_notes: str = ""


# ── F2 Submission ────────────────────────────────────────


class SubmissionRecord(BaseModel):
    submitted_at: Optional[datetime] = None
    output_file_path: str = ""
    archive_path: str = ""
    file_hash: str = ""


# ── Audit Trail ──────────────────────────────────────────


class AuditEntry(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    agent: str
    action: str
    details: str = ""
    state_version: int = 0
