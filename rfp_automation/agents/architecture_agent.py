from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.state import RFPState
from rfp_automation.mcp.mcp_server import mcp_server

from rfp_automation.utils.llm import llm_client
import json

class ArchitectureAgent(BaseAgent):
    def __init__(self):
        super().__init__("C1_Architecture")

    async def run(self, state: RFPState) -> RFPState:
        print(f"[{self.name}] Planning architecture...")
        
        req_summary = "\n".join([f"{r['id']}: {r['text']}" for r in state.requirements])
        sections_list = list(state.sections.keys())
        
        sys_prompt = f"""Map the requirements to the proposed sections.
        Return a JSON dictionary where keys are Section Names and values are lists of Requirement IDs.
        Sections available: {sections_list}"""
        
        user_prompt = f"Requirements:\n{req_summary}"
        
        try:
            response = llm_client.generate(sys_prompt, user_prompt)
            clean_json = response.replace("```json", "").replace("```", "").strip()
            plan = json.loads(clean_json)
            state.architecture_plan = plan
        except Exception as e:
            print(f"[{self.name}] Architecture planning failed: {e}")
            # Fallback: put all reqs in first section
            if sections_list:
                state.architecture_plan = {sections_list[0]: [r['id'] for r in state.requirements]}
        
        state.log(f"{self.name} created plan mapping requirements to sections")
        return state
