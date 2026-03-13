# RFP Response Automation — Implementation Plan

> **Last Updated:** 2026-03-13
> **Current Progress:** 10 of 13 agents fully implemented (A1–D1), pipeline runs through D1 with stubs for E1–F2

---

## Implementation Status

| Agent | Status | Key Implementation Details |
|---|---|---|
| A1 IntakeAgent | ✅ Done | PDF parsing, HuggingFace VLM table extraction (`vision_service.py`), Pinecone embedding, regex metadata |
| A2 StructuringAgent | ✅ Done | LLM section classification (6 categories), confidence scoring, retry loop (max 3) |
| A3 GoNoGoAgent | ✅ Done | LLM risk analysis + MCP policy rules, requirement-to-policy mapping table, NO_GO bypass (continues pipeline) |
| B1 RequirementsExtractionAgent | ✅ Done | Two-layer extraction (`obligation_detector.py` + LLM), 3-tier embedding dedup, temp=0/seed=42, JSON repair for truncated output |
| B2 RequirementsValidationAgent | ✅ Done | Grounded refinement with hallucination guards, Llama model with 50K/80K char limits |
| C1 ArchitecturePlanningAgent | ✅ Done | LLM section design + programmatic gap-fill + auto-split (max 20 reqs/section) |
| C2 RequirementWritingAgent | ✅ Done | Per-section prose, Llama token budgeting (~25K input budget), RFP metadata injection, 3-tier coverage matrix, JSON repair |
| C3 NarrativeAssemblyAgent | ✅ Done | LLM exec summary + transitions, split-section reassembly, coverage appendix, placeholder detection |
| D1 TechnicalValidationAgent | ✅ Done | Single-call/multi-pass validation, 4 checks (completeness/alignment/realism/consistency), Llama 4 Scout budgets |
| E1 CommercialAgent | ⬜ Stub | `NotImplementedError` |
| E2 LegalAgent | ⬜ Stub | `NotImplementedError` |
| F1 FinalReadinessAgent | ⬜ Stub | `NotImplementedError` |
| F2 SubmissionAgent | ⬜ Stub | `NotImplementedError` |

### Infrastructure — Completed ✅

| Component | File(s) | Notes |
|---|---|---|
| State models | `models/enums.py`, `schemas.py`, `state.py` | 20+ Pydantic v2 models, `PipelineStatus` enum |
| Orchestration | `orchestration/graph.py`, `transitions.py` | 17-node LangGraph, 5 conditional edges, `run_pipeline()` + `run_pipeline_from()`, Go/No-Go bypass |
| MCP Server | `mcp/mcp_server.py` + vector_store + rules | Pinecone + MongoDB + BM25 + 4 rule layers + rules_config |
| KB Seed Data | `mcp/knowledge_data/` | 6 JSON files (capabilities, certs, pricing, legal, proposals, policies) |
| KB Loader | `mcp/knowledge_loader.py` | `seed_all()` function to bootstrap KB |
| API | `api/routes.py`, `knowledge_routes.py` | REST + WebSocket + CORS + document caching + checkpoint/rerun |
| Frontend | `frontend/index.html` | Vanilla JS dashboard: upload, status, agent output renderers, KB management, policy CRUD |
| Services | `services/` | 10 service files: LLM, vision, parsing, obligation detection, cross-ref, section store, policy extraction, file, storage, audit |
| Persistence | `persistence/` | MongoDB client, state repo (in-memory), JSON checkpoints per agent |
| Tests | `tests/` | 8 test files covering agents, pipeline, rules, API, extraction, obligation detection, quality fixes |
| Prompts | `prompts/` | 9 prompt templates (A2, A3, B1, B2, C1, C2, D1, E2, policy extraction) |
| Config | `config.py` + `.env` | Dual-model setup: Qwen3-32B (primary) + Llama 4 Scout (large context), secrets in `.env` |

### Dual-Model LLM Architecture

The system uses two Groq Cloud models based on agent context requirements:

| Model | Config Key | Context | TPM | Agents |
|---|---|---|---|---|
| `qwen/qwen3-32b` | `llm_model` | ~32K | 6K | B1, A2, A3, C1 (deterministic extraction/structuring) |
| `meta-llama/llama-4-scout-17b-16e-instruct` | `llm_large_model` | ~131K | 30K | C2, B2, D1, C3 (large-context writing/validation) |

