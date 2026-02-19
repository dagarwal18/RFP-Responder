from fastapi import APIRouter, BackgroundTasks, WebSocket, WebSocketDisconnect
from rfp_automation.models.state import RFPState
from rfp_automation.orchestration.runner import pipeline_runner
import uuid

router = APIRouter()

@router.get("/health")
async def health_check():
    return {"status": "ok"}

from fastapi import UploadFile, File

@router.post("/api/rfp/upload")
async def upload_rfp(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    rfp_id = str(uuid.uuid4())[:8]
    
    # Read file content
    content = await file.read()
    text = content.decode("utf-8", errors="ignore")
    
    # If file is empty or too short, use dummy for robustness (optional, but good for demo)
    if len(text) < 10:
         text = "Uploaded file was empty. Using dummy context: Secure cloud migration required."

    # Start in background
    background_tasks.add_task(pipeline_runner.run_pipeline, rfp_id, text)
    
    return {"rfp_id": rfp_id, "message": "File uploaded and pipeline started"}

@router.websocket("/ws/{rfp_id}")
async def websocket_endpoint(websocket: WebSocket, rfp_id: str):
    await pipeline_runner.connect(rfp_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pipeline_runner.disconnect(rfp_id, websocket)
