"""
LangGraph shared state — the single object that flows through every node.

Design rules:
  1. Each field is "owned" by one agent (see comments).
  2. Agents may READ any field but should only WRITE to their owned fields.
  3. The state is versioned for audit purposes.
"""

from __future__ import annotations

from typing import Annotated, Optional
from operator import add
from pydantic import BaseModel, Field

from .enums import PipelineStatus
from .schemas import (
    RFPMetadata,
    StructuringResult,
    GoNoGoResult,
    Requirement,
    RequirementsValidationResult,
    ArchitecturePlan,
    WritingResult,
    AssembledProposal,
    TechnicalValidationResult,
    CommercialResult,
    LegalResult,
    CommercialLegalGateResult,
    ApprovalPackage,
    SubmissionRecord,
    AuditEntry,
)


class RFPGraphState(BaseModel):
    """
    The shared graph state passed through every LangGraph node.

    LangGraph expects a TypedDict or Pydantic model.
    Using Pydantic gives us validation + serialization for free.
    """

    # ── Pipeline control ─────────────────────────────────
    status: PipelineStatus = PipelineStatus.RECEIVED
    current_agent: str = ""
    error_message: str = ""
    state_version: int = 0

    # ── Tracking (set by API route, used for WebSocket) ──
    tracking_rfp_id: str = ""

    # ── A1 Intake (owner: A1) ────────────────────────────
    rfp_metadata: RFPMetadata = Field(default_factory=RFPMetadata)
    uploaded_file_path: str = ""
    raw_text: str = ""  # kept temporarily; agents use MCP after embedding

    # ── A2 Structuring (owner: A2) ───────────────────────
    structuring_result: StructuringResult = Field(default_factory=StructuringResult)

    # ── A3 Go / No-Go (owner: A3) ────────────────────────
    go_no_go_result: GoNoGoResult = Field(default_factory=GoNoGoResult)

    # ── B1 Requirements Extraction (owner: B1) ───────────
    requirements: list[Requirement] = Field(default_factory=list)

    # ── B2 Requirements Validation (owner: B2) ───────────
    requirements_validation: RequirementsValidationResult = Field(
        default_factory=RequirementsValidationResult
    )

    # ── C1 Architecture Planning (owner: C1) ─────────────
    architecture_plan: ArchitecturePlan = Field(default_factory=ArchitecturePlan)

    # ── C2 Requirement Writing (owner: C2) ───────────────
    writing_result: WritingResult = Field(default_factory=WritingResult)

    # ── C3 Narrative Assembly (owner: C3) ─────────────────
    assembled_proposal: AssembledProposal = Field(default_factory=AssembledProposal)

    # ── D1 Technical Validation (owner: D1) ──────────────
    technical_validation: TechnicalValidationResult = Field(
        default_factory=TechnicalValidationResult
    )

    # ── E1 Commercial (owner: E1) ────────────────────────
    commercial_result: CommercialResult = Field(default_factory=CommercialResult)

    # ── E2 Legal (owner: E2) ─────────────────────────────
    legal_result: LegalResult = Field(default_factory=LegalResult)

    # ── E1+E2 Gate (owner: orchestration) ────────────────
    commercial_legal_gate: CommercialLegalGateResult = Field(
        default_factory=CommercialLegalGateResult
    )

    # ── F1 Final Readiness (owner: F1) ───────────────────
    approval_package: ApprovalPackage = Field(default_factory=ApprovalPackage)

    # ── F2 Submission (owner: F2) ────────────────────────
    submission_record: SubmissionRecord = Field(default_factory=SubmissionRecord)

    # ── Audit trail (append-only) ────────────────────────
    audit_trail: list[AuditEntry] = Field(default_factory=list)

    # ── Helper ───────────────────────────────────────────

    def add_audit(self, agent: str, action: str, details: str = "") -> None:
        self.state_version += 1
        self.audit_trail.append(
            AuditEntry(
                agent=agent,
                action=action,
                details=details,
                state_version=self.state_version,
            )
        )
