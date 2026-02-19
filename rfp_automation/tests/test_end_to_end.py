import sys
import os
import asyncio

# Ensure project root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rfp_automation.orchestration.graph import build_graph
from rfp_automation.models.state import RFPState

async def run_test():
    print("Building Graph...")
    app = build_graph()
    
    print("Initializing State...")
    initial_state = RFPState()
    
    print("Running Pipeline...")
    # LangGraph app.invoke returns the final state
    result = await app.ainvoke(initial_state)
    
    print("\n--- Pipeline Finished ---")
    print(f"Final RFP ID: {result.get('rfp_id')}")
    print(f"Go/No-Go: {result.get('gonogo_decision')}")
    print(f"Status: {result.get('status')}")
    print(f"Logs: {len(result.get('logs'))} entries")
    
    if result.get("status") == "SUBMITTED":
        print("\n✅ SUCCESS: Pipeline reached SUBMITTED state.")
    else:
        print(f"\n❌ FAILURE: Pipeline ended with status {result.get('status')}")

if __name__ == "__main__":
    asyncio.run(run_test())
