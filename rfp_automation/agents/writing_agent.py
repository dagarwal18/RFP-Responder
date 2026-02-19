from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.state import RFPState
from rfp_automation.utils.llm import llm_client

from rfp_automation.mcp.mcp_server import mcp_server

class WritingAgent(BaseAgent):
    def __init__(self):
        super().__init__("C2_Writing")

    async def run(self, state: RFPState) -> RFPState:
        print(f"[{self.name}] Writing content with LLM...")
        
        responses = {}
        for section, req_ids in state.architecture_plan.items():
            # Gather requirements text for this section
            req_texts = [r["text"] for r in state.requirements if r["id"] in req_ids]
            req_context = "\n".join(req_texts)
            
            # RAG: Retrieve context from RFP and Knowledge Base
            query = f"{section} {' '.join(req_texts[:3])}"
            
            rfp_context = await mcp_server.query_rfp(state.rfp_id, query)
            kb_context = await mcp_server.query_knowledge_base(query)
            
            context_str = f"RFP Context:\n{rfp_context}\n\nCompany Capabilities:\n{kb_context}"
            
            system_prompt = "You are a Proposal Writer. Write a professional, winning response addressing the requirements using the provided context."
            user_prompt = f"Section: {section}\nRequirements:\n{req_context}\n\n{context_str}\n\nWrite a 2-3 sentence response."
            
            content = llm_client.generate(system_prompt, user_prompt)
            responses[section] = content
            
            # Update compliance matrix
            for rid in req_ids:
                state.compliance_matrix[rid] = section

        state.section_responses = responses
        state.log(f"{self.name} wrote {len(responses)} sections")
        return state