Both share `max_tokens=8192` for output generation. Agents that process large inputs (full proposals, all requirements) use the Llama model via `llm_large_text_call()`. API key rotation (`groq_api_keys`) distributes calls across multiple keys.

---

## Recent Fixes (March 2026)

### Token Budget Corrections

Several agents had budget calculations based on `llm_max_tokens=8192` (an **output** limit), treating it as an input context limit. This caused severe data truncation:

| Agent | Issue | Fix |
|---|---|---|
| B1 | `MAX_CONTEXT_LEN` too small for Qwen's actual ~32K context | Increased to ~32K context, added `_repair_truncated_json_array()` for resilience |
| B2 | Requirements JSON truncated at 12K chars, RFP text at 15K | Raised to 50K/80K chars respectively to use Llama's capacity |
| C2 | Budget computed from 8192 output tokens instead of ~25K input budget | Recalculated using Llama's actual capacity (~100K chars), added JSON repair |
| D1 | Proposal and requirements truncated at small limits | `_SINGLE_CALL_MAX_CHARS=80K`, `_MAX_PROPOSAL_CHARS=100K`, `_MAX_REQUIREMENTS_CHARS=50K` |

### Go/No-Go Bypass

Modified `route_after_go_no_go()` in `transitions.py` to always route to `b1_requirements_extraction`, regardless of the decision. The `NO_GO` decision is preserved in `go_no_go_result` for frontend display but does not terminate the pipeline.

---

## Remaining Agents (E1–F2)

### E1 — Commercial Agent

**Purpose:** Generate pricing breakdown.

**Plan:**
1. Query MCP Knowledge Store for pricing rules (from `knowledge_data/pricing_rules.json`)
2. Analyze proposal scope and requirement counts by category
3. Apply pricing formula: base + (per-requirement × complexity) + risk margin
4. Generate payment terms, assumptions, exclusions
5. Uses `rules/commercial_rules.py` for margin validation

### E2 — Legal Agent

**Purpose:** Legal risk assessment with VETO authority.

**Plan:**
1. Query MCP RFP Store for contract clauses
2. Query MCP Knowledge Store for legal templates (from `knowledge_data/legal_templates.json`)
3. LLM classifies each clause: LOW / MEDIUM / HIGH / CRITICAL risk
4. Decision: APPROVED / CONDITIONAL / BLOCKED
5. BLOCKED → pipeline terminates via `rules/legal_rules.py` fan-in gate

### F1 — Final Readiness Agent

**Purpose:** Compile approval package for human review.

**Plan:**
1. Aggregate: proposal, pricing, legal risk register, coverage matrix
2. Generate one-page executive decision brief
3. Trigger human approval gate (auto-approve in mock mode)

### F2 — Submission & Archive Agent

**Purpose:** Finalize and archive deliverables.

**Plan:**
1. Apply final formatting to proposal
2. Package all deliverables
3. Compute SHA-256 hashes (`utils/hashing.py`) for auditability
4. Archive to storage
5. status → SUBMITTED

---

## Quality Metrics (Latest Run — March 2026)

| Metric | Value |
|---|---|
| Requirements extracted (B1) | 88 (from ~71 pre-fix) |
| Coverage quality (D1) | 90.9% full, 9.1% partial, 0% missing |
| D1 validation decision | PASS (0 critical failures, 0 warnings) |
| Pipeline completion time | ~7–8 minutes (A1→D1) |
| Assembled proposal word count | ~8,500 words across 13 sections |
| All 4 D1 checks | ✅ completeness, alignment, realism, consistency |

---

## Deployment

| Component | Current | Planned |
|---|---|---|
| Backend | Local dev (`uvicorn rfp_automation.api:app`) | Docker container on EC2 |
| Frontend | Served by FastAPI at `/` (vanilla JS) | Same (or separate deployment) |
| Vector DB | Pinecone Serverless (AWS us-east-1) | Same |
| Config DB | MongoDB local | MongoDB Atlas |
| Monitoring | Pipeline logs + WebSocket events | Same + structured logging |
