# RFP Response Automation System

## Overview

A multi-agent AI system that automates the end-to-end process of responding to Requests for Proposal (RFP). The system ingests an RFP document, extracts and classifies requirements, generates a tailored technical and commercial response, validates quality, performs legal review, and produces a submission-ready proposal — all orchestrated as a LangGraph state machine with built-in governance controls.

---

## Architecture

### Core Design Principles

- **MCP Server as Central Hub** — all agents retrieve context from the MCP server rather than passing raw data through state. Agents query, reason, and write outputs to shared graph state.
- **13-Stage Pipeline** — each stage is an independent agent with a single responsibility.
- **Governance Built In** — veto points (A3, E2), validation loops (D1→C3), and a human approval gate (F1) before submission.

### MCP Server Layers

The MCP server runs **in-process** as a Python module (not a separate service). Agents import `MCPService` and never touch internals.

| Layer | Module | Purpose |
|---|---|---|
| RFP Vector Store | `mcp/vector_store/rfp_store.py` | Chunked + embedded RFP content (Pinecone) |
| Knowledge Store | `mcp/vector_store/knowledge_store.py` | Company capabilities, proposals, certs (Pinecone + MongoDB) |
| BM25 Store | `mcp/vector_store/bm25_store.py` | BM25 keyword-based retrieval |
| Policy Rules | `mcp/rules/policy_rules.py` | Hard disqualification rules (A3) |
| Validation Rules | `mcp/rules/validation_rules.py` | Prohibited language checks (D1) |
| Commercial Rules | `mcp/rules/commercial_rules.py` | Pricing validation (E1) |
| Legal Rules | `mcp/rules/legal_rules.py` | Commercial+Legal gate logic (E1+E2) |
| Rules Config | `mcp/rules/rules_config.py` | Shared rules configuration |
| Knowledge Loader | `mcp/knowledge_loader.py` | Seeds KB from JSON files in `mcp/knowledge_data/` |
| Embeddings | `mcp/embeddings/embedding_model.py` | Sentence Transformers wrapper |

### Knowledge Data (Seed Files)

Located in `mcp/knowledge_data/`:
- `capabilities.json` — company product/service capabilities
- `certifications.json` — compliance certifications held
- `pricing_rules.json` — pricing parameters and formulas
- `legal_templates.json` — contract clause templates
- `past_proposals.json` — historical proposal examples
- `extracted_policies.json` — extracted company policies

---

## Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.10+ |
| LLM (Primary) | Groq Cloud (`qwen/qwen3-32b`) via `langchain-groq` — ~32K context, used by B1, A2, A3, C1 |
| LLM (Large) | Groq Cloud (`meta-llama/llama-4-scout-17b-16e-instruct`) — ~131K context, used by C2, B2, D1, C3 |
| VLM | HuggingFace / Novita (`Qwen/Qwen3-VL-8B-Instruct:novita`) for table extraction |
| Orchestration | LangGraph (state machine — 17 nodes, 5 conditional edges) |
| Vector DB | Pinecone Serverless (AWS us-east-1, cosine similarity) |
| Embeddings | Sentence Transformers (`all-MiniLM-L6-v2`, 384 dimensions) |
| Structured DB | MongoDB (company config, certifications, pricing, legal) |
| API | FastAPI + uvicorn (async, `to_thread` for heavy I/O) |
| Real-time | WebSocket via `PipelineProgress` singleton |
| Frontend | Single-page vanilla JS dashboard (served at `/`) |
| File Parsing | PyMuPDF (PDF), python-docx (DOCX) |
| State Models | Pydantic v2 |
| Configuration | pydantic-settings (`.env` for secrets only) |
| Testing | pytest |

---

## Project Structure

