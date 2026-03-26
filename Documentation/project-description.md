# RFP Response Automation System

## Overview

A multi-agent AI system that automates the end-to-end process of responding to Requests for Proposal (RFP). The system ingests an RFP document, extracts and classifies requirements, generates a tailored technical and commercial response, validates quality, performs legal review, and produces a submission-ready PDF proposal -- all orchestrated as a LangGraph state machine with built-in governance controls and a human-in-the-loop review gate.

---

## Architecture

### Core Design Principles

- **MCP Server as Central Hub** -- all agents retrieve context from the MCP server rather than passing raw data through state. Agents query, reason, and write outputs to shared graph state.
- **14-Node Pipeline** -- each node is an independent agent with a single responsibility.
- **Governance Built In** -- veto points (A3, E2), validation loops (D1 to C2), a human validation gate (H1), and a final readiness check (F1) before submission.
- **Human-in-the-Loop** -- H1 pauses the pipeline for structured human review with section-level commenting, then F1 handles final readiness and submission.

### System Architecture Diagram

```
+-------------------------------------------------------------------+
|                        BACKEND (FastAPI)                           |
|                                                                   |
|  +----------+   +--------------+   +------------------------+    |
|  | FastAPI   |-->| Orchestration|-->|    14 Agent Nodes       |    |
|  | (API)     |   | (LangGraph)  |   | (A1->A2->...->H1->F1) |    |
|  +----------+   +--------------+   +-----------+------------+    |
|       |                                         |                 |
|       |              +--------------------------+                 |
|       |              v                                            |
|       |    +------------------+                                   |
|       |    |   MCP Server     |  <- in-process module             |
|       |    |   (MCPService)   |                                   |
|       |    |  +-------------+ |                                   |
|       |    |  | RFP Store   | |  <- Pinecone vectors              |
|       |    |  | KB Store    | |  <- Pinecone + MongoDB            |
|       |    |  | BM25 Store  | |  <- Keyword retrieval             |
|       |    |  | Rules       | |  <- Policy/validation/legal       |
|       |    |  | Embeddings  | |  <- BAAI/bge-m3                   |
|       |    |  +-------------+ |                                   |
|       |    +------------------+                                   |
|       v                                                           |
|  +----------+  +-----------+  +-----------+                      |
|  | Storage  |  |  MongoDB  |  | Pinecone  |                      |
|  | (local)  |  |  (config) |  | (vectors) |                      |
|  +----------+  +-----------+  +-----------+                      |
+-------------------------------------------------------------------+
        ^  REST + WebSocket
        |
        v
+-----------------------------------+  +------------------------------+
|  FRONTEND (served at /)           |  |  FRONTEND-NEXT               |
|  Vanilla JS single-page app      |  |  Next.js decoupled frontend  |
|                                   |  |  (separate deployment)       |
|  - Upload    -- drag & drop       |  +------------------------------+
|  - Dashboard -- list all RFPs     |
|  - Status    -- live progress     |
|  - Review    -- human validation  |
|  - KB Mgmt   -- knowledge base   |
+-----------------------------------+
```

### MCP Server Layers

The MCP server runs **in-process** as a Python module (not a separate service). Agents import `MCPService` and never touch internals.

| Layer | Module | Purpose |
|---|---|---|
| RFP Vector Store | `mcp/vector_store/rfp_store.py` | Chunked + embedded RFP content (Pinecone) |
| Knowledge Store | `mcp/vector_store/knowledge_store.py` | Company capabilities, proposals, certs (Pinecone + MongoDB) |
| BM25 Store | `mcp/vector_store/bm25_store.py` | Keyword-based retrieval for hybrid search |
| Policy Rules | `mcp/rules/policy_rules.py` | Hard disqualification rules (A3) |
| Validation Rules | `mcp/rules/validation_rules.py` | Prohibited language checks (D1) |
| Commercial Rules | `mcp/rules/commercial_rules.py` | Pricing margin validation (E1) |
| Legal Rules | `mcp/rules/legal_rules.py` | Contract clause risk scoring (E2) |
| Rules Config | `mcp/rules/rules_config.py` | Shared rules configuration store |
| Knowledge Loader | `mcp/knowledge_loader.py` | Seeds KB from JSON files in `mcp/knowledge_data/` |
| Embeddings | `mcp/embeddings/embedding_model.py` | HuggingFace Inference API wrapper |

### Knowledge Data (Seed Files)

Located in `mcp/knowledge_data/`:
- `capabilities.json` -- company product/service capabilities
- `certifications.json` -- compliance certifications held
- `pricing_rules.json` -- product pricing catalogs and rate cards
- `legal_templates.json` -- contract clause templates
- `company_profile.json` -- company profile information
- `extracted_policies.json` -- extracted company policies
- `past_proposals.json` -- historical proposal examples

---

## Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.10+ |
| LLM (Primary) | Groq Cloud (`qwen/qwen3-32b`) via `langchain-groq` -- ~32K context, used by A2, A3, B1, C1 |
| LLM (Large) | Groq Cloud (`meta-llama/llama-4-scout-17b-16e-instruct`) -- ~131K context, used by B2, C2, C3, D1, E1, E2 |
| VLM | HuggingFace / Novita (`Qwen/Qwen3-VL-8B-Instruct:novita`) for table extraction |
| Orchestration | LangGraph (state machine -- 16 nodes, 5 conditional edges) |
| Vector DB | Pinecone Serverless (AWS us-east-1, cosine similarity) |
| Embeddings | `BAAI/bge-m3` via HuggingFace Inference API (multi-key round-robin) |
| Structured DB | MongoDB (company config, certifications, pricing, legal) |
| API | FastAPI + uvicorn (async, `to_thread` for heavy I/O) |
| Real-time | WebSocket via `PipelineProgress` singleton |
| Frontend (Legacy) | Single-page vanilla JS dashboard (served at `/`) |
| Frontend (Next.js) | Decoupled Next.js frontend (separate deployment) |
| File Parsing | PyMuPDF (PDF), python-docx (DOCX) |
| PDF Output | Custom Markdown-to-PDF renderer (`scripts/md_to_pdf.py`) |
| Diagram Rendering | Mermaid CLI via `npx @mermaid-js/mermaid-cli` |
| State Models | Pydantic v2 |
| Configuration | pydantic-settings (`.env` for secrets only) |
| Testing | pytest |

### Dual-Model LLM Strategy

The system uses two LLM models via Groq Cloud, selected based on agent context requirements:

| Model | Config Key | Context Window | TPM Limit | Used By |
|---|---|---|---|---|
| `qwen/qwen3-32b` | `llm_model` | ~32K tokens | 6K TPM | A2 (structuring), A3 (go/no-go), B1 (extraction), C1 (architecture) |
| `meta-llama/llama-4-scout-17b-16e-instruct` | `llm_large_model` | ~131K tokens | 30K TPM | B2 (validation), C2 (writing), C3 (assembly), D1 (tech validation), E1 (commercial), E2 (legal) |

Both share `max_tokens=8192` for output generation. The key difference is input context capacity. Agents processing large documents (full proposals, all requirements) use the Llama model via `llm_large_text_call()`. API key rotation (`GROQ_API_KEYS`) distributes calls across multiple keys with per-key TPM-aware throttling via the `KeyRotator` singleton.

---

## Project Structure

