import uuid
from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.state import RFPState
from rfp_automation.mcp.mcp_server import mcp_server

from rfp_automation.utils.llm import llm_client
import json

class IntakeAgent(BaseAgent):
    def __init__(self):
        super().__init__("A1_Intake")

    async def run(self, state: RFPState) -> RFPState:
        print(f"[{self.name}] Processing file...")
        
        # Use existing raw_text if available (from upload), else use dummy if empty
        if not state.raw_text or len(state.raw_text) < 10:
             state.raw_text = "RFP for Enterprise Cloud Migration: We are a Fortune 500 company seeking a partner to migrate 500+ on-premise servers to AWS. Key requirements: Zero downtime, ISO 27001 compliance, and 24/7 managed support post-migration. Budget: $5M. Deadline: 2024-12-31."
        
        # Extract Metadata using LLM
        sys_prompt = "Extract metadata from the RFP text. Return JSON with keys: client_name, deadline, summary."
        user_prompt = f"RFP Text: {state.raw_text[:2000]}" # Limit context for speed/cost if needed
        
        try:
            response = llm_client.generate(sys_prompt, user_prompt)
            clean_json = response.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)
            
            state.client_name = data.get("client_name", "Unknown Client")
            state.deadline = data.get("deadline", "TBD")
            summary = data.get("summary", "")
        except Exception as e:
            print(f"[{self.name}] Metadata extraction failed: {e}")
            state.client_name = "Unknown"
        
        # Store in MCP
        await mcp_server.store_rfp(state.rfp_id, state.raw_text)
        
        state.log(f"{self.name} processed RFP for {state.client_name}")
        return state
