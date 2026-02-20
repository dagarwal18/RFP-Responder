"""
Knowledge Base API routes.

Routes:
  POST /api/knowledge/upload  → Upload a company doc, auto-classify, embed + store
  GET  /api/knowledge/status  → Knowledge base stats
  POST /api/knowledge/query   → Test query against knowledge base
  POST /api/knowledge/seed    → Seed from JSON files
  GET  /api/knowledge/files   → List all uploaded KB documents
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from pydantic import BaseModel

from rfp_automation.config import get_settings
from rfp_automation.services.parsing_service import ParsingService
from rfp_automation.services.policy_extraction_service import PolicyExtractionService

logger = logging.getLogger(__name__)

knowledge_router = APIRouter()

# ── In-memory uploaded files registry ────────────────────
_kb_files: list[dict[str, Any]] = []


# ── Response schemas ─────────────────────────────────────

class KBUploadResponse(BaseModel):
    doc_id: str
    doc_type: str
    auto_classified: bool
    filename: str
    chunks_stored: int
    policies_extracted: int = 0
    message: str


class KBFileEntry(BaseModel):
    doc_id: str
    filename: str
    doc_type: str
    auto_classified: bool
    chunks_stored: int
    uploaded_at: str


class KBStatusResponse(BaseModel):
    pinecone: dict[str, Any]
    mongodb: dict[str, Any]


class KBQueryRequest(BaseModel):
    query: str
    top_k: int = 5
    doc_type: str = ""  # empty = search all


class KBQueryResponse(BaseModel):
    results: list[dict[str, Any]]


class KBSeedResponse(BaseModel):
    results: dict[str, Any]
    message: str


# ── Auto-classification logic ────────────────────────────

DOC_TYPES = ["capability", "past_proposal", "certification", "pricing", "legal"]

# Keyword lists for rule-based classification
_CLASSIFICATION_PATTERNS: dict[str, list[str]] = {
    "certification": [
        r"\bISO[\s-]?\d{4,5}", r"\bSOC[\s-]?[12]", r"\bGDPR\b", r"\bHIPAA\b",
        r"\bcertif", r"\baccredit", r"\bcompliance\b", r"\baudit\b",
        r"\bCMMI\b", r"\bPCI[\s-]DSS\b", r"\bFedRAMP\b",
    ],
    "pricing": [
        r"\bpric(?:e|ing)\b", r"\bcost\b", r"\brate\s*card\b", r"\btariff\b",
        r"\bquot(?:e|ation)\b", r"\bmargin\b", r"\bdiscount\b", r"\bSLA\b",
        r"\bbilling\b", r"\binvoic", r"\bfee\s*schedule\b",
    ],
    "legal": [
        r"\bindemnif", r"\bliabilit", r"\bwarrant", r"\btermination\b",
        r"\bconfidential", r"\bnon[\s-]?disclosure\b", r"\bNDA\b",
        r"\bcontract\b", r"\bclause\b", r"\bgoverning\s+law\b",
        r"\bdispute\s+resolution\b", r"\bforce\s+majeure\b",
    ],
    "past_proposal": [
        r"\bproposal\b", r"\bexecutive\s+summary\b", r"\bscope\s+of\s+work\b",
        r"\bsolution\s+overview\b", r"\bdeliverables?\b", r"\bproject\s+plan\b",
        r"\bwork\s*plan\b", r"\btechnical\s+approach\b", r"\bwin\b",
    ],
}


def classify_document(texts: list[str]) -> str:
    """
    Auto-classify a document into one of the DOC_TYPES based on keyword
    frequency in the extracted text.  Falls back to 'capability'.
    """
    combined = " ".join(texts[:50]).lower()  # first 50 blocks
    scores: dict[str, int] = {k: 0 for k in _CLASSIFICATION_PATTERNS}

    for doc_type, patterns in _CLASSIFICATION_PATTERNS.items():
        for pat in patterns:
            matches = re.findall(pat, combined, re.IGNORECASE)
            scores[doc_type] += len(matches)

    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    if scores[best] >= 3:
        return best
    return "capability"  # default


# ── Sync helper — runs in thread pool via to_thread() ────

def _sync_upload_process(
    local_path: str,
    filename: str,
    doc_id: str,
    doc_type: Optional[str],
) -> KBUploadResponse:
    """CPU/IO-heavy work: parse PDF → classify → embed → store.  Runs off the event loop."""
    try:
        # Parse document
        blocks = ParsingService.parse_pdf_blocks(local_path)
        if not blocks:
            raise ValueError("No text blocks extracted")
    except Exception as e:
        raise RuntimeError(f"Failed to parse document: {e}")

    # Build text + metadata for embedding
    texts: list[str] = []
    metadatas: list[dict[str, Any]] = []
    for i, block in enumerate(blocks):
        if block["type"] == "table_mock":
            continue
        text = block["text"].strip()
        if len(text) < 20:
            continue
        texts.append(text)
        metadatas.append({
            "id": f"{doc_id}_block_{i:04d}",
            "source_file": filename,
            "page_number": block.get("page_number", 0),
            "block_type": block["type"],
        })

    if not texts:
        raise RuntimeError("No usable text blocks found")

    # Auto-classify if not provided
    auto_classified = False
    if not doc_type or doc_type.strip() not in DOC_TYPES:
        doc_type = classify_document(texts)
        auto_classified = True
        logger.info(f"[KB] Auto-classified {filename} as '{doc_type}'")
    else:
        doc_type = doc_type.strip()

    # Store in Pinecone via MCPService
    from rfp_automation.mcp import MCPService
    mcp = MCPService()

    chunks_stored = mcp.ingest_knowledge_doc(
        doc_type=doc_type,
        texts=texts,
        metadatas=metadatas,
    )

    # Extract policies/rules from the document via LLM
    extractor = PolicyExtractionService()
    new_policies = extractor.extract_and_persist(
        doc_id=doc_id,
        doc_type=doc_type,
        texts=texts,
        filename=filename,
    )
    policies_count = len(new_policies)

    return KBUploadResponse(
        doc_id=doc_id,
        doc_type=doc_type,
        auto_classified=auto_classified,
        filename=filename,
        chunks_stored=chunks_stored,
        policies_extracted=policies_count,
        message=f"Stored {chunks_stored} chunks as '{doc_type}' from {filename}. Extracted {policies_count} policies.",
    )


# ── Upload company document ─────────────────────────────

@knowledge_router.post("/upload", response_model=KBUploadResponse)
async def upload_knowledge_doc(
    file: UploadFile = File(...),
    doc_type: Optional[str] = Form(None),
):
    """
    Upload a company document to the knowledge base.

    Heavy work (parse, embed, store) runs in a thread pool so the
    event loop stays responsive — WebSocket, health, and other
    requests remain unblocked.
    """
    # Validate file type
    filename = file.filename or "unknown.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Save file temporarily for parsing
    doc_id = f"KB-{uuid.uuid4().hex[:8].upper()}"
    save_dir = "./storage/knowledge"
    os.makedirs(save_dir, exist_ok=True)
    local_path = os.path.join(save_dir, f"{doc_id}_{filename}")

    file_bytes = await file.read()
    with open(local_path, "wb") as f:
        f.write(file_bytes)

    logger.info(f"[KB] Saved {filename} → {local_path}")

    try:
        result = await asyncio.to_thread(
            _sync_upload_process, local_path, filename, doc_id, doc_type,
        )

        # Register in uploaded files list
        _kb_files.append({
            "doc_id": result.doc_id,
            "filename": result.filename,
            "doc_type": result.doc_type,
            "auto_classified": result.auto_classified,
            "chunks_stored": result.chunks_stored,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        })

        return result

    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        # Always clean up the temp file after parsing + embedding
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
                logger.info(f"[KB] Cleaned up temp file: {local_path}")
        except OSError as e:
            logger.warning(f"[KB] Failed to clean up {local_path}: {e}")


# ── Policy CRUD Endpoints ────────────────────────────────


class PolicyInput(BaseModel):
    policy_text: str
    category: str = "capability"
    rule_type: str = "requirement"
    severity: str = "medium"
    source_section: str = ""


class PolicyUpdateInput(BaseModel):
    policy_text: str | None = None
    category: str | None = None
    rule_type: str | None = None
    severity: str | None = None
    source_section: str | None = None


@knowledge_router.get("/policies")
async def list_policies(category: str = ""):
    """List all extracted policies, optionally filtered by category."""
    policies = PolicyExtractionService.get_all_policies()
    if category:
        policies = [p for p in policies if p.get("category") == category]
    return policies


@knowledge_router.post("/policies")
async def add_policy(body: PolicyInput):
    """Manually add a new policy."""
    policy = PolicyExtractionService.add_policy(body.model_dump())
    return {"message": "Policy added", "policy": policy}


@knowledge_router.put("/policies/{policy_id}")
async def update_policy(policy_id: str, body: PolicyUpdateInput):
    """Update an existing policy."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    result = PolicyExtractionService.update_policy(policy_id, updates)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")
    return {"message": "Policy updated", "policy": result}