```
RFP-Responder/
+-- Documentation/
|   +-- project-description.md           # This file -- full system spec + agent descriptions
|   +-- implementation-plan.md           # Implementation status + remaining work
|
+-- rfp_automation/                      # === BACKEND ===
|   +-- __init__.py
|   +-- __main__.py                      # CLI entry: python -m rfp_automation
|   +-- config.py                        # Centralized config (pydantic-settings + .env)
|   +-- main.py                          # run() + serve() entry points
|   |
|   +-- api/                             # -- HTTP + WebSocket Layer --
|   |   +-- __init__.py                  # FastAPI app factory + CORS + router wiring
|   |   +-- routes.py                    # RFP endpoints (upload, status, approve, list, rerun, checkpoints, WS)
|   |   +-- knowledge_routes.py          # KB endpoints (upload, status, query, seed, files, policy CRUD)
|   |   +-- websocket.py                 # PipelineProgress singleton (real-time WS broadcast)
|   |
|   +-- agents/                          # -- 14 Agents --
|   |   +-- base_agent.py                # BaseAgent -- _real_process(), audit, WS events
|   |   +-- intake_agent.py              # A1 IntakeAgent
|   |   +-- structuring_agent.py         # A2 StructuringAgent
|   |   +-- go_no_go_agent.py            # A3 GoNoGoAgent
|   |   +-- requirement_extraction_agent.py  # B1 RequirementsExtractionAgent
|   |   +-- requirement_validation_agent.py  # B2 RequirementsValidationAgent
|   |   +-- architecture_agent.py        # C1 ArchitecturePlanningAgent
|   |   +-- writing_agent.py             # C2 RequirementWritingAgent
|   |   +-- narrative_agent.py           # C3 NarrativeAssemblyAgent
|   |   +-- technical_validation_agent.py    # D1 TechnicalValidationAgent
|   |   +-- commercial_agent.py          # E1 CommercialAgent
|   |   +-- legal_agent.py               # E2 LegalAgent
|   |   +-- human_validation_agent.py    # H1 HumanValidationAgent
|   |   +-- final_readiness_agent.py     # F1 FinalReadinessAgent (includes submission)
|   |
|   +-- models/                          # -- Data Layer --
|   |   +-- enums.py                     # PipelineStatus, GoNoGoDecision, categories, etc.
|   |   +-- schemas.py                   # 20+ Pydantic models for each agent's output
|   |   +-- state.py                     # RFPGraphState -- the shared LangGraph state
|   |
|   +-- mcp/                             # -- MCP Server (in-process module) --
|   |   +-- mcp_server.py                # MCPService facade -- single entry point for agents
|   |   +-- knowledge_loader.py          # Seed KB from JSON files
|   |   +-- vector_store/
|   |   |   +-- rfp_store.py             # RFP Vector Store (Pinecone)
|   |   |   +-- knowledge_store.py       # Company KB (Pinecone + MongoDB)
|   |   |   +-- bm25_store.py            # BM25 keyword-based retrieval
|   |   +-- rules/
|   |   |   +-- policy_rules.py          # Hard disqualification rules
|   |   |   +-- validation_rules.py      # Prohibited language checks
|   |   |   +-- commercial_rules.py      # Pricing margin validation
|   |   |   +-- legal_rules.py           # Contract clause risk scoring
|   |   |   +-- rules_config.py          # Shared rules configuration
|   |   +-- schema/                      # Capability, pricing, requirement models
|   |   +-- embeddings/
|   |   |   +-- embedding_model.py       # HuggingFace Inference API wrapper
|   |   +-- knowledge_data/              # Seed JSON files for KB
|   |
|   +-- services/                        # -- Business Services --
|   |   +-- llm_service.py               # LLM call wrappers (text, JSON, deterministic, large)
|   |   +-- vision_service.py            # VLM-based table detection and extraction
|   |   +-- parsing_service.py           # PDF/DOCX extraction + semantic chunking + VLM tables
|   |   +-- review_service.py            # Human validation review package builder + feedback routing
|   |   +-- obligation_detector.py       # Rule-based obligation indicator detection (B1 Layer 1)
|   |   +-- cross_ref_resolver.py        # Cross-reference resolution between requirements
|   |   +-- section_store.py             # Section-level text storage for extraction
|   |   +-- policy_extraction_service.py # LLM-based policy extraction from KB docs
|   |   +-- file_service.py              # Local / S3 file operations
|   |   +-- storage_service.py           # Coordinates file + state persistence
|   |   +-- audit_service.py             # Audit trail recording (in-memory)
|   |
|   +-- persistence/                     # -- Data Persistence --
|   |   +-- mongo_client.py              # MongoDB connection wrapper
|   |   +-- state_repository.py          # State persistence (in-memory)
|   |   +-- checkpoint.py                # JSON checkpoint save/load per agent + pipeline log collector
|   |
|   +-- orchestration/                   # -- LangGraph Pipeline --
|   |   +-- graph.py                     # StateGraph (16 nodes + edges + run_pipeline + run_pipeline_from)
|   |   +-- transitions.py              # Conditional routing (4 decision functions)
|   |
|   +-- prompts/                         # -- LLM Prompt Templates (13 files) --
|   |   +-- structuring_prompt.txt       # A2 section classification
|   |   +-- go_no_go_prompt.txt          # A3 go/no-go analysis
|   |   +-- extraction_prompt.txt        # B1 requirement extraction
|   |   +-- requirements_validation_prompt.txt  # B2 validation
|   |   +-- architecture_prompt.txt      # C1 architecture planning
|   |   +-- writing_prompt.txt           # C2 response writing
|   |   +-- narrative_assembly_prompt.txt    # C3 narrative assembly
|   |   +-- narrative_transitions_prompt.txt # C3 section transitions
|   |   +-- validation_prompt.txt        # D1 technical validation
|   |   +-- commercial_prompt.txt        # E1 commercial analysis
|   |   +-- legal_prompt.txt             # E2 legal review
|   |   +-- factual_correction_prompt.txt   # Factual correction pass
|   |   +-- policy_extraction_prompt.txt # KB policy extraction
|   |
|   +-- utils/
|   |   +-- logger.py                    # Logging setup
|   |   +-- hashing.py                   # SHA-256 hashing
|   |   +-- text.py                      # Text truncation and boundary utils
|   |   +-- mermaid_utils.py             # Mermaid diagram extraction + rendering
|   |
|   +-- tests/                           # -- Test Suite (12 files) --
|       +-- test_agents.py               # Per-agent unit tests
|       +-- test_pipeline.py             # End-to-end pipeline tests
|       +-- test_rules.py                # MCP rule layer tests
|       +-- test_api.py                  # API endpoint tests
|       +-- test_extraction_overhaul.py  # B1 extraction overhaul validation
|       +-- test_obligation_detector.py  # Obligation detection tests
|       +-- test_quality_fixes.py        # C2 quality fix verification
|       +-- test_stage4.py              # Stage 4 integration tests
|       +-- test_commercial_legal_agents.py  # E1/E2 agent tests
|       +-- test_go_no_go_budget.py      # A3 budget tests
|       +-- test_output_cleanup.py       # Output sanitization tests
|       +-- test_table_output_fixes.py   # Table formatting tests
|
+-- frontend/                            # === FRONTEND (Legacy) ===
|   +-- index.html                       # Single-page dashboard (vanilla JS + CSS)
|   +-- css/                             # Stylesheets
|   +-- js/                              # JavaScript modules
|   +-- README.md
|
+-- frontend-next/                       # === FRONTEND (Next.js) ===
|   +-- ...                              # Decoupled frontend with separate build/deploy
|
+-- scripts/                             # Utility scripts
|   +-- md_to_pdf.py                     # Markdown to PDF converter
|   +-- resume_pipeline.py              # Pipeline resume helper
|   +-- verify_pinecone.py              # Pinecone index verification
|   +-- test_mermaid_pipeline.py        # Mermaid rendering tests
|
+-- example_docs/                        # Sample documents for testing
|   +-- rfp/                             # Sample RFP PDFs
|   +-- KB_PDF/                          # Sample KB documents
|   +-- Response/                        # Sample response documents
|
+-- storage/                             # Local file + checkpoint storage
+-- requirements.txt
+-- .env.example
+-- README.md
```

---

## API Endpoints

### RFP Pipeline (`/api/rfp`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/rfp/upload` | Upload RFP PDF, start pipeline, return `rfp_id` |
| GET | `/api/rfp/{rfp_id}/status` | Poll pipeline status and agent outputs |
| POST | `/api/rfp/{rfp_id}/approve` | Human approval gate (APPROVE / REJECT / REQUEST_CHANGES) |
| GET | `/api/rfp/list` | List all pipeline runs (in-memory + checkpointed) |
| GET | `/api/rfp/{rfp_id}/checkpoints` | List available agent checkpoints |
| DELETE | `/api/rfp/{rfp_id}/checkpoints` | Clear checkpoints for full re-run |
| POST | `/api/rfp/{rfp_id}/rerun?start_from=agent` | Re-run pipeline from a specific agent |
| GET | `/api/rfp/{rfp_id}/requirements` | Get extracted requirements + validation |
| GET | `/api/rfp/{rfp_id}/mappings` | Get A3 requirement-to-policy mappings |
| GET | `/api/rfp/{rfp_id}/debug` | Debug view of pipeline result keys |
| WS | `/api/rfp/ws/{rfp_id}` | Real-time progress events via WebSocket |
| GET | `/health` | Health check |

