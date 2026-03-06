# RFP Response Automation System

## Overview

A multi-agent AI system that automates the end-to-end process of responding to Requests for Proposal (RFP). The system ingests an RFP document, extracts and classifies requirements, generates a tailored technical and commercial response, validates quality, performs legal review, and produces a submission-ready proposal — all orchestrated as a LangGraph state machine with built-in governance controls.

**Problem:** RFP response is slow, expensive, and error-prone.
**Solution:** Multi-agent AI automation with validation loops, veto points, and human approval gates.

---

## Architecture

### Core Design Principles

- **MCP Server as Central Hub** — all agents retrieve context from the MCP server rather than passing raw data through state. Agents query, reason, and write outputs to shared graph state.
- **12-Stage Pipeline** — each stage is an independent agent with a single responsibility.
- **Governance Built In** — veto points (A3, E2), validation loops (D1→C3), and a human approval gate (F1) before submission.

### Intelligence Sources (via MCP Server)

| Source | Contents |
|---|---|
| **Company Knowledge Store** | Product specs, past proposals, certifications, pricing rules, legal templates, compliance policies — stored as embeddings |
| **Incoming RFP Store** | Full RFP text chunked and embedded at ingestion — all agents retrieve RFP context from here |

### MCP Server Layers

| Layer | Module | Who Queries It |
|---|---|---|
| RFP Vector Store | `mcp/vector_store/rfp_store.py` | A1, A2, A3, B1, C1, C2, D1, E2 |
| Knowledge Store | `mcp/vector_store/knowledge_store.py` | A3, C1, C2, E1, E2 |
| Policy Rules | `mcp/rules/policy_rules.py` | A3 Go/No-Go gate |
| Validation Rules | `mcp/rules/validation_rules.py` | D1 Validation gate |
| Commercial Rules | `mcp/rules/commercial_rules.py` | E1 Commercial gate |
| Legal Rules | `mcp/rules/legal_rules.py` | E1+E2 fan-in gate |

---

## Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.10+ |
| LLM | Groq Cloud (`llama-3.3-70b-versatile`) via `langchain-groq` |
| Orchestration | LangGraph (state machine — 17 nodes, 5 conditional edges) |
| Vector DB | Pinecone Serverless (AWS us-east-1, cosine similarity) |
| Embeddings | Sentence Transformers (`all-MiniLM-L6-v2`, 384 dimensions) |
| Structured DB | MongoDB (company config, certifications, pricing, legal) |
| API | FastAPI + uvicorn (async, `to_thread` for heavy I/O) |
| Real-time | WebSocket via `PipelineProgress` singleton |
| Frontend | Single-page vanilla JS dashboard (served at `/`) |
| File Parsing | PyMuPDF (PDF), python-docx (DOCX) |
| Vision/Tables | Groq VLM (`llama-4-scout-17b-16e-instruct`) for table extraction |
| State Models | Pydantic v2 (type safety + validation) |
| Configuration | pydantic-settings (`.env` file support) |
| Testing | pytest |

---

## Project Structure

