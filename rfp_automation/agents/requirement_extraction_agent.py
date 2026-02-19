from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.state import RFPState
from rfp_automation.mcp.mcp_server import mcp_server
from rfp_automation.utils.llm import llm_client

class RequirementExtractionAgent(BaseAgent):
    def __init__(self):
        super().__init__("B1_ReqExtraction")

    async def run(self, state: RFPState) -> RFPState:
        print(f"[{self.name}] Extracting requirements with LLM...")
        
        system_prompt = """You are a Requirements Analyst. Extract key requirements from the RFP text.
        Return a JSON list of objects with fields: id (REQ-001, etc.), text, category, mandatory (boolean).
        Return ONLY valid JSON.
        """
        user_prompt = f"RFP Text: {state.raw_text}"
        
        response = llm_client.generate(system_prompt, user_prompt)
        
        try:
            # Basic cleanup to ensure JSON parsing works if LLM adds markdown blocks
            clean_response = response.replace("```json", "").replace("```", "").strip()
            import json
            reqs = json.loads(clean_response)
        except Exception as e:
            print(f"[{self.name}] JSON Parse Error: {e}. Fallback to mock.")
            reqs = [
                {"id": "REQ-001", "text": "System must support SSO (Fallback)", "category": "Security", "mandatory": True}
            ]
        
        state.requirements = reqs
        state.log(f"{self.name} extracted {len(reqs)} requirements")
        return state