### Knowledge Base (`/api/knowledge`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/knowledge/upload` | Upload company doc, auto-classify, embed, extract policies |
| GET | `/api/knowledge/status` | Pinecone + MongoDB stats |
| POST | `/api/knowledge/query` | Semantic query with optional `doc_type` filter |
| POST | `/api/knowledge/seed` | Seed KB from JSON files (`mcp/knowledge_data/`) |
| GET | `/api/knowledge/files` | List uploaded KB documents |
| GET | `/api/knowledge/policies` | List extracted policies (optional `?category=` filter) |
| POST | `/api/knowledge/policies` | Add a policy manually |
| PUT | `/api/knowledge/policies/{id}` | Update a policy |
| DELETE | `/api/knowledge/policies/{id}` | Delete a policy |
| DELETE | `/api/knowledge/policies` | Delete all policies |

Swagger UI at `/docs`. Dashboard at `/`.

---

## Pipeline Flow

### Compact View

```
A1 --> A2 --+-- (retry loop, max 3) --> A3 --> B1 --> B2 --> C1 --> C2 --> C3 --> D1 --+-- PASS --> E1+E2 --> H1 --> [pause] --> F1 --> END
            |                           |                                               |
            +-- escalate --> END        +-- (NO_GO: status preserved,                   +-- REJECT --> C2 (retry, max 3)
                                              pipeline always continues)                +-- escalate_validation --> END
```

### Detailed Flow

```
A1 Intake --> A2 Structuring --> A3 Go/No-Go --> B1 Req Extraction
                  | low                              (always continues,
                  | confidence                        NO_GO status preserved
                  +-->retry (max 3x)                  for frontend display)
                  +--> ESCALATE                       |
                                                      v
                                             B2 Req Validation
                                             --> C1 Architecture
                                             --> C2 Writing
                                             --> C3 Assembly
                                                |
                                                v
                                            D1 Validation
                                            | REJECT (max 3x)
                                            +--> C2 (retry)
                                            | PASS
                                            v
                                    E1 Commercial  +
                                    E2 Legal       | (sequential with fan-in gate)
                                                   |
                                            BLOCK --> END
                                            CLEAR v
                                            H1 Human Validation Prepare
                                                |
                                        Pipeline pauses --> WebSocket END
                                        (awaits human decision via API)
                                                |
                                        Human submits APPROVE/REJECT/REQUEST_CHANGES
                                                |
                                        REQUEST_CHANGES --> rerun from computed agent
                                        REJECT --> F1 (sets REJECTED status)
                                        APPROVE v
                                            F1 Final Readiness + Submission
                                                |
                                        Builds approval package
                                        Generates proposal.md + proposal.pdf
                                        status --> SUBMITTED
                                                --> END
```

A3 Go/No-Go no longer terminates the pipeline on `NO_GO`. The decision is preserved for frontend display, but processing always continues to B1. After E1+E2, the pipeline pauses at H1 for human validation. F1 handles both final readiness and submission (formerly separate F1+F2 agents).

---

## Agent Descriptions

### Phase A -- Document Understanding and Strategic Assessment

#### A1 -- Intake Agent

| Property | Value |
|---|---|
| **Class** | `IntakeAgent` |
| **File** | `agents/intake_agent.py` |
| **Uses LLM** | No |
| **Uses VLM** | Yes -- HuggingFace Qwen3-VL for table detection and extraction |
| **Uses MCP** | Stores chunks to RFP Store |
| **Deterministic** | Yes |

The gateway agent. Takes a raw uploaded PDF, validates it, extracts all text and metadata (including VLM-based table extraction), resolves cross-references between chunks, builds semantic chunks, and stores them in MCP for all downstream agents.

**Processing:** File validation --> SHA-256 hashing --> structured block extraction (`ParsingService.parse_pdf_blocks()`) --> VLM table extraction --> metadata extraction via regex --> cross-reference resolution --> semantic chunk preparation --> MCP storage --> state update.

**State writes:** `rfp_metadata`, `uploaded_file_path`, `raw_text`, `status --> INTAKE_COMPLETE`

---

#### A2 -- Structuring Agent

| Property | Value |
|---|---|
| **Class** | `StructuringAgent` |
| **File** | `agents/structuring_agent.py` |
| **Uses LLM** | Yes -- `llm_text_call(deterministic=True)` |
| **Uses MCP** | Full fetch from RFP Store |
| **Has Retry Loop** | Up to 3 attempts |

Classifies the RFP document into logical sections across six categories: `scope`, `technical`, `compliance`, `legal`, `submission`, `evaluation`. Assigns confidence scores. If overall confidence < 0.6, retries with better hints (up to 3 times).

**State writes:** `structuring_result`, `status --> GO_NO_GO` or `STRUCTURING` (retry)

**Routing:** confidence >= 0.6 --> A3 | retry_count < 3 --> A2 (retry) | retry_count >= 3 --> escalate --> END

---

#### A3 -- Go / No-Go Agent

