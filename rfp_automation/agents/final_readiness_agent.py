from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.state import RFPState

class FinalReadinessAgent(BaseAgent):
    def __init__(self):
        super().__init__("F1_FinalReadiness")

class FinalReadinessAgent(BaseAgent):
    def __init__(self):
        super().__init__("F1_FinalReadiness")

    async def run(self, state: RFPState) -> RFPState:
        print(f"[{self.name}] Preparing approval package...")
        
        package = {
             "client": state.client_name,
             "proposal_length": len(state.full_proposal_text or ""),
             "pricing": state.commercial_response,
             "legal_status": state.legal_status,
             "risks": state.legal_risks,
             "validation_status": state.validation_status
        }
        state.approval_package = package
        
        state.log(f"{self.name} compiled approval package. Ready for submission.")
        return state
