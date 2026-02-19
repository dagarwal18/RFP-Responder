from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.state import RFPState

class IntakeAgent(BaseAgent):
    async def run(self, state: RFPState) -> RFPState:
        print(f"{self.name} running...")
        # Implementation here
        return state
