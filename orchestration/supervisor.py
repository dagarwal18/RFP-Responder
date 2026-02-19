import uuid
from typing import Any, Dict, List, Optional
from agents.workers.extractor import extract_requirements
from agents.workers.cbr_adaptor import adapt_with_cbr
from agents.workers.validator import validate_requirement
from persistence.state_repo import StateRepo
from services import export_service

class Supervisor:
    def __init__(self):
        self.repo = StateRepo()

    async def handle_upload(self, filename: str, content: bytes) -> str:
        job_id = str(uuid.uuid4())
        reqs = await extract_requirements(filename, content)
        await self.repo.save_requirements(job_id, reqs)
        for r in reqs:
            draft = await adapt_with_cbr(r)
            validation = await validate_requirement(draft, r)
            await self.repo.update_requirement(job_id, r["id"], {"draft": draft, "validation": validation})
        return job_id

    # New helper endpoints
    async def get_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = await self.repo.get_job(job_id)
        if not job:
            return None
        reqs = job.get("requirements", [])
        # simple status: processing if any requirement missing validation, else done
        processing = any("validation" not in r for r in reqs)
        return {"rfp_id": job["rfp_id"], "processing": processing, "requirement_count": len(reqs), "synthesized_url": job.get("synthesized_url")}

    async def get_requirements(self, job_id: str) -> Optional[List[Dict[str, Any]]]:
        job = await self.repo.get_job(job_id)
        if not job:
            return None
        return job.get("requirements", [])

    async def get_requirement(self, job_id: str, req_id: str) -> Optional[Dict[str, Any]]:
        return await self.repo.get_requirement(job_id, req_id)

    async def rebuild_requirement(self, job_id: str, req_id: str) -> Optional[Dict[str, Any]]:
        req = await self.repo.get_requirement(job_id, req_id)
        if not req:
            return None
        draft = await adapt_with_cbr(req)
        validation = await validate_requirement(draft, req)
        await self.repo.update_requirement(job_id, req_id, {"draft": draft, "validation": validation})
        # return updated requirement
        return await self.repo.get_requirement(job_id, req_id)

    async def synthesize(self, job_id: str) -> Optional[str]:
        job = await self.repo.get_job(job_id)
        if not job:
            return None
        requirements = job.get("requirements", [])
        # call export service (creates file and returns url/path)
        url = export_service.synthesize_document(requirements, job_id)
        await self.repo.set_synthesized_url(job_id, url)
        return url