```
RFP-Responder/
├── Documentation/
│   ├── project-description.md           # This file — full system spec + agent descriptions
│   └── implementation-plan.md           # Current status + remaining work
│
├── rfp_automation/                      # ═══ BACKEND ═══
│   ├── __init__.py
│   ├── __main__.py                      # CLI entry: python -m rfp_automation
│   ├── config.py                        # Centralised config (pydantic-settings + .env)
│   ├── main.py                          # run() + serve() entry points
│   │
│   ├── api/                             # ── HTTP + WebSocket Layer ──
│   │   ├── __init__.py                  # FastAPI app factory + CORS + router wiring
│   │   ├── routes.py                    # RFP endpoints (upload, status, approve, list, rerun, checkpoints, WS)
│   │   ├── knowledge_routes.py          # KB endpoints (upload, status, query, seed, files, policy CRUD)
│   │   └── websocket.py                 # PipelineProgress singleton (real-time WS broadcast)
│   │
│   ├── agents/                          # ── 13 Agents ──
│   │   ├── base_agent.py                # BaseAgent — _real_process(), audit, WS events
│   │   ├── intake_agent.py              # A1 — IntakeAgent ✅
│   │   ├── structuring_agent.py         # A2 — StructuringAgent ✅
│   │   ├── go_no_go_agent.py            # A3 — GoNoGoAgent ✅
│   │   ├── requirement_extraction_agent.py  # B1 — RequirementsExtractionAgent ✅
│   │   ├── requirement_validation_agent.py  # B2 — RequirementsValidationAgent ✅
│   │   ├── architecture_agent.py        # C1 — ArchitecturePlanningAgent ✅
│   │   ├── writing_agent.py             # C2 — RequirementWritingAgent ✅
│   │   ├── narrative_agent.py           # C3 — NarrativeAssemblyAgent ✅
│   │   ├── technical_validation_agent.py    # D1 — TechnicalValidationAgent ✅
│   │   ├── commercial_agent.py          # E1 — CommercialAgent (stub)
│   │   ├── legal_agent.py               # E2 — LegalAgent (stub)
│   │   ├── final_readiness_agent.py     # F1 — FinalReadinessAgent (stub)
│   │   └── submission_agent.py          # F2 — SubmissionAgent (stub)
│   │
│   ├── models/                          # ── Data Layer ──
│   │   ├── enums.py                     # PipelineStatus, GoNoGoDecision, categories, etc.
│   │   ├── schemas.py                   # 20+ Pydantic models for each agent's output
│   │   └── state.py                     # RFPGraphState — the shared LangGraph state
│   │
│   ├── mcp/                             # ── MCP Server (in-process module) ──
│   │   ├── mcp_server.py                # MCPService facade — single entry point for agents
│   │   ├── knowledge_loader.py          # Seed KB from JSON files
│   │   ├── vector_store/
│   │   │   ├── rfp_store.py             # RFP Vector Store (Pinecone)
│   │   │   ├── knowledge_store.py       # Company KB (Pinecone + MongoDB)
│   │   │   └── bm25_store.py            # BM25 keyword-based retrieval
│   │   ├── rules/
│   │   │   ├── policy_rules.py          # Hard disqualification rules
│   │   │   ├── validation_rules.py      # Prohibited language checks
│   │   │   ├── commercial_rules.py      # Pricing margin validation
│   │   │   ├── legal_rules.py           # Combined E1+E2 gate logic
│   │   │   └── rules_config.py          # Shared rules configuration
│   │   ├── schema/
│   │   │   ├── capability_schema.py     # Capability model
│   │   │   ├── pricing_schema.py        # PricingParameters model
│   │   │   └── requirement_schema.py    # ExtractedRequirement model
│   │   ├── embeddings/
│   │   │   └── embedding_model.py       # Sentence Transformers wrapper
│   │   └── knowledge_data/              # Seed JSON files for KB
│   │       ├── capabilities.json
│   │       ├── certifications.json
│   │       ├── pricing_rules.json
│   │       ├── legal_templates.json
│   │       ├── past_proposals.json
│   │       └── extracted_policies.json
│   │
│   ├── services/                        # ── Business Services ──
│   │   ├── llm_service.py               # LLM call wrappers (text, JSON, deterministic)
│   │   ├── vision_service.py            # VLM-based table detection and extraction
│   │   ├── parsing_service.py           # PDF/DOCX extraction + semantic chunking + VLM tables
│   │   ├── obligation_detector.py       # Rule-based obligation indicator detection (B1 Layer 1)
│   │   ├── cross_ref_resolver.py        # Cross-reference resolution between requirements
│   │   ├── section_store.py             # Section-level text storage for extraction
│   │   ├── policy_extraction_service.py # LLM-based policy extraction from KB docs
│   │   ├── file_service.py              # Local / S3 file operations
│   │   ├── storage_service.py           # Coordinates file + state persistence
│   │   └── audit_service.py             # Audit trail recording (in-memory)
│   │
│   ├── persistence/                     # ── Data Persistence ──
│   │   ├── mongo_client.py              # MongoDB connection wrapper
│   │   ├── state_repository.py          # State persistence (in-memory)
│   │   └── checkpoint.py                # JSON checkpoint save/load per agent
│   │
│   ├── orchestration/                   # ── LangGraph Pipeline ──
│   │   ├── graph.py                     # StateGraph (17 nodes + edges + run_pipeline)
│   │   └── transitions.py              # Conditional routing (5 decision functions)
│   │
│   ├── prompts/                         # ── LLM Prompt Templates (9 files) ──
│   │   ├── structuring_prompt.txt       # A2 section classification
│   │   ├── go_no_go_prompt.txt          # A3 go/no-go analysis
│   │   ├── extraction_prompt.txt        # B1 requirement extraction
│   │   ├── requirements_validation_prompt.txt  # B2 validation
│   │   ├── architecture_prompt.txt      # C1 architecture planning
│   │   ├── writing_prompt.txt           # C2 response writing
│   │   ├── validation_prompt.txt        # D1 technical validation
│   │   ├── legal_prompt.txt             # E2 legal review
│   │   └── policy_extraction_prompt.txt # KB policy extraction
│   │
│   ├── utils/
│   │   ├── logger.py                    # Logging setup
│   │   ├── hashing.py                   # SHA-256 hashing
│   │   └── text.py                      # Text truncation and boundary utils
│   │
│   └── tests/                           # ── Test Suite (8 files) ──
│       ├── test_agents.py               # Per-agent unit tests
│       ├── test_pipeline.py             # End-to-end pipeline tests
│       ├── test_rules.py                # MCP rule layer tests
│       ├── test_api.py                  # API endpoint tests
│       ├── test_extraction_overhaul.py  # B1 extraction overhaul validation
│       ├── test_obligation_detector.py  # Obligation detection tests
│       ├── test_quality_fixes.py        # C2 quality fix verification
│       └── test_stage4.py               # Stage 4 integration tests
│
├── frontend/                            # ═══ FRONTEND ═══
│   ├── index.html                       # Single-page dashboard (vanilla JS + CSS)
│   └── README.md
│
├── example_docs/                        # Sample documents for testing
│   ├── Telecom RFP Document.pdf         # 14-page telecom UC RFP
│   ├── BSS_RFP_2026.pdf                # BSS RFP document
│   ├── Example_Response.docx            # Example response document
│   └── kb-docs/                         # Sample KB documents (7 PDFs)
│
├── scripts/                             # Utility scripts
│   └── verify_pinecone.py              # Pinecone index verification
│
├── storage/                             # Local file + checkpoint storage
├── requirements.txt
├── .env.example                         # Only 3 secret keys needed
└── README.md
```

