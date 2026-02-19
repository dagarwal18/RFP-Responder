from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.state import RFPState
from rfp_automation.mcp.mcp_server import mcp_server

class CommercialAgent(BaseAgent):
    def __init__(self):
        super().__init__("E1_Commercial")

from rfp_automation.utils.llm import llm_client
import json

class CommercialAgent(BaseAgent):
    def __init__(self):
        super().__init__("E1_Commercial")

    async def run(self, state: RFPState) -> RFPState:
        print(f"[{self.name}] Calculating pricing...")
        
        req_count = len(state.requirements)
        
        sys_prompt = """Estimate the project cost based on the requirements volume and complexity.
        Return a JSON object with keys: total_cost (number), currency (str), breakdown (dict).
        Assume a standard rate of $150/hr."""
        
        user_prompt = f"Number of Requirements: {req_count}\nClient: {state.client_name}\nSummary: {state.raw_text[:500]}..."
        
        try:
            response = llm_client.generate(sys_prompt, user_prompt)
            clean_json = response.replace("```json", "").replace("```", "").strip()
            pricing = json.loads(clean_json)
        except Exception as e:
            print(f"[{self.name}] Pricing calc failed: {e}")
            pricing = {"total_cost": 100000, "currency": "USD", "breakdown": {"Base": 100000}}
        
        state.commercial_response = pricing
        state.log(f"{self.name} estimated total cost: {pricing.get('currency', '$')} {pricing.get('total_cost', 0)}")
        return state