```
RFP-Responder/
├── Documentation/
│   ├── project-description.md           # This file — full system spec + agent descriptions
│   └── implementation-plan.md           # Detailed implementation plan with current status
│
├── rfp_automation/                      # ═══ BACKEND ═══
│   ├── __init__.py
│   ├── __main__.py                      # CLI entry: python -m rfp_automation
│   ├── config.py                        # Centralised config (pydantic-settings + .env)
│   ├── main.py                          # run() + serve() entry points
│   │
│   ├── api/                             # ── HTTP Layer ──
│   │   ├── __init__.py                  # FastAPI app factory
│   │   ├── routes.py                    # RFP endpoints (upload, status, approve, list, WS)
│   │   ├── knowledge_routes.py          # KB endpoints (upload, status, query, seed, files)
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
│   │   ├── narrative_agent.py           # C3 — NarrativeAssemblyAgent (stub)
│   │   ├── technical_validation_agent.py    # D1 — TechnicalValidationAgent (stub)
│   │   ├── commercial_agent.py          # E1 — CommercialAgent (stub)
│   │   ├── legal_agent.py               # E2 — LegalAgent (stub)
│   │   ├── final_readiness_agent.py     # F1 — FinalReadinessAgent (stub)
│   │   └── submission_agent.py          # F2 — SubmissionAgent (stub)
│   │
│   ├── mcp/                             # ── MCP Server (in-process module) ──
│   │   ├── mcp_server.py                # MCPService facade — single entry point
│   │   ├── vector_store/
│   │   │   ├── rfp_store.py             # RFP Vector Store (Pinecone)
│   │   │   └── knowledge_store.py       # Company KB (Pinecone + MongoDB)
│   │   ├── rules/                       # Policy, validation, commercial, legal
│   │   ├── schema/                      # Capability, pricing, requirement models
│   │   └── embeddings/
│   │       └── embedding_model.py       # Sentence Transformers wrapper
│   │
│   ├── models/                          # ── Data Layer ──
│   │   ├── enums.py                     # Status codes, decision types, categories
│   │   ├── state.py                     # RFPGraphState — the shared LangGraph state
│   │   └── schemas.py                   # 20+ Pydantic models for each agent's output
│   │
│   ├── services/                        # ── Business Services ──
│   │   ├── file_service.py              # Local / S3 file operations
│   │   ├── parsing_service.py           # PDF/DOCX extraction + chunking + VLM tables
│   │   ├── llm_service.py               # LLM call wrappers (text, JSON, deterministic)
│   │   ├── vision_service.py            # VLM-based table detection and extraction
│   │   ├── storage_service.py           # Coordinates file + state persistence
│   │   └── audit_service.py             # Audit trail recording
│   │
│   ├── persistence/                     # ── Data Persistence ──
│   │   ├── mongo_client.py              # MongoDB connection wrapper
│   │   ├── state_repository.py          # State persistence (in-memory)
│   │   └── checkpoint.py               # JSON checkpoint save/load per agent
│   │
│   ├── orchestration/                   # ── LangGraph Pipeline ──
│   │   ├── graph.py                     # StateGraph (17 nodes + edges + run_pipeline)
│   │   └── transitions.py              # Conditional routing (5 decision functions)
│   │
│   ├── prompts/                         # ── LLM Prompt Templates ──
│   │   ├── extraction_prompt.txt        # B1 requirement extraction
│   │   ├── architecture_prompt.txt      # C1 architecture planning
│   │   ├── go_no_go_prompt.txt          # A3 go/no-go analysis
│   │   ├── structuring_prompt.txt       # A2 section classification
│   │   ├── writing_prompt.txt           # C2 response writing
│   │   ├── validation_prompt.txt        # D1 technical validation
│   │   └── legal_prompt.txt             # E2 legal review
│   │
│   ├── utils/
│   │   ├── logger.py                    # Logging setup
│   │   └── hashing.py                   # SHA-256 hashing
│   │
│   └── tests/
│       ├── test_agents.py               # Per-agent unit tests
│       ├── test_pipeline.py             # End-to-end pipeline tests
│       └── test_rules.py                # MCP rule layer tests
│
├── frontend/                            # ═══ FRONTEND ═══
│   ├── index.html                       # Single-page dashboard (vanilla JS + CSS)
│   └── README.md
│
├── example_docs/                        # Sample RFP documents for testing
├── storage/                             # Local file + checkpoint storage
├── requirements.txt
├── .env.example
└── README.md
```

---

## Pipeline: 12-Stage Flow

```
A1 → A2 ──┬── (retry loop, max 3) ──→ A3 ──┬── GO ──→ B1 → B2 → C1 → C2 → C3 → D1 ──┬── PASS ──→ E1+E2 → F1 → F2 → END
           │                                │                                           │
           └── escalate_structuring → END    └── NO_GO → END                             ├── REJECT → C3 (retry, max 3)
                                                                                         └── escalate_validation → END
```

---

## Agent Descriptions

