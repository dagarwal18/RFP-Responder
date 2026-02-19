from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum

class AgentStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class RFPState(BaseModel):
    rfp_id: str
    client_name: Optional[str] = None
    status: AgentStatus = AgentStatus.IDLE
    current_stage: str = "init"
    # Add other fields from documentation
