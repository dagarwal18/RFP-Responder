from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.state import RFPState, LegalStatus

class LegalAgent(BaseAgent):
    def __init__(self):
        super().__init__("E2_Legal")

from rfp_automation.utils.llm import llm_client
from rfp_automation.models.state import LegalStatus

class LegalAgent(BaseAgent):
    def __init__(self):
        super().__init__("E2_Legal")

    async def run(self, state: RFPState) -> RFPState:
        print(f"[{self.name}] Reviewing legal terms...")
        
        sys_prompt = """Analyze the RFP text for legal risks (IP, Indemnification, Termination). 
        Return a list of risks found. If none, return 'No major risks'."""
        
        user_prompt = f"RFP Text extracted: {state.raw_text[:3000]}"
        
        response = llm_client.generate(sys_prompt, user_prompt)
        
        risks = [line for line in response.split('\n') if '-' in line or len(line) > 10]
        state.legal_risks = risks
        
        # Simplified approval logic
        if len(risks) < 5:
             state.legal_status = LegalStatus.APPROVED
        else:
             state.legal_status = LegalStatus.CONDITIONAL
        
        state.log(f"{self.name} found {len(risks)} risks. Status: {state.legal_status}")
        return state