### Phase A — Document Understanding & Strategic Assessment

#### A1 — Intake Agent ✅

| Property | Value |
|---|---|
| **Class** | `IntakeAgent` |
| **File** | `agents/intake_agent.py` |
| **Uses LLM** | ❌ No |
| **Uses MCP** | ✅ Stores chunks to RFP Store |
| **Deterministic** | ✅ Yes |

The gateway agent. Takes a raw uploaded PDF, validates it, extracts all text and metadata, builds semantic chunks, and stores them in MCP for all downstream agents.

**Processing:** File validation → SHA-256 hashing → structured block extraction (`ParsingService.parse_pdf_blocks()`) → metadata extraction via regex → semantic chunk preparation → MCP storage → state update.

**State writes:** `rfp_metadata`, `uploaded_file_path`, `raw_text`, `status → INTAKE_COMPLETE`

---

#### A2 — Structuring Agent ✅

| Property | Value |
|---|---|
| **Class** | `StructuringAgent` |
| **File** | `agents/structuring_agent.py` |
| **Uses LLM** | ✅ Yes — `llm_text_call(deterministic=True)` |
| **Uses MCP** | ✅ Full fetch from RFP Store |
| **Deterministic** | ✅ Yes |
| **Has Retry Loop** | ✅ Up to 3 attempts |

Classifies the RFP document into logical sections across six categories: `scope`, `technical`, `compliance`, `legal`, `submission`, `evaluation`. Assigns confidence scores. If overall confidence < 0.6, retries with better hints (up to 3 times).

**Processing:** Fetch all chunks deterministically → build prompt with retry hints → LLM call → parse section JSON → compute overall confidence → update state.

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
| **Deterministic** | ✅ Yes |

Makes the strategic **GO / NO_GO** decision by evaluating the RFP against company policies, capabilities, and risk factors. Produces a detailed requirement-to-policy mapping table.

**Processing:** Gather RFP content + company policies + capabilities → LLM analysis → parse scores (strategic fit, technical feasibility, regulatory risk on 0-10 scale) + policy violations + red flags + per-requirement mapping → state update.

> **Note:** A3's output is **advisory only** — it does NOT filter the requirements list. The full set from B1 flows unchanged to downstream agents.

**State writes:** `go_no_go_result`, `status → EXTRACTING_REQUIREMENTS` or `NO_GO`

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

The most complex agent. Performs a **full-document sweep** using a two-layer architecture: rule-based candidate detection (obligation indicators) followed by LLM-based structuring. Produces deduplicated, sequentially-numbered `Requirement` objects.

**Two-Layer Architecture:**
1. **Layer 1 — Rule-based** (`ObligationDetector`): Scans for obligation patterns (must, shall, required, etc.), counts indicators, applies density-based fallback
2. **Layer 2 — LLM structuring** (batched): Token-budget-aware batching, structured extraction with retry on failure

**Post-processing:** JSON parsing with recovery → requirement construction (ID, text, type, classification, category, impact, keywords, source) → embedding-based 3-tier deduplication (exact, same-section, cross-section) → sequential ID re-assignment → coverage validation

**State writes:** `requirements` (list[Requirement]), `status → VALIDATING_REQUIREMENTS`

---

#### B2 — Requirements Validation Agent ✅

| Property | Value |
|---|---|
| **Class** | `RequirementsValidationAgent` |
| **File** | `agents/requirement_validation_agent.py` |
| **Uses LLM** | ✅ Yes — 1-2 deterministic calls |
| **Uses MCP** | ❌ No |
| **Deterministic** | ✅ Yes |

Cross-checks B1's requirements for duplicates, contradictions, and ambiguities. If confidence is low, performs one grounded refinement pass using original RFP text. Refinement has guardrails: can only REMOVE issues or LOWER severity — never add new issues.

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
| **Deterministic** | ✅ Yes |

Produces the **complete response document blueprint**. Designs section structure by combining RFP structure, extracted requirements, submission instructions, and company capabilities.

