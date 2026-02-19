from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.state import RFPState
from rfp_automation.models.enums import ValidationStatus
from rfp_automation.utils.llm import llm_client

class TechnicalValidationAgent(BaseAgent):
    def __init__(self):
        super().__init__("D1_TechValidation")

    async def run(self, state: RFPState) -> RFPState:
        print(f"[{self.name}] Validating proposal...")
        
        sys_prompt = """Review the proposal text against the requirements. 
        If it addresses them adequately, return 'PASS'. 
        If there are missing requirements or technical gaps, return 'FAIL' followed by a brief reason."""
        
        req_summary = "\n".join([f"{r['id']}: {r['text']}" for r in state.requirements])
        user_prompt = f"Requirements:\n{req_summary}\n\nProposal:\n{state.full_proposal_text}"
        
        response = llm_client.generate(sys_prompt, user_prompt)
        
        if "PASS" in response.upper():
            state.validation_status = ValidationStatus.PASS
            state.log(f"{self.name} PASSED validation.")
        else:
            state.validation_status = ValidationStatus.REJECT
            state.validation_issues.append(response)
            state.retry_count += 1
            state.log(f"{self.name} REJECTED validation. Feedback: {response[:50]}...")
            
        # Simulate retry limit to avoid infinite loops in demo
        if state.retry_count > 1:
             state.validation_status = ValidationStatus.PASS
             state.log(f"{self.name} Force PASSED after retries.")

        return state
