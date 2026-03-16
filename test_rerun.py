import asyncio
import sys
import logging
import json
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.enums import HumanValidationDecision
from rfp_automation.models.schemas import ReviewPackage, HumanValidationDecisionRecord
from rfp_automation.orchestration.graph import run_pipeline_from

logging.basicConfig(level=logging.INFO)

# Create a mock state matching the end of h1_human_validation_prepare
state = RFPGraphState()
state.tracking_rfp_id = "TEST-RFP-123"

# Mock the review package explicitly as Approved
review_package = ReviewPackage()
review_package.decision = HumanValidationDecisionRecord(decision=HumanValidationDecision.APPROVE)
# Must have some content or else F1 crashes? F1 uses: state.assembled_proposal.executive_summary
state.assembled_proposal.executive_summary = "Exec summary test"
state.commercial_result.currency = "USD"
state.commercial_result.total_price = 1000

# Convert to dict, same as checkpoint
checkpoint_state = state.model_dump(mode="json")
checkpoint_state["review_package"] = review_package.model_dump(mode="json")

print("Starting resume from f1_final_readiness")
try:
    result = run_pipeline_from("f1_final_readiness", checkpoint_state)
    print("Success. Final state:", result.get("status"))
except Exception as e:
    print("Failed!")
    import traceback
    traceback.print_exc()

