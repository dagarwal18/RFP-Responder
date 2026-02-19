from enum import Enum

class AgentStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"

class AgentRole(str, Enum):
    INTAKE = "intake"
    STRUCTURING = "structuring"
    GO_NO_GO = "go_no_go"
    REQ_EXTRACTION = "req_extraction"
    REQ_VALIDATION = "req_validation"
    ARCHITECTURE = "architecture"
    WRITING = "writing"
    NARRATIVE = "narrative"
    TECH_VALIDATION = "tech_validation"
    COMMERCIAL = "commercial"
    LEGAL = "legal"
    FINAL_READINESS = "final_readiness"
    SUBMISSION = "submission"

class GoNoGoDecision(str, Enum):
    GO = "GO"
    NO_GO = "NO_GO"

class ValidationStatus(str, Enum):
    PASS = "PASS"
    REJECT = "REJECT"

class LegalStatus(str, Enum):
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    BLOCKED = "BLOCKED"