@knowledge_router.delete("/policies/{policy_id}")
async def delete_policy(policy_id: str):
    """Delete a policy."""
    if not PolicyExtractionService.delete_policy(policy_id):
        raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")
    return {"message": f"Policy {policy_id} deleted"}


@knowledge_router.delete("/policies")
async def delete_all_policies():
    """Delete all extracted policies."""
    count = len(PolicyExtractionService.get_all_policies())
    PolicyExtractionService._save_policies_static([])
    logger.info(f"[KB] Deleted all {count} policies")
    return {"message": f"Deleted all {count} policies", "deleted_count": count}


# ── Knowledge base status ───────────────────────────────

@knowledge_router.get("/status", response_model=KBStatusResponse)
async def knowledge_status():
    """Return knowledge base statistics (runs off event loop)."""
    def _sync():
        from rfp_automation.mcp import MCPService
        return MCPService().get_knowledge_stats()

    stats = await asyncio.to_thread(_sync)
    return KBStatusResponse(**stats)


# ── Query knowledge base ────────────────────────────────

@knowledge_router.post("/query", response_model=KBQueryResponse)
async def query_knowledge(body: KBQueryRequest):
    """
    Test query against the knowledge base (runs off event loop).
    If doc_type is provided, filters by that type; otherwise searches all.
    """
    def _sync():
        from rfp_automation.mcp import MCPService
        mcp = MCPService()
        if body.doc_type and body.doc_type in DOC_TYPES:
            return mcp.query_knowledge(body.query, body.top_k, doc_type=body.doc_type)
        return mcp.query_knowledge(body.query, body.top_k)

    results = await asyncio.to_thread(_sync)
    return KBQueryResponse(results=results)


# ── Seed from JSON files ────────────────────────────────

@knowledge_router.post("/seed", response_model=KBSeedResponse)
async def seed_knowledge():
    """Seed knowledge base from JSON files (runs off event loop)."""
    def _sync():
        from rfp_automation.mcp.knowledge_loader import seed_all
        return seed_all()

    try:
        results = await asyncio.to_thread(_sync)
        return KBSeedResponse(
            results=results,
            message="Knowledge base seeded successfully",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Seed failed: {e}")


# ── List uploaded KB files ───────────────────────────────

@knowledge_router.get("/files", response_model=list[KBFileEntry])
async def list_kb_files():
    """Return list of all uploaded KB documents with their classified types."""
    return [
        KBFileEntry(**entry)
        for entry in reversed(_kb_files)  # newest first
    ]