**Section Types:** `requirement_driven`, `knowledge_driven`, `commercial`, `legal`, `boilerplate`

**Processing:** Gather requirements → format A2 sections → fetch submission instructions (4 MCP queries) → fetch capabilities (general + per-category + per-topic) → LLM call → parse sections → **programmatic gap-fill** (assigns unassigned requirements via keyword scoring with max 20/section cap) → **auto-split** overloaded sections by requirement category → coverage check → state update.

**Key feature:** Sections exceeding 20 requirements are automatically split into sub-sections (e.g., "Technical Solution — Security & Data Protection") to keep C2's token budget manageable.

**State writes:** `architecture_plan` (sections + gaps + instructions), `status → WRITING_RESPONSES`

---

#### C2 — Requirement Writing Agent ✅

| Property | Value |
|---|---|
| **Class** | `RequirementWritingAgent` |
| **File** | `agents/writing_agent.py` |
| **Uses LLM** | ✅ Yes — deterministic, per-section calls |
| **Uses MCP** | ✅ Knowledge Store (capabilities) |
| **Deterministic** | ✅ Yes |

Generates prose response for each section from C1's architecture plan. For each section: fetches matching capabilities from MCP Knowledge Store, builds a token-aware prompt with RFP metadata, requirements, capabilities, and guidance, then calls the LLM.

**Key features:**
- **Token-aware budgeting** — allocates prompt space: 40% requirements, 35% capabilities, 15% instructions, 10% guidance
- **RFP metadata injection** — client name, title, dates included to prevent placeholder hallucination
- **Actual word count** — uses `len(content.split())`, not LLM self-reported counts
- **Three-tier coverage matrix:** `full` (LLM confirmed), `partial` (C1 assigned but not confirmed), `missing` (not assigned)

**State writes:** `writing_result` (section_responses + coverage_matrix), `status → ASSEMBLING_NARRATIVE`

---

#### C3 — Narrative Assembly Agent *(stub)*

Combines section responses into a cohesive proposal document with executive summary, section transitions, and coverage appendix. Participates in D1→C3 retry loop.

**Expected outputs:** `assembled_proposal` (executive_summary, full_proposal_text, section_order, word_count, coverage_appendix)

---

### Phase D — Quality Assurance

#### D1 — Technical Validation Agent *(stub)*

Validates the assembled proposal against original requirements. Checks: completeness, alignment, realism, consistency. Uses MCP Validation Rules for prohibited language detection.

**Routing:** PASS → E1+E2 | REJECT → C3 (max 3 retries) | REJECT after 3 → escalate → END

---

### Phase E — Commercial & Legal Review

> E1 and E2 run in `commercial_legal_parallel` node (sequential execution, LangGraph `Send()` parallel planned).

#### E1 — Commercial Agent *(stub)*

Generates pricing breakdown using MCP Knowledge Store pricing rules. Formula: base cost + (per-requirement cost × complexity multiplier) + risk margin.

#### E2 — Legal Agent *(stub)*

Analyzes contract clauses for legal risk. **Has VETO power** — BLOCK terminates the pipeline. Fan-in gate: E2 BLOCK → END, regardless of E1.

---

### Phase F — Finalization & Delivery

#### F1 — Final Readiness Agent *(stub)*

Compiles approval package (proposal, pricing, legal, coverage) and triggers the **human approval gate**.

#### F2 — Submission & Archive Agent *(stub)*

Final formatting, packaging, SHA-256 hashing for auditability, archival. Pipeline status → `SUBMITTED`.

---

## Shared Infrastructure

### BaseAgent

All 13 agents inherit from `BaseAgent` (`agents/base_agent.py`):
- **`process(state: dict) → dict`** — Public entry called by LangGraph. Hydrates state, calls `_real_process()`, handles errors, manages audit trail, broadcasts WebSocket events.
- **`_real_process(state: RFPGraphState) → RFPGraphState`** — Abstract method each agent overrides.
- `NotImplementedError` → Agent skipped gracefully (stubs).
- All other exceptions → logged, re-raised (pipeline fails).