| Property | Value |
|---|---|
| **Class** | `GoNoGoAgent` |
| **File** | `agents/go_no_go_agent.py` |
| **Uses LLM** | Yes -- deterministic |
| **Uses MCP** | RFP Store + Knowledge Store + Policy Store |

Makes the strategic **GO / NO_GO** decision by evaluating the RFP against company policies, capabilities, and risk factors. Produces a detailed requirement-to-policy mapping table with scores (strategic fit, technical feasibility, regulatory risk on 0-10 scale).

A3's output is **advisory only** -- it does NOT filter the requirements list. Even if the decision is `NO_GO`, the pipeline always continues to B1. The `NO_GO` decision is preserved in `go_no_go_result` for frontend display.

**State writes:** `go_no_go_result`, `status --> EXTRACTING_REQUIREMENTS`

---

### Phase B -- Requirements Analysis

#### B1 -- Requirements Extraction Agent

| Property | Value |
|---|---|
| **Class** | `RequirementsExtractionAgent` |
| **File** | `agents/requirement_extraction_agent.py` |
| **Uses LLM** | Yes -- `llm_deterministic_call()` -- batched per section |
| **Uses MCP** | `fetch_all_rfp_chunks(rfp_id)` |
| **Deterministic** | Yes -- temperature=0, seed=42 |

The most complex agent. Performs a **full-document sweep** using a two-layer architecture:

1. **Layer 1 -- Rule-based** (`ObligationDetector` in `services/obligation_detector.py`): Scans for obligation patterns (must, shall, required, etc.), counts indicators, applies density-based fallback
2. **Layer 2 -- LLM structuring** (batched): Token-budget-aware batching, structured extraction with retry on failure

**Post-processing:** JSON parsing with recovery --> requirement construction --> embedding-based 3-tier deduplication (exact at >=0.99, same-section at >=0.92, cross-section at >=0.95) --> sequential ID re-assignment --> coverage validation

**State writes:** `requirements` (list[Requirement]), `status --> VALIDATING_REQUIREMENTS`

---

#### B2 -- Requirements Validation Agent

| Property | Value |
|---|---|
| **Class** | `RequirementsValidationAgent` |
| **File** | `agents/requirement_validation_agent.py` |
| **Uses LLM** | Yes -- 1-2 deterministic calls |

Cross-checks B1's requirements for duplicates, contradictions, and ambiguities. If confidence < `min_validation_confidence` (0.7), performs one grounded refinement pass using original RFP text. Refinement guardrails: can only REMOVE issues or LOWER severity -- never add new issues.

B2 does **NOT filter** the requirements list. Full `state.requirements` from B1 passes unchanged to C1.

**State writes:** `requirements_validation`, `status --> ARCHITECTURE_PLANNING`

---

### Phase C -- Response Generation

#### C1 -- Architecture Planning Agent

| Property | Value |
|---|---|
| **Class** | `ArchitecturePlanningAgent` |
| **File** | `agents/architecture_agent.py` |
| **Uses LLM** | Yes -- deterministic |
| **Uses MCP** | RFP Store + Knowledge Store |

Produces the **complete response document blueprint**. Section types: `requirement_driven`, `knowledge_driven`, `commercial`, `legal`, `boilerplate`.

**Processing:** Gather requirements --> format A2 sections --> fetch submission instructions (4 MCP queries) --> fetch capabilities (general + per-category + per-topic) --> LLM call --> parse sections --> **programmatic gap-fill** (assigns unassigned requirements via keyword scoring with capacity penalty) --> **auto-split** overloaded sections (max 20 reqs/section) --> coverage check --> state update.

**State writes:** `architecture_plan` (sections + gaps + instructions), `status --> WRITING_RESPONSES`

---

#### C2 -- Requirement Writing Agent

| Property | Value |
|---|---|
| **Class** | `RequirementWritingAgent` |
| **File** | `agents/writing_agent.py` |
| **Uses LLM** | Yes -- deterministic, per-section calls |
| **Uses MCP** | Knowledge Store (capabilities) |

Generates prose response for each section from C1's architecture plan.

**Key features:**
- **Token-aware budgeting** -- 40% requirements, 35% capabilities, 15% instructions, 10% guidance
- **RFP metadata injection** -- client name, title, dates included to prevent placeholder hallucination
- **Actual word count** -- uses `len(content.split())`, not LLM self-reported counts
- **Three-tier coverage matrix:** `full` (LLM confirmed), `partial` (C1 assigned but not confirmed), `missing` (not assigned)
- **Table format detection** -- detects fillable tables in RFP and preserves their structure

**State writes:** `writing_result` (section_responses + coverage_matrix), `status --> ASSEMBLING_NARRATIVE`

---

#### C3 -- Narrative Assembly Agent

| Property | Value |
|---|---|
| **Class** | `NarrativeAssemblyAgent` |
| **File** | `agents/narrative_agent.py` |
| **Uses LLM** | Yes -- `llm_large_text_call()` (Llama 4 Scout) |
| **Uses MCP** | No |

Combines C2's section responses into a cohesive proposal document with LLM-generated executive summary, inter-section transitions, and a comprehensive coverage appendix. Handles split-section reassembly (sections that were auto-split by C1 are merged back). Detects and warns about placeholder text (`[...]`, `{{...}}`). Participates in D1 to C2 retry loop.

**State writes:** `assembled_proposal` (executive_summary, full_narrative, section_order, word_count, coverage_appendix), `status --> TECHNICAL_VALIDATION`

---

### Phase D -- Quality Assurance

#### D1 -- Technical Validation Agent