---

## Pipeline: 13-Stage Flow

```
A1 → A2 ──┬── (retry loop, max 3) ──→ A3 ──→ B1 → B2 → C1 → C2 → C3 → D1 ──┬── PASS ──→ E1+E2 → F1 → F2 → END
           │                           │                                       │
           └── escalate → END          └── (NO_GO: status preserved,           ├── REJECT → C3 (retry, max 3)
                                             pipeline always continues)         └── escalate_validation → END
```

> **Note:** A3 Go/No-Go no longer terminates the pipeline on `NO_GO`. The decision is preserved for frontend display, but processing always continues to B1.

---

## Agent Descriptions

### Phase A — Document Understanding & Strategic Assessment

#### A1 — Intake Agent ✅

| Property | Value |
|---|---|
| **Class** | `IntakeAgent` |
| **File** | `agents/intake_agent.py` |
| **Uses LLM** | ❌ No |
| **Uses VLM** | ✅ Yes — HuggingFace Qwen3-VL for table detection and extraction |
| **Uses MCP** | ✅ Stores chunks to RFP Store |
| **Deterministic** | ✅ Yes |

The gateway agent. Takes a raw uploaded PDF, validates it, extracts all text and metadata (including VLM-based table extraction), builds semantic chunks, and stores them in MCP for all downstream agents.