### Pipeline Graph & Routing

`rfp_automation/orchestration/graph.py` wires all agents with:
- **5 conditional edges** (A2 retry, A3 go/no-go, D1 validation, E1+E2 gate, F1 approval)
- **5 terminal nodes** (`end_no_go`, `end_legal_block`, `end_rejected`, `escalate_structuring`, `escalate_validation`)
- **1 composite node** (`commercial_legal_parallel` — E1+E2 sequential with fan-in gate)

---

## Data Flow

```
RFP Upload
    │
    ▼
A1 Intake ──► Embed RFP into MCP RFP Vector Store
    │
    ▼
A2 Structuring ◄──── MCP: RFP Store
    │ confidence < 0.6 (retry ≤ 3)
    ├──────────────────────────────────────► Escalate → END
    │ confidence ≥ 0.6
    ▼
A3 Go/No-Go ◄──────── MCP: RFP Store + Knowledge Store + Policy Rules
    │ NO_GO
    ├──────────────────────────────────────► END
    │ GO
    ▼
B1 Requirements Extraction ◄──── MCP: RFP Store
    │
    ▼
B2 Requirements Validation
    │
    ▼
C1 Architecture Planning ◄──────── MCP: RFP Store + Knowledge Store
    │
    ▼
C2 Requirement Writing ◄─────────── MCP: Knowledge Store
    │
    ▼
C3 Narrative Assembly
    │
    ▼
D1 Technical Validation ◄─────────── MCP: RFP Store + Validation Rules
    │ REJECT (retry ≤ 3)
    ├──────────────────────────────────► C3 Narrative Assembly
    │ PASS
    ▼
  ┌─────────────────────────────┐
  │ commercial_legal_parallel   │
  │  E1 Commercial ◄── MCP: Knowledge Store (pricing rules)
  │  E2 Legal      ◄── MCP: RFP Store + Knowledge Store (legal templates)
  └────────────┬────────────────┘
               │
               ▼
    MCP: Legal Rules (gate evaluation)
               │ BLOCK
               ├──────────────────────────────────► END – Legal Block
               │ CLEAR
               ▼
          F1 Final Readiness
               │
               ▼
        Human Approval Gate
               │ REJECT
               ├──────────────────────────────────► END – Rejected
               │ APPROVE
               ▼
          F2 Submission & Archive
               │
               ▼
             END – Submitted
```

---

## State Schema

The shared state object (`RFPGraphState` in `models/state.py`):

| Field | Type | Owner | Description |
|---|---|---|---|
| `status` | `PipelineStatus` | Every agent | Current pipeline status (19 possible values) |
| `current_agent` | `str` | BaseAgent | Currently executing agent name |
| `error_message` | `str` | Any | Error details if pipeline fails |
| `state_version` | `int` | Auto-increment | Version counter for audit trail |
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
| **Go / No-Go** | A3 | Policy violation or low scores | NO_GO → END |
| **Technical Validation** | D1 | REJECT | Loop to C3 (max 3), then escalate → END |
| **Legal Review** | E2 | BLOCK (critical risk) | Legal Block → END |
| **Human Approval** | F1 | REJECT | Rejected → END |

---

## Configuration

All settings via `rfp_automation/config.py` using `pydantic-settings` (`.env` file support).

| Setting | Default | Description |
|---|---|---|
| `llm_model` | `llama-3.3-70b-versatile` | Groq model name |
| `llm_max_tokens` | `4096` | Max tokens per LLM call |
| `embedding_model` | `all-MiniLM-L6-v2` | Sentence transformer model |
| `storage_backend` | `local` | File storage (`local` / `s3`) |
| `local_storage_path` | `./storage` | Local file storage directory |
| `vector_db_backend` | `pinecone` | Vector database backend |
| `max_validation_retries` | `3` | D1 validation retry limit |
| `max_structuring_retries` | `3` | A2 structuring retry limit |
| `approval_timeout_hours` | `48` | Human approval timeout |
