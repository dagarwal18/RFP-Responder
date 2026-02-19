"""Wired demo that attempts to use repository modules with safe fallbacks.

Run with: python demo/wired_demo.py

The script will try to call:
- `agents.workers.extractor.extract_requirements`
- `agents.workers.cbr_adaptor.adapt_with_cbr`
- `agents.workers.validator.validate_requirement`
- `persistence.state_repo.StateRepo.save_requirements`
- `services.export_service.synthesize_document`

If any import or runtime call fails (e.g., no MongoDB), the demo falls back
to local in-memory or file-based behavior so it remains runnable.
"""
import asyncio
import json
import os
import traceback
from typing import List, Dict, Any


SAMPLE_TEXT = (
    "Vendor X offers cloud hosting with 99.9% SLA. "
    "They perform annual security audits and provide SOC2 reports on request."
)


async def run() -> None:
    print("--- Wired demo starting ---")
    # Attempt to import repository modules
    try:
        from agents.workers.extractor import extract_requirements
        from agents.workers.cbr_adaptor import adapt_with_cbr
        from agents.workers.validator import validate_requirement
        from persistence.state_repo import StateRepo
        from services import export_service
        repo_available = True
        print("Using repository worker modules where available.")
    except Exception:
        extract_requirements = None
        adapt_with_cbr = None
        validate_requirement = None
        StateRepo = None
        export_service = None
        repo_available = False
        print("Repository modules not fully available; falling back to stubs.")

    filename = "sample_rfp.txt"
    content = SAMPLE_TEXT.encode("utf-8")

    # Extraction
    if extract_requirements:
        try:
            requirements = await extract_requirements(filename, content)
        except Exception:
            traceback.print_exc()
            requirements = []
    else:
        # fallback: create a simple requirement
        requirements = [{
            "id": "sample_rfp-REQ-1",
            "title": "Provide hosting SLA",
            "description": "Vendor must provide hosting with uptime and audits.",
            "evidence": {"page": 1, "text": SAMPLE_TEXT[:200], "paragraph_index": 0}
        }]

    print(f"Extracted {len(requirements)} requirement(s)")

    # Adapt (CBR) and Validate per requirement
    for req in requirements:
        # adapt
        if adapt_with_cbr:
            try:
                draft = await adapt_with_cbr(req)
            except Exception:
                traceback.print_exc()
                draft = "(adaptation-failed) Proposed: see evidence."
        else:
            draft = "Proposed response: We confirm the requirement as described."
        req["draft"] = draft

        # validate
        if validate_requirement:
            try:
                validation = await validate_requirement(draft, req)
            except Exception:
                traceback.print_exc()
                validation = {"logic_status": "FAILED", "violations": [{"type": "ERROR", "message": "validation error"}]}
        else:
            validation = {"logic_status": "PASSED", "violations": []}
        req["validation"] = validation

    rfp_id = "demo-rfp-1"

    # Persistence: try to save to StateRepo, otherwise write JSON locally
    persisted_path = None
    try:
        if StateRepo:
            repo = StateRepo()
            await repo.save_requirements(rfp_id, requirements)
            persisted_path = f"(mongodb) saved under rfp_id={rfp_id}"
        else:
            raise RuntimeError("StateRepo not available")
    except Exception:
        # fallback to local JSON file
        local_path = os.path.join(os.getcwd(), f"wired_demo_output_{rfp_id}.json")
        with open(local_path, "w", encoding="utf-8") as f:
            json.dump({"rfp_id": rfp_id, "requirements": requirements}, f, indent=2)
        persisted_path = local_path

    print("Persistence result:", persisted_path)

    # Export / synthesize document
    synth_path = None
    try:
        if export_service and hasattr(export_service, "synthesize_document"):
            # synthesize_document is sync in services/export_service.py
            synth_path = export_service.synthesize_document(requirements, rfp_id)
        else:
            raise RuntimeError("export_service.synthesize_document unavailable")
    except Exception:
        # fallback: write a plain text summary
        synth_path = os.path.join(os.getcwd(), f"rfp_response_{rfp_id}.txt")
        with open(synth_path, "w", encoding="utf-8") as f:
            for r in requirements:
                f.write(f"ID: {r.get('id')}\nTitle: {r.get('title')}\nDraft: {r.get('draft')}\n\n")

    print("Synthesized document:", synth_path)
    print("--- Wired demo complete ---")


if __name__ == "__main__":
    asyncio.run(run())
