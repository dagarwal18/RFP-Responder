from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.state import RFPState

class RequirementValidationAgent(BaseAgent):
    def __init__(self):
        super().__init__("B2_ReqValidation")

from rfp_automation.utils.llm import llm_client

class RequirementValidationAgent(BaseAgent):
    def __init__(self):
        super().__init__("B2_ReqValidation")

    async def run(self, state: RFPState) -> RFPState:
        print(f"[{self.name}] Validating requirements...")
        
        req_text = "\n".join([f"{r['id']}: {r['text']}" for r in state.requirements])
        
        sys_prompt = "Review the extracted requirements for clarity, completeness, and ambiguity. Return a list of issues found, or 'NO ISSUES' if clean."
        user_prompt = f"Requirements:\n{req_text}"
        
        response = llm_client.generate(sys_prompt, user_prompt)
        
        issues = []
        if "NO ISSUES" not in response.upper():
            # Naive parsing: treat lines as issues
            issues = [line.strip() for line in response.split('\n') if line.strip() and '-' in line]
        
        state.validation_issues = issues
        state.log(f"{self.name} found {len(issues)} potential issues")
        return state
