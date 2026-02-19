from mcp.reasoning import cbr_engine, logic_rules, knowledge_graph

class MCPServer:
    def __init__(self):
        pass

    async def find_similar(self, text):
        return await cbr_engine.find_similar_cases(text)

    def check_logic(self, draft, requirement):
        return logic_rules.check_rules(draft, requirement)

    def query_facts(self, entity):
        return knowledge_graph.query_facts(entity)