**Processing:** File validation → SHA-256 hashing → structured block extraction (`ParsingService.parse_pdf_blocks()`) → VLM table extraction → metadata extraction via regex → semantic chunk preparation → MCP storage → state update.

**State writes:** `rfp_metadata`, `uploaded_file_path`, `raw_text`, `status → INTAKE_COMPLETE`

---

#### A2 — Structuring Agent ✅

| Property | Value |
|---|---|
| **Class** | `StructuringAgent` |
| **File** | `agents/structuring_agent.py` |
| **Uses LLM** | ✅ Yes — `llm_text_call(deterministic=True)` |
| **Uses MCP** | ✅ Full fetch from RFP Store |
| **Has Retry Loop** | ✅ Up to 3 attempts |

Classifies the RFP document into logical sections across six categories: `scope`, `technical`, `compliance`, `legal`, `submission`, `evaluation`. Assigns confidence scores. If overall confidence < 0.6, retries with better hints (up to 3 times).

**State writes:** `structuring_result`, `status → GO_NO_GO` or `STRUCTURING` (retry)

**Routing:** confidence ≥ 0.6 → A3 | retry_count < 3 → A2 (retry) | retry_count ≥ 3 → escalate → END

---

#### A3 — Go / No-Go Agent ✅

| Property | Value |
|---|---|
| **Class** | `GoNoGoAgent` |
| **File** | `agents/go_no_go_agent.py` |
| **Uses LLM** | ✅ Yes — deterministic |
| **Uses MCP** | ✅ RFP Store + Knowledge Store + Policy Store |

Makes the strategic **GO / NO_GO** decision by evaluating the RFP against company policies, capabilities, and risk factors. Produces a detailed requirement-to-policy mapping table with scores (strategic fit, technical feasibility, regulatory risk on 0-10 scale).

> **Note:** A3's output is **advisory only** — it does NOT filter the requirements list.

**State writes:** `go_no_go_result`, `status → EXTRACTING_REQUIREMENTS`

> **Go/No-Go Bypass:** Even if the decision is `NO_GO`, the pipeline always continues to B1. The `NO_GO` decision is preserved in `go_no_go_result` for frontend display, but does not terminate the pipeline. This allows users to see the full RFP analysis.

---

### Phase B — Requirements Analysis

#### B1 — Requirements Extraction Agent ✅

| Property | Value |
|---|---|
| **Class** | `RequirementsExtractionAgent` |
| **File** | `agents/requirement_extraction_agent.py` |
| **Uses LLM** | ✅ Yes — `llm_deterministic_call()` — batched per section |
| **Uses MCP** | ✅ `fetch_all_rfp_chunks(rfp_id)` |
| **Deterministic** | ✅ Yes — temperature=0, seed=42 |

The most complex agent. Performs a **full-document sweep** using a two-layer architecture:

1. **Layer 1 — Rule-based** (`ObligationDetector` in `services/obligation_detector.py`): Scans for obligation patterns (must, shall, required, etc.), counts indicators, applies density-based fallback
2. **Layer 2 — LLM structuring** (batched): Token-budget-aware batching, structured extraction with retry on failure

**Post-processing:** JSON parsing with recovery → requirement construction → embedding-based 3-tier deduplication (exact at ≥0.99, same-section at ≥0.92, cross-section at ≥0.95) → sequential ID re-assignment → coverage validation