| Property | Value |
|---|---|
| **Class** | `TechnicalValidationAgent` |
| **File** | `agents/technical_validation_agent.py` |
| **Uses LLM** | Yes -- `llm_large_text_call()` (Llama 4 Scout) |
| **Uses MCP** | No |
| **Has Retry Loop** | Up to 3 retries (routes back to C2) |

Validates the assembled proposal against original requirements using single-call or multi-pass processing (auto-selected based on input size). Runs 4 validation checks: **completeness** (all requirements addressed), **alignment** (responses match requirement intent), **realism** (no overpromising), **consistency** (no contradictions between sections).

**Budget constants (Llama 4 Scout):**
- Single-call threshold: 80K chars (proposals under this use one LLM call)
- Max proposal chars: 100K | Max requirements chars: 50K
- Per-pass budgets: ~20-30K chars for multi-pass mode

**State writes:** `technical_validation` (decision, checks, critical_failures, warnings, feedback_for_revision, retry_count), `status --> COMMERCIAL_REVIEW`

**Routing:** PASS --> E1+E2 | REJECT --> C2 (max 3 retries) | REJECT after max --> auto-pass

---

### Phase E -- Commercial and Legal Review

E1 and E2 run in `commercial_legal_parallel` node (sequential execution with fan-in gate). After both complete, E1/E2 content is injected into the assembled proposal narrative, replacing `[PIPELINE_STUB]` markers set by C2.

#### E1 -- Commercial Agent

| Property | Value |
|---|---|
| **Class** | `CommercialAgent` |
| **File** | `agents/commercial_agent.py` |
| **Uses LLM** | Yes -- `llm_large_text_call()` |
| **Uses MCP** | RFP Store + Knowledge Store |

Generates a realistic commercial proposal section by analyzing the RFP requirements against the company's Knowledge Base (product pricing catalogs, rate cards, terms and conditions).

**Key Principle:** ALL pricing figures MUST come from the KB or the RFP. If the KB lacks pricing data, the agent MUST flag it explicitly. The agent MUST NEVER fabricate, assume, or use hardcoded pricing values.

**Processing:** Scope analysis --> RFP commercial context extraction (including pricing table layout detection) --> KB pricing data query --> LLM pricing analysis --> `commercial_rules.py` validation --> missing data flagging --> state update.

**State writes:** `commercial_result` (decision, total_price, currency, line_items, commercial_narrative, validation_flags, confidence)

---

#### E2 -- Legal Agent

| Property | Value |
|---|---|
| **Class** | `LegalAgent` |
| **File** | `agents/legal_agent.py` |
| **Uses LLM** | Yes -- `llm_large_text_call(deterministic=True)` |
| **Uses MCP** | RFP Store + Knowledge Store + Legal Rules |
| **Has VETO power** | BLOCKED decision terminates the pipeline |

Analyzes contract clauses for legal risk and checks compliance certifications.

**Processing:**
1. Extract contract clauses from RFP (MCP + structuring result + semantic search)
2. Load legal templates from knowledge base
3. Query KB for company standard legal terms
4. Load certifications (held vs required)
5. Rule-based clause scoring (deterministic, via `legal_rules.py`)
6. LLM clause analysis + risk register narrative + legal narrative
7. Compliance certification check (gap analysis with severity grading)
8. Decision: APPROVED / CONDITIONAL / BLOCKED

**State writes:** `legal_result` (decision, clause_risks, compliance_checks, block_reasons, risk_register_summary, legal_narrative, confidence)

---

### Phase H -- Human Validation

#### H1 -- Human Validation Agent

| Property | Value |
|---|---|
| **Class** | `HumanValidationAgent` |
| **File** | `agents/human_validation_agent.py` |
| **Uses LLM** | No |
| **Uses:** | `ReviewService.build_review_package(state)` |

Builds a structured `ReviewPackage` containing:
- Source sections (from the original RFP, with section-level and paragraph-level anchoring)
- Response sections (C2 output with E1/E2 content injected into stub sections)
- Validation summary (from D1)
- Commercial summary (from E1)
- Legal summary (from E2)

Sets pipeline status to `AWAITING_HUMAN_VALIDATION` and pauses the pipeline. The WebSocket sends `END` to the frontend. The pipeline resumes only when a human submits a decision via the API.

**Human decisions:**
- **APPROVE** -- F1 runs, generates final PDF, status --> SUBMITTED
- **REJECT** -- F1 runs, sets status --> REJECTED
- **REQUEST_CHANGES** -- `ReviewService.compute_rerun_target()` determines the earliest agent to re-run based on comment domains and rerun hints, then `run_pipeline_from()` re-executes from that agent with human feedback injected into the prompts

**State writes:** `review_package`, `status --> AWAITING_HUMAN_VALIDATION`

---

### Phase F -- Finalization and Delivery

#### F1 -- Final Readiness and Submission Agent

| Property | Value |
|---|---|
| **Class** | `FinalReadinessAgent` |
| **File** | `agents/final_readiness_agent.py` |
| **Uses LLM** | No |
| **Uses:** | `ReviewService`, `mermaid_utils`, `scripts/md_to_pdf.py` |

Combines the former F1 (readiness) and F2 (submission) roles into a single agent. Only runs after a human validation decision is recorded.

