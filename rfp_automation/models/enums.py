from enum import Enum

class AgentRole(str, Enum):
    INTAKE = "intake"
    STRUCTURING = "structuring"
    GO_NO_GO = "go_no_go"
    # ... others
