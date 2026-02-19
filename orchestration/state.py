from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class Evidence(BaseModel):
    page: int
    text: str
    paragraph_index: Optional[int] = None

class Requirement(BaseModel):
    id: str
    title: Optional[str]
    description: Optional[str]
    evidence: Evidence
    cbr_citation: Optional[str] = None
    logic_status: Optional[str] = None
    reasoning_trace: Optional[str] = None
    draft: Optional[str] = None

class RequirementMatrix(BaseModel):
    rfp_id: str
    requirements: List[Requirement] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
