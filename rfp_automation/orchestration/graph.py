from langgraph.graph import StateGraph
from rfp_automation.models.state import RFPState
# Import agents

def build_graph():
    workflow = StateGraph(RFPState)
    # Add nodes and edges
    return workflow.compile()
