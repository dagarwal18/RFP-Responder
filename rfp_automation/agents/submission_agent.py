from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.state import RFPState

class SubmissionAgent(BaseAgent):
    def __init__(self):
        super().__init__("F2_Submission")

    async def run(self, state: RFPState) -> RFPState:
        print(f"[{self.name}] Submitting RFP...")
        
        state.status = "SUBMITTED"
        state.final_artifact_path = f"s3://bucket/rfps/{state.rfp_id}/final.pdf"
        
        state.log(f"{self.name} submitted successfully.")
        return state