**State writes:** `requirements` (list[Requirement]), `status → VALIDATING_REQUIREMENTS`

--- 

#### B2 — Requirements Validation Agent ✅

| Property | Value |
|---|---|
| **Class** | `RequirementsValidationAgent` |
| **File** | `agents/requirement_validation_agent.py` |
| **Uses LLM** | ✅ Yes — 1-2 deterministic calls |

Cross-checks B1's requirements for duplicates, contradictions, and ambiguities. If confidence < `min_validation_confidence` (0.7), performs one grounded refinement pass using original RFP text. Refinement guardrails: can only REMOVE issues or LOWER severity — never add new issues.

> **Note:** B2 does **NOT filter** the requirements list. Full `state.requirements` from B1 passes unchanged to C1.

**State writes:** `requirements_validation`, `status → ARCHITECTURE_PLANNING`

---

### Phase C — Response Generation

#### C1 — Architecture Planning Agent ✅

| Property | Value |
|---|---|
| **Class** | `ArchitecturePlanningAgent` |
| **File** | `agents/architecture_agent.py` |
| **Uses LLM** | ✅ Yes — deterministic |
| **Uses MCP** | ✅ RFP Store + Knowledge Store |

Produces the **complete response document blueprint**. Section types: `requirement_driven`, `knowledge_driven`, `commercial`, `legal`, `boilerplate`.

**Processing:** Gather requirements → format A2 sections → fetch submission instructions (4 MCP queries) → fetch capabilities (general + per-category + per-topic) → LLM call → parse sections → **programmatic gap-fill** (assigns unassigned requirements via keyword scoring with capacity penalty) → **auto-split** overloaded sections (max 20 reqs/section) → coverage check → state update.

**State writes:** `architecture_plan` (sections + gaps + instructions), `status → WRITING_RESPONSES`

---

#### C2 — Requirement Writing Agent ✅

| Property | Value |
|---|---|
| **Class** | `RequirementWritingAgent` |
| **File** | `agents/writing_agent.py` |
| **Uses LLM** | ✅ Yes — deterministic, per-section calls |
| **Uses MCP** | ✅ Knowledge Store (capabilities) |

Generates prose response for each section from C1's architecture plan.

**Key features:**
- **Token-aware budgeting** — 40% requirements, 35% capabilities, 15% instructions, 10% guidance
- **RFP metadata injection** — client name, title, dates included to prevent placeholder hallucination
- **Actual word count** — uses `len(content.split())`, not LLM self-reported counts
- **Three-tier coverage matrix:** `full` (LLM confirmed), `partial` (C1 assigned but not confirmed), `missing` (not assigned)

**State writes:** `writing_result` (section_responses + coverage_matrix), `status → ASSEMBLING_NARRATIVE`

---

#### C3 — Narrative Assembly Agent ✅

| Property | Value |
|---|---|
| **Class** | `NarrativeAssemblyAgent` |
| **File** | `agents/narrative_agent.py` |
| **Uses LLM** | ✅ Yes — `llm_large_text_call()` (Llama 4 Scout) |
| **Uses MCP** | ❌ No |

Combines C2's section responses into a cohesive proposal document with LLM-generated executive summary, inter-section transitions, and a comprehensive coverage appendix. Handles split-section reassembly (sections that were auto-split by C1 are merged back). Detects and warns about placeholder text (`[...]`, `{{...}}`). Participates in D1→C3 retry loop.

**State writes:** `assembled_proposal` (executive_summary, full_narrative, section_order, word_count, coverage_appendix), `status → TECHNICAL_VALIDATION`

---

### Phase D — Quality Assurance

#### D1 — Technical Validation Agent ✅

| Property | Value |
|---|---|
| **Class** | `TechnicalValidationAgent` |
| **File** | `agents/technical_validation_agent.py` |
| **Uses LLM** | ✅ Yes — `llm_large_text_call()` (Llama 4 Scout) |
| **Uses MCP** | ❌ No |
| **Has Retry Loop** | ✅ Up to 3 retries (routes back to C3) |

