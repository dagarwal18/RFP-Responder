from langgraph.graph import StateGraph, END
from rfp_automation.models.state import RFPState
from rfp_automation.models.enums import GoNoGoDecision, ValidationStatus, LegalStatus

# Import Agents
from rfp_automation.agents.intake_agent import IntakeAgent
from rfp_automation.agents.structuring_agent import StructuringAgent
from rfp_automation.agents.go_no_go_agent import GoNoGoAgent
from rfp_automation.agents.requirement_extraction_agent import RequirementExtractionAgent
from rfp_automation.agents.requirement_validation_agent import RequirementValidationAgent
from rfp_automation.agents.architecture_agent import ArchitectureAgent
from rfp_automation.agents.writing_agent import WritingAgent
from rfp_automation.agents.narrative_agent import NarrativeAgent
from rfp_automation.agents.technical_validation_agent import TechnicalValidationAgent
from rfp_automation.agents.commercial_agent import CommercialAgent
from rfp_automation.agents.legal_agent import LegalAgent
from rfp_automation.agents.final_readiness_agent import FinalReadinessAgent
from rfp_automation.agents.submission_agent import SubmissionAgent

# Instantiate Agents
a1 = IntakeAgent()
a2 = StructuringAgent()
a3 = GoNoGoAgent()
b1 = RequirementExtractionAgent()
b2 = RequirementValidationAgent()
c1 = ArchitectureAgent()
c2 = WritingAgent()
c3 = NarrativeAgent()
d1 = TechnicalValidationAgent()
e1 = CommercialAgent()
e2 = LegalAgent()
f1 = FinalReadinessAgent()
f2 = SubmissionAgent()

def decision_gonogo(state: RFPState):
    if state.gonogo_decision == GoNoGoDecision.NO_GO:
        return "end"
    return "extract"

def decision_validation(state: RFPState):
    if state.validation_status == ValidationStatus.REJECT and state.retry_count <= 3:
        return "retry"
    return "pass"

def decision_legal_block(state: RFPState):
    if state.legal_status == LegalStatus.BLOCKED:
        return "block"
    return "proceed"

def build_graph():
    workflow = StateGraph(RFPState)

    # Add Nodes
    workflow.add_node("intake", a1.run)
    workflow.add_node("structuring", a2.run)
    workflow.add_node("gonogo", a3.run)
    workflow.add_node("req_extraction", b1.run)
    workflow.add_node("req_validation", b2.run)
    workflow.add_node("architecture", c1.run)
    workflow.add_node("writing", c2.run)
    workflow.add_node("narrative", c3.run)
    workflow.add_node("tech_validation", d1.run)
    workflow.add_node("commercial", e1.run)
    workflow.add_node("legal", e2.run)
    workflow.add_node("final_readiness", f1.run)
    workflow.add_node("submission", f2.run)

    # Add Edges
    workflow.set_entry_point("intake")
    workflow.add_edge("intake", "structuring")
    workflow.add_edge("structuring", "gonogo")
    
    # Conditional: Go/No-Go
    workflow.add_conditional_edges(
        "gonogo",
        decision_gonogo,
        {
            "end": END,
            "extract": "req_extraction"
        }
    )

    workflow.add_edge("req_extraction", "req_validation")
    workflow.add_edge("req_validation", "architecture")
    workflow.add_edge("architecture", "writing")
    workflow.add_edge("writing", "narrative")
    workflow.add_edge("narrative", "tech_validation")

    # Conditional: Technical Validation Loop
    workflow.add_conditional_edges(
        "tech_validation",
        decision_validation,
        {
            "retry": "narrative", # Simplified loop back to narrative (can be C3 or C2 depending on logic)
            "pass": "commercial" # Start E1 (E2 run in parallel typically, but sequential here for simplicity of graph)
        }
    )

    # For strict parallel execution, LangGraph supports it, but simple updated sequential E1->E2 is safer for now
    workflow.add_edge("commercial", "legal")

    # Conditional: Legal Block
    workflow.add_conditional_edges(
        "legal",
        decision_legal_block,
        {
            "block": END,
            "proceed": "final_readiness"
        }
    )

    workflow.add_edge("final_readiness", "submission")
    workflow.add_edge("submission", END)

    return workflow.compile()
