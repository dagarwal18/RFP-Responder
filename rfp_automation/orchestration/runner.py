import asyncio
from typing import Dict, List, Any
from rfp_automation.orchestration.graph import build_graph
from rfp_automation.models.state import RFPState, AgentStatus
from fastapi import WebSocket

class PipelineRunner:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.graph = build_graph()

    async def connect(self, rfp_id: str, websocket: WebSocket):
        await websocket.accept()
        if rfp_id not in self.active_connections:
            self.active_connections[rfp_id] = []
        self.active_connections[rfp_id].append(websocket)
        print(f"WS Connected: {rfp_id}")

    def disconnect(self, rfp_id: str, websocket: WebSocket):
        if rfp_id in self.active_connections:
            self.active_connections[rfp_id].remove(websocket)

    async def broadcast(self, rfp_id: str, message: Dict[str, Any]):
        if rfp_id in self.active_connections:
            for connection in self.active_connections[rfp_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    print(f"WS Broadcast Error: {e}")

    async def run_pipeline(self, rfp_id: str, initial_text: str):
        print(f"Starting pipeline for {rfp_id}...")
        
        state = RFPState(raw_text=initial_text)
        state.rfp_id = rfp_id # Ensure ID matches
        
        # We need to hook into the graph execution to stream updates.
        # LangGraph doesn't have a native "per-node" callback that's easy to hook into 
        # without using LangSmith or complex listeners in this version.
        # FOR DEMO: We will wrap the runner and broadcast state after the full run (simple)
        # OR better: The agents themselves log to console.
        # To get REAL-TIME updates in the UI, we'd ideally modify the agents to call a webhook or 
        # pass the runner injection. 
        # simplified approach: Just run it and broadcast the FINAL result for now OR
        # Broadcast "heartbeats" if possible. 
        
        # ACTUALLY, sticking to the plan: "Watch the 12 agents execute".
        # To do this without rewriting every agent to accept a websocket broadcaster:
        # We can use a custom callback handler if using LangChain, but these act as functions.
        #
        # Hack for visualization: We will rely on the `logs` field in the state. 
        # IF we want real-time steps, we need `graph.stream`.
        
        app = self.graph
        
        latest_state = None
        
        # Stream events!
        # The 'stream' method yields output as nodes complete.
        async for output in app.astream(state):
            # output is a dict like {'node_name': updated_state}
            for node_name, updated_state_dict in output.items():
                
                # In Pydantic V2/LangGraph, the state might be a dict or object.
                # We handle both safely.
                state_data = updated_state_dict
                if hasattr(updated_state_dict, "model_dump"):
                    state_data = updated_state_dict.model_dump(mode='json')
                elif hasattr(updated_state_dict, "dict"):
                    state_data = updated_state_dict.dict()
                
                latest_state = state_data
                
                # Get the latest log entry to send to UI
                logs = state_data.get("logs", [])
                latest_log = logs[-1] if logs else f"{node_name} completed."
                
                # Structure for UI
                msg = {
                    "type": "update",
                    "node": node_name,
                    "log": latest_log,
                    "state": state_data
                }
                
                print(f"Broadcasting update for {node_name}")
                await self.broadcast(rfp_id, msg)
                    
                # Small sleep to make it visible to human eye
                await asyncio.sleep(0.5)

        # Broadcast completion with final state content
        final_payload = {
            "type": "complete", 
            "status": "DONE",
            "rfp_id": rfp_id,
        }
        
        if latest_state:
            # Construct a summary or pass the full text
            # Assuming 'full_proposal_text' or 'section_responses' is populated
            final_payload["proposal_text"] = latest_state.get("full_proposal_text", "No proposal text generated.")
            final_payload["gonogo"] = latest_state.get("gonogo_decision", "UNKNOWN")
            
        await self.broadcast(rfp_id, final_payload)

pipeline_runner = PipelineRunner()
