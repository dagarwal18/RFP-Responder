from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.state import RFPState, GoNoGoDecision
from rfp_automation.mcp.mcp_server import mcp_server
from rfp_automation.utils.llm import llm_client

class GoNoGoAgent(BaseAgent):
    def __init__(self):
        super().__init__("A3_GoNoGo")

    async def run(self, state: RFPState) -> RFPState:
        print(f"[{self.name}] Assessing RFP with LLM ({llm_client.model})...")
        
        # 1. Checks policies (Mock)
        violations = await mcp_server.check_policy(state.raw_text)
        
        if violations:
             state.gonogo_decision = GoNoGoDecision.NO_GO
             state.gonogo_reasoning = f"Policy Violations: {violations}"
             state.log(f"{self.name} NO_GO due to policy.")
             return state

        # 2. LLM Strategic Assessment
        system_prompt = """You are a senior Bid Manager. Analyze the RFP summary and decide GO or NO_GO.
        Output purely the reasoning. If it looks like a tech project we can do, say GO.
        """
        user_prompt = f"RFP Text: {state.raw_text[:2000]}..." # Truncate for efficiency if needed
        
        reasoning = llm_client.generate(system_prompt, user_prompt)
        
        # Simple heuristic parser for demo purposes
        if "NO_GO" in reasoning.upper() and "GO" not in reasoning.upper():
             decision = GoNoGoDecision.NO_GO
        else:
             decision = GoNoGoDecision.GO

        state.gonogo_decision = decision
        state.gonogo_reasoning = reasoning
            
        state.log(f"{self.name} decision: {state.gonogo_decision}")
        return state