**Processing (APPROVE):**
1. Build approval package (decision brief, proposal summary, pricing summary, risk summary, coverage summary)
2. Generate final proposal markdown with E1/E2 content injected, duplicate table rows deduplicated, invalid Mermaid blocks stripped, technical parent sections collapsed
3. Render Mermaid code blocks to PNG images via `npx @mermaid-js/mermaid-cli`
4. Convert markdown to PDF via `scripts/md_to_pdf.py`
5. Compute SHA-256 hash for audit trail
6. Archive to `storage/submissions/{rfp_id}/`

**Output files:** `proposal_raw.md`, `proposal.md`, `proposal.pdf`, `diagrams/` (rendered PNGs)

**State writes:** `approval_package`, `submission_record` (output_file_path, archive_path, file_hash), `status --> SUBMITTED` or `REJECTED`

---

## Human Validation Workflow

After E1+E2 complete, the pipeline enters the human validation phase:

1. **H1 builds a `ReviewPackage`** containing source sections (from the original RFP), response sections (with E1/E2 content injected into stubs), and validation/commercial/legal summaries
2. **Pipeline pauses** at `AWAITING_HUMAN_VALIDATION` status
3. **Frontend receives** WebSocket `END` event and displays the review UI
4. **Human reviewer** can add `ReviewComment` objects anchored to specific sections or paragraphs, each with a domain (`source`, `response`, `narrative`, `commercial`, `legal`, `validation`) and optional `rerun_hint`
5. **Human submits a decision:**
   - **APPROVE** -- pipeline resumes into F1 for final readiness and submission
   - **REJECT** -- pipeline resumes into F1, which sets `REJECTED` status
   - **REQUEST_CHANGES** -- `ReviewService.compute_rerun_target()` determines the earliest agent to re-run based on comment domains and rerun hints, then `run_pipeline_from()` re-executes from that agent with human feedback injected into the LLM prompts

**Automatic rerun target mapping by comment domain:**

| Comment Domain | Rerun From |
|---|---|
| `source` | `c1_architecture_planning` |
| `response` | `c2_requirement_writing` |
| `narrative` | `c3_narrative_assembly` |
| `validation` | `d1_technical_validation` |
| `commercial` | `commercial_legal_parallel` |
| `legal` | `commercial_legal_parallel` |

When multiple comments target different agents, the system selects the earliest agent in the pipeline to ensure all downstream outputs are regenerated.

---

## Submission and PDF Generation

When the pipeline reaches F1 with an APPROVE decision:

1. **Approval package** -- compiles decision brief, proposal summary, pricing summary, risk summary, and coverage summary from pipeline state
2. **Markdown generation** -- builds the final proposal `.md` file with:
   - E1/E2 content injected (replacing `[PIPELINE_STUB]` markers from C2)
   - Duplicate table rows deduplicated (by row ID pattern matching)
   - Invalid Mermaid blocks stripped (syntax-validated before rendering)
   - Technical parent sections collapsed (e.g., "Technical Implementation Framework" merged under "Technical Implementation")
   - Internal workflow references sanitized (KB IDs, REQ IDs, section markers removed)
3. **Mermaid rendering** -- Mermaid code blocks rendered to PNG images via `npx @mermaid-js/mermaid-cli`
4. **PDF conversion** -- `scripts/md_to_pdf.py` produces the final `proposal.pdf` with professional formatting, embedded diagrams, proper table rendering, and table of contents
5. **Archival** -- SHA-256 hash computed for audit trail, files saved to `storage/submissions/{rfp_id}/`

**Output files:**

| File | Description |
|---|---|
| `proposal_raw.md` | Pre-Mermaid-rendering markdown (debug artifact) |
| `proposal.md` | Final markdown with rendered diagram image references |
| `proposal.pdf` | Submission-ready PDF |
| `diagrams/` | Rendered Mermaid PNG files |

---

## Shared Infrastructure

### BaseAgent

All agents inherit from `BaseAgent` (`agents/base_agent.py`):
- **`process(state: dict) --> dict`** -- Public entry called by LangGraph. Hydrates state, calls `_real_process()`, handles errors, manages audit trail, broadcasts WebSocket events.
- **`_real_process(state: RFPGraphState) --> RFPGraphState`** -- Abstract method each agent overrides.
- `NotImplementedError` --> Agent skipped gracefully (stubs continue pipeline).
- All other exceptions --> logged, re-raised (pipeline fails).
- Built-in debug logging: state summary on entry, state diff on exit, timing.

### Pipeline Graph and Routing

`orchestration/graph.py` wires all agents with:
- **4 conditional edges** (A2 retry, A3 go/no-go, D1 validation, E1+E2 gate)
- **4 terminal nodes** (`end_no_go`, `end_legal_block`, `escalate_structuring`, `escalate_validation`)
- **1 composite node** (`commercial_legal_parallel` -- E1+E2 sequential with fan-in gate + stub injection)
- **`_with_checkpoint` wrapper** -- saves checkpoint after each agent, handles rerun skip logic, tracks LLM calls via `LLMCallTracker`

### Checkpointing

`persistence/checkpoint.py` saves agent output as JSON files at `storage/checkpoints/{rfp_id}/{agent_name}.json` after each agent completes. Enables:
- **Re-running** from any agent without re-executing predecessors
- **Debugging** by inspecting intermediate state
- **Persistence** across server restarts (checkpoint-only runs show as `CHECKPOINTED`)
- **Pipeline error logging** via `PipelineLogCollector` (captures WARNING+ records to file)

### ReviewService