Validates the assembled proposal against original requirements using single-call or multi-pass processing (auto-selected based on input size). Runs 4 validation checks: **completeness** (all requirements addressed), **alignment** (responses match requirement intent), **realism** (no overpromising), **consistency** (no contradictions between sections).

**Budget constants (Llama 4 Scout):**
- Single-call threshold: 80K chars (proposals under this use one LLM call)
- Max proposal chars: 100K | Max requirements chars: 50K
- Per-pass budgets: ~20-30K chars for multi-pass mode

**State writes:** `technical_validation` (decision, checks, critical_failures, warnings, feedback_for_revision, retry_count), `status → COMMERCIAL_REVIEW`

**Routing:** PASS → E1+E2 | REJECT → C3 (max 3 retries) | REJECT after 3 → escalate → END

---

### Phase E — Commercial & Legal Review

> E1 and E2 run in `commercial_legal_parallel` node (sequential execution with fan-in gate).

#### E1 — Commercial Agent *(stub)*

Generates pricing breakdown using MCP Knowledge Store pricing rules.

#### E2 — Legal Agent *(stub)*

Analyzes contract clauses for legal risk. **Has VETO power** — BLOCK terminates the pipeline.

---

### Phase F — Finalization & Delivery

#### F1 — Final Readiness Agent *(stub)*

Compiles approval package and triggers the **human approval gate**.

#### F2 — Submission & Archive Agent *(stub)*

Final formatting, packaging, SHA-256 hashing for auditability, archival. Pipeline status → `SUBMITTED`.

---

## Shared Infrastructure

### BaseAgent

All 13 agents inherit from `BaseAgent` (`agents/base_agent.py`):
- **`process(state: dict) → dict`** — Public entry called by LangGraph. Hydrates state, calls `_real_process()`, handles errors, manages audit trail, broadcasts WebSocket events.
- **`_real_process(state: RFPGraphState) → RFPGraphState`** — Abstract method each agent overrides.
- `NotImplementedError` → Agent skipped gracefully (stubs continue pipeline).
- All other exceptions → logged, re-raised (pipeline fails).

### Pipeline Graph & Routing

`orchestration/graph.py` wires all agents with:
- **5 conditional edges** (A2 retry, A3 go/no-go, D1 validation, E1+E2 gate, F1 approval)
- **5 terminal nodes** (`end_no_go`, `end_legal_block`, `end_rejected`, `escalate_structuring`, `escalate_validation`)
- **1 composite node** (`commercial_legal_parallel` — E1+E2 sequential with fan-in gate)

### Checkpointing

`persistence/checkpoint.py` saves agent output as JSON files at `storage/checkpoints/{rfp_id}/{agent_name}.json` after each agent completes. Enables:
- **Re-running** from any agent without re-executing predecessors
- **Debugging** by inspecting intermediate state
- **Persistence** across server restarts (checkpoint-only runs show as `CHECKPOINTED`)

---

## State Schema

The shared state object (`RFPGraphState` in `models/state.py`):

