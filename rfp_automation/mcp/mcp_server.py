from typing import List, Dict, Any
from rfp_automation.mcp.vector_store.rfp_store import RFPVectorStore
from rfp_automation.mcp.knowledge_store import KnowledgeBaseStore
from rfp_automation.utils.llm import llm_client

class MCPServer:
    def __init__(self):
        self.rfp_store = RFPVectorStore()
        self.kb_store = KnowledgeBaseStore()

    async def store_rfp(self, rfp_id: str, text: str):
        self.rfp_store.add_rfp(rfp_id, text)

    async def query_rfp(self, rfp_id: str, query: str) -> List[str]:
        return self.rfp_store.query(rfp_id, query, k=3)

    async def query_knowledge_base(self, query: str) -> List[str]:
        return self.kb_store.search(query, k=3)

    async def check_policy(self, rfp_text: str) -> List[str]:
        # Intelligent Policy Check using LLM
        sys_prompt = """You are a Corporate Compliance Officer. Review the RFP text against the following policies:
        1. No business with sanctioned countries (North Korea, Iran, Russia).
        2. Minimum contract value of $50,000.
        3. Must not require on-site presence in conflict zones.
        
        Return a list of violations. If none, return 'NO VIOLATIONS'."""
        
        user_prompt = f"RFP Text (summary): {rfp_text[:3000]}"
        
        response = llm_client.generate(sys_prompt, user_prompt)
        
        if "NO VIOLATIONS" in response.upper():
            return []
        else:
            # Clean up response
            return [line for line in response.split('\n') if '-' in line or len(line) > 10]

mcp_server = MCPServer()