`services/review_service.py` provides:
- **`build_review_package(state)`** -- assembles source/response sections with paragraph-level anchoring
- **`build_global_feedback(package)`** -- formats open review comments as LLM-injectable feedback text
- **`build_section_feedback(package, section_id)`** -- filters feedback for a specific section
- **`compute_rerun_target(package)`** -- determines the earliest pipeline agent to re-run based on comment domains and rerun hints
- **`_sanitize_response_text(text)`** -- removes internal workflow references (KB IDs, REQ IDs, section markers) while preserving tables and Mermaid blocks

### LLM Service

`services/llm_service.py` provides:
- **`KeyRotator`** -- round-robin API key selector with per-key TPM-aware throttling (sliding-window token bucket)
- **`LLMCallTracker`** -- per-agent call count, token count, and timing statistics
- **`get_llm()`** -- returns Groq ChatModel with rotated key
- **`llm_json_call(prompt, output_model)`** -- structured output via `with_structured_output()`
- **`llm_text_call(prompt)`** -- raw text response with retry and `<think>` tag stripping
- **`llm_deterministic_call(prompt)`** -- temperature=0, top_p=1, seed=42
- **`llm_large_text_call(prompt)`** -- uses the large-context model (Llama 4 Scout)

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
| `commercial_result` | `CommercialResult` | E1 | Pricing breakdown + narrative + validation flags |
| `legal_result` | `LegalResult` | E2 | Decision + clause risks + compliance checks + narrative |
| `commercial_legal_gate` | `CommercialLegalGateResult` | Orchestration | Combined gate decision |
| `review_package` | `ReviewPackage` | H1 | Source/response sections + comments + decision |
| `approval_package` | `ApprovalPackage` | F1 | Decision brief for leadership |
| `submission_record` | `SubmissionRecord` | F1 | Archive details + file hash |
| `audit_trail` | `list[AuditEntry]` | Every agent | Timestamped action log |

---

## Governance and Decision Points

| Gate | Agent | Condition | Outcome |
|---|---|---|---|
| **Structuring Confidence** | A2 | confidence < 0.6 after 3 retries | Escalate to human, END |
| **Go / No-Go** | A3 | Policy violation or low scores | Status set to NO_GO, pipeline **continues** |
| **Technical Validation** | D1 | REJECT | Loop to C2 (max 3), then auto-pass |
| **Legal Review** | E2 | BLOCK (critical risk) | Legal Block, END |
| **Human Validation** | H1 | REJECT | REJECTED, END |
| **Human Validation** | H1 | REQUEST_CHANGES | Rerun from computed agent |

---

## Quality Metrics (Latest Run)

| Metric | Value |
|---|---|
| Requirements extracted (B1) | 88-104 depending on RFP complexity |
| Coverage quality (C2 to D1) | 90-95% full, 5-10% partial, 0% missing |
| D1 validation decision | PASS (0 critical failures, 0 warnings) |
| Pipeline completion time | ~7-8 minutes end-to-end (A1 to F1) |
| Word count (assembled proposal) | ~8,500 words across 13-15 sections |
| D1 validation checks | Completeness, alignment, realism, consistency |

---

## Configuration

All settings via `rfp_automation/config.py` using `pydantic-settings`.

**Secrets (from `.env` file):**

| Setting | Description |
|---|---|
| `groq_api_key` / `groq_api_keys` | Groq Cloud API key(s) |
| `huggingface_api_key` / `huggingface_api_keys` | HuggingFace API key(s) (VLM + embeddings) |
| `pinecone_api_key` | Pinecone API key |
| `mongodb_uri` | MongoDB connection string (default: `mongodb://localhost:27017`) |
| `aws_access_key` / `aws_secret_key` | AWS keys (optional, for S3 storage) |

**Hardcoded defaults (in `config.py`, not in `.env`):**

| Setting | Default | Description |
|---|---|---|
| `llm_model` | `qwen/qwen3-32b` | Primary LLM (A2, A3, B1, C1) -- ~32K context |
| `llm_large_model` | `meta-llama/llama-4-scout-17b-16e-instruct` | Large-context LLM (B2, C2, C3, D1, E1, E2) -- ~131K context |
| `llm_temperature` | `0.2` | Default LLM temperature |
| `llm_max_tokens` | `8192` | Max **output** tokens per LLM call |
| `llm_large_max_tokens` | `8192` | Max **output** tokens per large LLM call |
| `vlm_provider` | `huggingface` | VLM provider (`huggingface` or `groq`) |
| `vlm_model` | `Qwen/Qwen3-VL-8B-Instruct:novita` | VLM model name |
| `vlm_max_tokens` | `4096` | Max tokens per VLM call |
| `vlm_enabled` | `true` | Feature flag for VLM processing |
| `extraction_llm_temperature` | `0.0` | Deterministic LLM temperature |
| `embedding_model` | `BAAI/bge-m3` | Embedding model |
| `storage_backend` | `local` | File storage (`local` / `s3`) |
| `pinecone_index_name` | `rfp-automation-m3` | Pinecone index name |
| `max_validation_retries` | `0` | D1 validation retry limit |
| `max_structuring_retries` | `3` | A2 structuring retry limit |
| `min_validation_confidence` | `0.7` | B2 refinement trigger threshold |
| `approval_timeout_hours` | `48` | Human approval timeout |
| `extraction_dedup_similarity_threshold` | `0.99` | B1 dedup cosine threshold |
| `extraction_coverage_warn_ratio` | `0.6` | B1 coverage warning threshold |
| `extraction_min_output_headroom_ratio` | `0.40` | B1 token budget headroom |
| `extraction_min_candidate_density` | `0.15` | B1 candidate density threshold |
