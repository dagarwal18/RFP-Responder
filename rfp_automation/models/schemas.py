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
    RequirementCategory,
    ImpactLevel,
    RiskLevel,
    GoNoGoDecision,
    ValidationDecision,
    LegalDecision,
    ApprovalDecision,
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


class GoNoGoResult(BaseModel):
    decision: GoNoGoDecision = GoNoGoDecision.GO
    strategic_fit_score: float = 0.0   # 1-10
    technical_feasibility_score: float = 0.0
    regulatory_risk_score: float = 0.0
    policy_violations: list[str] = []
    red_flags: list[str] = []
    justification: str = ""


# ── B1 Requirements Extraction ───────────────────────────


class Requirement(BaseModel):
    """A single requirement extracted from the RFP."""
    requirement_id: str
    text: str
    type: RequirementType = RequirementType.MANDATORY
    category: RequirementCategory = RequirementCategory.TECHNICAL
    impact: ImpactLevel = ImpactLevel.MEDIUM
    source_section: str = ""
    keywords: list[str] = []


# ── B2 Requirements Validation ───────────────────────────


class ValidationIssue(BaseModel):
    issue_type: str  # "duplicate" | "contradiction" | "ambiguity"
    requirement_ids: list[str]
    description: str
    severity: str = "warning"  # "warning" | "info"


class RequirementsValidationResult(BaseModel):
    validated_requirements: list[Requirement] = []
    issues: list[ValidationIssue] = []
    total_requirements: int = 0
    mandatory_count: int = 0
    optional_count: int = 0


# ── C1 Architecture Planning ─────────────────────────────


class ResponseSection(BaseModel):
    """A planned section of the proposal response."""
    section_id: str
    title: str
    requirement_ids: list[str] = []
    mapped_capabilities: list[str] = []
    priority: int = 0


class ArchitecturePlan(BaseModel):
    sections: list[ResponseSection] = []
    coverage_gaps: list[str] = []  # requirement IDs not yet mapped
    total_sections: int = 0


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


# ── D1 Technical Validation ──────────────────────────────


class ValidationCheckResult(BaseModel):
    check_name: str  # "completeness" | "alignment" | "realism" | "consistency"
    passed: bool = True
    issues: list[str] = []


class TechnicalValidationResult(BaseModel):
    decision: ValidationDecision = ValidationDecision.PASS
    checks: list[ValidationCheckResult] = []
    critical_failures: int = 0
    warnings: int = 0
    feedback_for_revision: str = ""
    retry_count: int = 0


# ── E1 Commercial ────────────────────────────────────────


class PricingBreakdown(BaseModel):
    base_cost: float = 0.0
    per_requirement_cost: float = 0.0
    complexity_multiplier: float = 1.0
    risk_margin: float = 0.0
    total_price: float = 0.0
    payment_terms: str = ""
    assumptions: list[str] = []
    exclusions: list[str] = []


class CommercialResult(BaseModel):
    pricing: PricingBreakdown = Field(default_factory=PricingBreakdown)
    commercial_narrative: str = ""


# ── E2 Legal ──────────────────────────────────────────────


class ContractClauseRisk(BaseModel):
    clause_id: str
    clause_text: str
    risk_level: RiskLevel = RiskLevel.LOW
    concern: str = ""
    recommendation: str = ""


class LegalResult(BaseModel):
    decision: LegalDecision = LegalDecision.APPROVED
    clause_risks: list[ContractClauseRisk] = []
    compliance_status: dict[str, bool] = {}  # cert_name -> held?
    block_reasons: list[str] = []
    risk_register_summary: str = ""


# ── E1 + E2 Combined Gate ────────────────────────────────


class CommercialLegalGateResult(BaseModel):
    gate_decision: CommercialLegalGateDecision = CommercialLegalGateDecision.CLEAR
    commercial: CommercialResult = Field(default_factory=CommercialResult)
    legal: LegalResult = Field(default_factory=LegalResult)


# ── F1 Final Readiness ───────────────────────────────────


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