| Field | Type | Owner | Description |
|---|---|---|---|
| `status` | `PipelineStatus` | Every agent | Current pipeline status |
| `current_agent` | `str` | BaseAgent | Currently executing agent name |
| `error_message` | `str` | Any | Error details if pipeline fails |
| `state_version` | `int` | Auto-increment | Version counter for audit trail |
| `tracking_rfp_id` | `str` | API route | Set at upload for WebSocket tracking |
| `rfp_metadata` | `RFPMetadata` | A1 | ID, client name, deadline, status |
| `uploaded_file_path` | `str` | Initial input | Original file path |
| `raw_text` | `str` | A1 | Extracted document text |
| `structuring_result` | `StructuringResult` | A2 | Section map with confidence scores |
| `go_no_go_result` | `GoNoGoResult` | A3 | GO/NO_GO with scores and reasoning |
| `requirements` | `list[Requirement]` | B1 | Classified requirements with unique IDs |
| `requirements_validation` | `RequirementsValidationResult` | B2 | Duplicates, contradictions, ambiguities |
| `architecture_plan` | `ArchitecturePlan` | C1 | Requirement groupings + capability mappings |
| `writing_result` | `WritingResult` | C2 | Per-section prose + coverage matrix |
| `assembled_proposal` | `AssembledProposal` | C3 | Full narrative document |
| `technical_validation` | `TechnicalValidationResult` | D1 | Pass/fail + issues + retry count |
| `commercial_result` | `CommercialResult` | E1 | Pricing breakdown + terms |
| `legal_result` | `LegalResult` | E2 | Decision + risk register |
| `commercial_legal_gate` | `CommercialLegalGateResult` | Orchestration | Combined gate decision |
| `approval_package` | `ApprovalPackage` | F1 | Decision brief for leadership |
| `submission_record` | `SubmissionRecord` | F2 | Archive details + file hash |
| `audit_trail` | `list[AuditEntry]` | Every agent | Timestamped action log |

---

## Governance & Decision Points

| Gate | Agent | Condition | Outcome |
|---|---|---|---|
| **Structuring Confidence** | A2 | confidence < 0.6 after 3 retries | Escalate to human → END |
| **Go / No-Go** | A3 | Policy violation or low scores | Status set to NO_GO, pipeline **continues** |
| **Technical Validation** | D1 | REJECT | Loop to C3 (max 3), then escalate → END |
| **Legal Review** | E2 | BLOCK (critical risk) | Legal Block → END |
| **Human Approval** | F1 | REJECT | Rejected → END |

---

## Configuration

All settings via `rfp_automation/config.py` using `pydantic-settings`.

**Secrets (from `.env` file):**

| Setting | Description |
|---|---|
| `groq_api_key` | Groq Cloud API key |
| `pinecone_api_key` | Pinecone API key |
| `mongodb_uri` | MongoDB connection string (default: `mongodb://localhost:27017`) |
| `huggingface_api_key` | HuggingFace API key (for VLM) |
| `aws_secret_key` | AWS secret key (for S3, optional) |

**Hardcoded defaults (in `config.py`, not in `.env`):**

| Setting | Default | Description |
|---|---|---|
| `llm_model` | `qwen/qwen3-32b` | Primary LLM (B1, A2, A3, C1) — ~32K context |
| `llm_large_model` | `meta-llama/llama-4-scout-17b-16e-instruct` | Large-context LLM (C2, B2, D1, C3) — ~131K context |
| `llm_temperature` | `0.2` | Default LLM temperature |
| `llm_max_tokens` | `8192` | Max **output** tokens per LLM call |
| `llm_large_max_tokens` | `8192` | Max **output** tokens per large LLM call |
| `vlm_provider` | `huggingface` | VLM provider (`huggingface` or `groq`) |
| `vlm_model` | `Qwen/Qwen3-VL-8B-Instruct:novita` | VLM model name |
| `vlm_max_tokens` | `4096` | Max tokens per VLM call |
| `vlm_enabled` | `true` | Feature flag for VLM processing |
| `extraction_llm_temperature` | `0.0` | Deterministic LLM temperature |
| `embedding_model` | `all-MiniLM-L6-v2` | Sentence transformer model |
| `storage_backend` | `local` | File storage (`local` / `s3`) |
| `pinecone_index_name` | `rfp-automation` | Pinecone index name |
| `max_validation_retries` | `3` | D1 validation retry limit |
| `max_structuring_retries` | `3` | A2 structuring retry limit |
| `min_validation_confidence` | `0.7` | B2 refinement trigger threshold |
| `approval_timeout_hours` | `48` | Human approval timeout |
| `extraction_dedup_similarity_threshold` | `0.99` | B1 dedup cosine threshold |
| `extraction_coverage_warn_ratio` | `0.6` | B1 coverage warning threshold |
| `extraction_min_output_headroom_ratio` | `0.40` | B1 token budget headroom |
| `extraction_min_candidate_density` | `0.15` | B1 candidate density threshold |
