from fastapi import FastAPI, UploadFile, File, HTTPException
from orchestration.supervisor import Supervisor
from mcp.reasoning.logic_rules import RULES
from pydantic import BaseModel
from services.llm_client import set_llm_api_key, get_llm_api_key

app = FastAPI(title="RFP Responder - Scaffold")
supervisor = Supervisor()

@app.post("/ingest")
async def ingest(file: UploadFile = File(...)):
    content = await file.read()
    job_id = await supervisor.handle_upload(file.filename, content)
    return {"job_id": job_id}

@app.get("/health")
def health():
    return {"status": "ok"}

# New endpoints
@app.get("/status/{job_id}")
async def status(job_id: str):
    st = await supervisor.get_status(job_id)
    if st is None:
        raise HTTPException(status_code=404, detail="job not found")
    return st

@app.get("/requirements/{job_id}")
async def list_requirements(job_id: str):
    reqs = await supervisor.get_requirements(job_id)
    if reqs is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {"requirements": reqs}

@app.get("/requirement/{job_id}/{req_id}")
async def get_requirement(job_id: str, req_id: str):
    req = await supervisor.get_requirement(job_id, req_id)
    if req is None:
        raise HTTPException(status_code=404, detail="requirement not found")
    return req

@app.post("/requirement/{job_id}/{req_id}/rebuild")
async def rebuild_requirement(job_id: str, req_id: str):
    updated = await supervisor.rebuild_requirement(job_id, req_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="requirement or job not found")
    return {"updated_requirement": updated}

@app.post("/synthesize/{job_id}")
async def synthesize(job_id: str):
    url = await supervisor.synthesize(job_id)
    if url is None:
        raise HTTPException(status_code=404, detail="job not found or synthesis failed")
    return {"synthesized_url": url}

@app.get("/rules")
def list_rules():
    return {"rules": RULES}

class LLMKeyPayload(BaseModel):
    provider: str
    api_key: str

@app.post("/secrets/llm")
async def set_llm_key(payload: LLMKeyPayload):
    """
    Store an LLM API key for a provider securely (encrypted in Mongo using MASTER_KEY).
    - provider: e.g. "openai"
    - api_key: raw API key (will be encrypted)
    """
    try:
        await set_llm_api_key(payload.provider, payload.api_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "stored", "provider": payload.provider}

@app.get("/secrets/llm/{provider}")
async def llm_key_status(provider: str):
    """
    Return whether an API key exists for provider and a masked preview.
    Does NOT return the actual key.
    """
    k = await get_llm_api_key(provider)
    if not k:
        raise HTTPException(status_code=404, detail="key not found")
    masked = ("*" * max(0, len(k)-4)) + k[-4:]
    return {"provider": provider, "masked_key": masked}
