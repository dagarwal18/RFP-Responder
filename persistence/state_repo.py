from persistence.mongo_client import get_db
from typing import List, Dict, Optional

class StateRepo:
    def __init__(self):
        self.db = get_db()
        self.collection = self.db["requirement_matrices"]

    async def save_requirements(self, rfp_id: str, requirements: List[Dict]):
        doc = {"rfp_id": rfp_id, "requirements": requirements}
        self.collection.insert_one(doc)

    async def update_requirement(self, rfp_id: str, req_id: str, update_fields: Dict):
        set_map = {f"requirements.$.{k}": v for k, v in update_fields.items()}
        self.collection.update_one({"rfp_id": rfp_id, "requirements.id": req_id}, {"$set": set_map})

    # New retrieval helpers
    async def get_job(self, rfp_id: str) -> Optional[Dict]:
        return self.collection.find_one({"rfp_id": rfp_id})

    async def get_requirement(self, rfp_id: str, req_id: str) -> Optional[Dict]:
        doc = self.collection.find_one({"rfp_id": rfp_id, "requirements.id": req_id}, {"requirements.$": 1})
        if not doc:
            return None
        reqs = doc.get("requirements", [])
        return reqs[0] if reqs else None

    async def set_synthesized_url(self, rfp_id: str, url: str):
        self.collection.update_one({"rfp_id": rfp_id}, {"$set": {"synthesized_url": url}})
