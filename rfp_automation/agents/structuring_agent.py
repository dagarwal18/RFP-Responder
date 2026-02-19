from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.state import RFPState
from rfp_automation.mcp.mcp_server import mcp_server

from rfp_automation.utils.llm import llm_client
import json

class StructuringAgent(BaseAgent):
    def __init__(self):
        super().__init__("A2_Structuring")

    async def run(self, state: RFPState) -> RFPState:
        print(f"[{self.name}] Structuring document...")
        
        sys_prompt = """Analyze the RFP text and suggest a structure for the proposal. 
        Return a JSON dictionary where keys are section titles (e.g., 'Executive Summary', 'Technical Approach') and values are brief descriptions of what goes in them."""
        
        user_prompt = f"RFP Text (first 3000 chars): {state.raw_text[:3000]}"
        
        try:
            response = llm_client.generate(sys_prompt, user_prompt)
            clean_json = response.replace("```json", "").replace("```", "").strip()
            sections = json.loads(clean_json)
            state.sections = sections
            state.structure_confidence = 0.9
        except Exception as e:
            print(f"[{self.name}] Structuring failed: {e}")
            state.sections = {"Executive Summary": "Overview", "Solution": "Technical details"}
            state.structure_confidence = 0.5
        
        state.log(f"{self.name} identified {len(state.sections)} sections")
        return state
