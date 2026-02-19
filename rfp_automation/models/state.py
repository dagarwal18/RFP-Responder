from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union
from rfp_automation.models.enums import AgentStatus, GoNoGoDecision, ValidationStatus, LegalStatus

class RFPState(BaseModel):
    # --- Metadata (A1) ---
    rfp_id: str = Field(default="")
    client_name: Optional[str] = None
    deadline: Optional[str] = None
    status: str = "RECEIVED"
    file_path: Optional[str] = None
    raw_text: Optional[str] = None

    # --- Structuring (A2) ---
    sections: Dict[str, Any] = Field(default_factory=dict)
    structure_confidence: float = 0.0

    # --- Go/No-Go (A3) ---
    gonogo_decision: Optional[GoNoGoDecision] = None
    gonogo_reasoning: Optional[str] = None

    # --- Requirements (B1/B2) ---
    requirements: List[Dict[str, Any]] = Field(default_factory=list)
    validation_issues: List[str] = Field(default_factory=list)

    # --- Architecture (C1/C2/C3) ---
    architecture_plan: Dict[str, Any] = Field(default_factory=dict)
    section_responses: Dict[str, str] = Field(default_factory=dict) # Section ID -> Prose
    compliance_matrix: Dict[str, str] = Field(default_factory=dict) # Req ID -> Section ID
    full_proposal_text: Optional[str] = None

    # --- Technical Validation (D1) ---
    validation_status: Optional[ValidationStatus] = None
    validation_feedback: List[str] = Field(default_factory=list)
    retry_count: int = 0

    # --- Commercial & Legal (E1/E2) ---
    commercial_response: Dict[str, Any] = Field(default_factory=dict)
    legal_status: Optional[LegalStatus] = None
    legal_risks: List[str] = Field(default_factory=list)

    # --- Finalization (F1/F2) ---
    approval_package: Dict[str, Any] = Field(default_factory=dict)
    final_artifact_path: Optional[str] = None
    
    # --- Audit ---
    logs: List[str] = Field(default_factory=list)

    def log(self, message: str):
        self.logs.append(message)
