from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.state import RFPState

from rfp_automation.utils.llm import llm_client

class NarrativeAgent(BaseAgent):
    def __init__(self):
        super().__init__("C3_Narrative")

    async def run(self, state: RFPState) -> RFPState:
        print(f"[{self.name}] Assembling proposal...")
        
        # Combine sections
        full_text = f"# Proposal for {state.client_name}\n\n"
        
        # Introduction
        intro_prompt = f"Write a brief executive summary introduction for a proposal to {state.client_name}."
        full_text += llm_client.generate("You are a Proposal Manager.", intro_prompt) + "\n\n"
        
        for section, content in state.section_responses.items():
            full_text += f"## {section}\n{content}\n\n"
            
        state.full_proposal_text = full_text
        state.log(f"{self.name} assembled full proposal ({len(full_text)} chars)")
        return state
