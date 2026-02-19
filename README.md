# RFP Response Automation System

A multi-agent AI system that automates end-to-end RFP (Request for Proposal) responses using a LangGraph state machine with built-in governance controls.

## Deployment Architecture

Two separately deployed units — the backend is a single Docker container, the frontend is a static Next.js site.

```
┌─────────────────────────────────────────────────────────────────┐
│                        BACKEND (Docker on EC2)                  │
│                                                                 │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────────────┐    │
│  │ FastAPI   │──▶│ Orchestration│──▶│      13 Agents       │    │
│  │ (API)     │   │ (LangGraph)  │   │ (A1→A2→A3→...→F2)   │    │
│  └──────────┘   └──────────────┘   └─────────┬────────────┘    │
│       │                                       │                 │
│       │              ┌────────────────────────┘                 │
│       │              ▼                                          │
│       │    ┌──────────────────┐                                 │
│       │    │   MCP Server     │  ← module, not a separate      │
│       │    │   (MCPService)   │    service — runs in-process    │
│       │    │  ┌─────────────┐ │                                 │
│       │    │  │ RFP Store   │ │                                 │
│       │    │  │ KB          │ │                                 │
│       │    │  │ Rules       │ │                                 │
│       │    │  │ Embeddings  │ │  ← embedding, chunking, vecDB  │
│       │    │  └─────────────┘ │                                 │
│       │    └──────────────────┘                                 │
│       │                                                         │
│       ▼                                                         │
│  ┌──────────┐  ┌───────────┐  ┌───────────┐                    │
│  │ Storage  │  │  MongoDB  │  │ Pinecone  │                    │
│  │ (local)  │  │  (config) │  │ (vectors) │                    │
│  └──────────┘  └───────────┘  └───────────┘                    │
└─────────────────────────────────────────────────────────────────┘
        ▲  REST + WebSocket
        │
        ▼
┌─────────────────────────────────┐
│  FRONTEND (Vercel — planned)    │
│  Next.js + TypeScript + Tailwind│
│                                 │
│  Pages:                         │
│   • Upload    — drag & drop     │
│   • Dashboard — list all RFPs   │
│   • Status    — live progress   │
│   • Approval  — human gate UI  │
└─────────────────────────────────┘
```

### Why the MCP Server is a module, not a separate service

The MCP server is a **logical boundary** — agents only import `MCPService` and never
touch the internals (embedding, chunking, vector DB). But it runs **in the same
Python process** as the agents. There's no network hop, no separate deployment.
This keeps the system simple now. If it ever needs to scale independently,
extracting it into its own service is straightforward because the boundary is already clean.

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Groq Cloud (`llama-3.3-70b-versatile`) via `langchain-groq` |
| Orchestration | LangGraph state machine (17 nodes, 5 conditional edges) |
| Vector DB | Pinecone Serverless (AWS us-east-1, cosine similarity) |
| Embeddings | Sentence Transformers (`all-MiniLM-L6-v2`, 384 dimensions) |
| Structured DB | MongoDB (company config, certifications, pricing rules, legal templates) |
| API | FastAPI + uvicorn (async, `to_thread` for heavy I/O) |
| Real-time | WebSocket via `PipelineProgress` singleton |
| Frontend | Single-page vanilla JS dashboard (served at `/`) |
| Parsing | PyMuPDF (PDF), python-docx (DOCX) |
| Config | pydantic-settings (`.env` file) |
| Testing | pytest |

## Project Structure

```
RFP-Responder/
├── Documentation/
│   ├── project-description.md           # Full system spec
│   ├── data-flow.md                     # Pipeline walkthrough (file by file)
│   └── implementation-plan.md           # Phased plan + current status
│
├── rfp_automation/                      # ═══ BACKEND (all in one Docker) ═══
│   ├── __init__.py                      # Package marker
│   ├── __main__.py                      # CLI entry: python -m rfp_automation
│   ├── config.py                        # Centralised config (pydantic-settings + .env)
│   ├── main.py                          # run() + serve() entry points
│   │
│   ├── api/                             # ── HTTP Layer (frontend talks to this) ──
│   │   ├── __init__.py                  # FastAPI app factory (create_app + app + event-loop setup)
│   │   ├── routes.py                    # RFP endpoints (upload, status, approve, list, WS)
│   │   ├── knowledge_routes.py          # KB endpoints (upload, status, query, seed, files)
│   │   └── websocket.py                 # PipelineProgress singleton (real-time WS broadcast)
│   │
│   ├── models/                          # ── Data Layer ──
│   │   ├── enums.py                     # Status codes, decision types, categories
│   │   ├── state.py                     # RFPGraphState — the shared LangGraph state
│   │   └── schemas.py                   # 20+ Pydantic models for each agent's output
│   │
│   ├── agents/                          # ── Agent Layer (imports MCPService only) ──
│   │   ├── base_agent.py                # BaseAgent — abstract _real_process(), audit
│   │   ├── intake_agent.py              # A1 — IntakeAgent ✅
│   │   ├── structuring_agent.py         # A2 — StructuringAgent (stub)
│   │   ├── go_no_go_agent.py            # A3 — GoNoGoAgent (stub)
│   │   ├── requirement_extraction_agent.py  # B1 — RequirementsExtractionAgent (stub)
│   │   ├── requirement_validation_agent.py  # B2 — RequirementsValidationAgent (stub)
│   │   ├── architecture_agent.py        # C1 — ArchitecturePlanningAgent (stub)
│   │   ├── writing_agent.py             # C2 — RequirementWritingAgent (stub)
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
│   │   │   ├── rfp_store.py             # RFP Vector Store (Pinecone, real)
│   │   │   └── knowledge_store.py       # Company KB (Pinecone + MongoDB, real)
│   │   ├── rules/
│   │   │   ├── policy_rules.py          # Hard disqualification rules (A3)
│   │   │   ├── validation_rules.py      # Prohibited language checks (D1)
│   │   │   ├── commercial_rules.py      # Pricing validation (E1)
│   │   │   └── legal_rules.py           # Commercial+Legal gate logic (E1+E2)
│   │   ├── schema/
│   │   │   ├── capability_schema.py     # Capability model
│   │   │   ├── pricing_schema.py        # PricingParameters model
│   │   │   └── requirement_schema.py    # ExtractedRequirement model
│   │   └── embeddings/
│   │       └── embedding_model.py       # Sentence Transformers wrapper (real)
│   │
│   ├── services/                        # ── Business Services ──
│   │   ├── file_service.py              # Local / S3 file operations
│   │   ├── parsing_service.py           # PDF / DOCX text extraction + chunking
│   │   ├── storage_service.py           # Coordinates file + state persistence
│   │   └── audit_service.py             # Audit trail recording (in-memory)
│   │
│   ├── persistence/                     # ── Data Persistence ──
│   │   ├── mongo_client.py              # MongoDB connection wrapper (real)
│   │   └── state_repository.py          # State persistence (in-memory, MongoDB TODO)
│   │
│   ├── orchestration/                   # ── LangGraph Pipeline ──
│   │   ├── graph.py                     # State machine (17 nodes + edges + run_pipeline)
│   │   └── transitions.py              # Conditional routing (5 decision functions)
│   │
│   ├── prompts/                         # ── LLM Prompt Templates ──
│   │   ├── extraction_prompt.txt        # B1 requirement extraction
│   │   ├── architecture_prompt.txt      # C1 architecture planning
│   │   ├── go_no_go_prompt.txt          # A3 go/no-go analysis
│   │   ├── structuring_prompt.txt       # A2 section classification
│   │   ├── legal_prompt.txt             # E2 legal review
│   │   ├── writing_prompt.txt           # C2 response writing
│   │   └── validation_prompt.txt        # D1 technical validation
│   │
│   ├── utils/
│   │   ├── logger.py                    # Logging setup
│   │   └── hashing.py                   # SHA-256 hashing
│   │
│   └── tests/
│       ├── test_agents.py               # Per-agent unit tests (4 tests)
│       ├── test_pipeline.py             # End-to-end pipeline tests (1 test)
│       └── test_rules.py                # MCP rule layer tests (11 tests)
│
├── example_docs/                        # Sample RFP documents for testing
│   └── Telecom RFP Document.pdf         # 14-page telecom UC RFP
│
├── frontend/                            # ═══ FRONTEND (served by FastAPI at /) ═══
│   ├── index.html                       # Single-page dashboard (vanilla JS + CSS)
│   └── README.md                        # Frontend documentation
│
├── storage/                             # Local file storage directory
├── requirements.txt
├── .env.example
└── README.md
```

## Quick Start

```bash
# 1. Create virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and configure environment
copy .env.example .env
# Edit .env with your real API keys:
#   GROQ_API_KEY     — required for LLM calls
#   PINECONE_API_KEY — required for vector storage
#   MONGODB_URI      — required for company config

# 4. Run the pipeline on a file
python -m rfp_automation "example_docs/Telecom RFP Document.pdf"

# 5. Or start the API server (for frontend integration)
python -m rfp_automation --serve      # → http://localhost:8000/docs
uvicorn rfp_automation.api:app --reload

# 6. Run tests
pytest rfp_automation/tests/ -v
```

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | Yes | — | Groq Cloud API key for LLM calls |
| `PINECONE_API_KEY` | Yes | — | Pinecone API key for vector storage |
| `MONGODB_URI` | Yes | `mongodb://localhost:27017` | MongoDB connection string |
| `MONGODB_DATABASE` | No | `rfp_automation` | MongoDB database name |
| `LLM_MODEL` | No | `llama-3.3-70b-versatile` | Groq model name |
| `PINECONE_INDEX_NAME` | No | `rfp-automation` | Pinecone index name |
| `PINECONE_CLOUD` | No | `aws` | Pinecone serverless cloud |
| `PINECONE_REGION` | No | `us-east-1` | Pinecone serverless region |
| `EMBEDDING_MODEL` | No | `all-MiniLM-L6-v2` | Sentence Transformers model |
| `STORAGE_BACKEND` | No | `local` | `local` or `s3` |
| `LOCAL_STORAGE_PATH` | No | `./storage` | Local file storage directory |
| `API_HOST` | No | `0.0.0.0` | API server bind host |
| `API_PORT` | No | `8000` | API server bind port |
| `MAX_VALIDATION_RETRIES` | No | `3` | D1→C3 retry loop limit |
| `MAX_STRUCTURING_RETRIES` | No | `3` | A2 confidence retry limit |
| `LOG_LEVEL` | No | `INFO` | Python logging level |

## API Endpoints

### RFP Pipeline (`/api/rfp`)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check (`{status, timestamp}`) |
| POST | `/api/rfp/upload` | Upload RFP → start pipeline (background thread) → return `rfp_id` |
| GET | `/api/rfp/{rfp_id}/status` | Poll pipeline status for an RFP |
| POST | `/api/rfp/{rfp_id}/approve` | Human approval gate (APPROVE / REJECT) |
| GET | `/api/rfp/list` | List all pipeline runs |
| WS | `/api/rfp/ws/{rfp_id}` | Real-time pipeline progress (node_start, node_end, error, pipeline_end) |

### Knowledge Base (`/api/knowledge`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/knowledge/upload` | Upload company doc → auto-classify → embed + store (async) |
| GET | `/api/knowledge/status` | Pinecone + MongoDB stats (async) |
| POST | `/api/knowledge/query` | Semantic query with optional `doc_type` filter (async) |
| POST | `/api/knowledge/seed` | Seed KB from JSON files (async) |
| GET | `/api/knowledge/files` | List all uploaded KB documents with classified types |

Swagger UI at `/docs`, ReDoc at `/redoc`. CORS configured for all origins.
Dashboard served at `/` (single-page HTML from `frontend/index.html`).

## Pipeline Flow

```
A1 Intake → A2 Structuring → A3 Go/No-Go ──→ END (NO_GO)
                 │ low                │ GO
                 │ confidence         ▼
                 ├──→ retry (≤3x)    B1 Req Extraction
                 └──→ ESCALATE       → B2 Req Validation
                                     → C1 Architecture
                                     → C2 Writing
                                     → C3 Assembly
                                        │
                                        ▼
                                    D1 Validation
                                    │ REJECT (≤3x)
                                    ├──→ C3 (retry)
                                    │ PASS
                                    ▼
                            commercial_legal_parallel
                                E1 Commercial ┐
                                E2 Legal      ┤
                                              │
                                        BLOCK → END
                                        CLEAR ↓
                                        F1 Readiness
                                            │
                                    Human Approval Gate
                                        REJECT → END
                                        APPROVE ↓
                                        F2 Submission → END (SUBMITTED)
```

### Orchestration Details

The pipeline is a compiled LangGraph `StateGraph` with **17 nodes** and **5 conditional edges**:

- **A2 structuring** retries up to 3 times if confidence is below 0.6, then escalates
- **A3 go/no-go** terminates the pipeline if the decision is NO_GO
- **D1 technical validation** loops back to C3 narrative assembly on REJECT (up to 3 retries), then escalates
- **E1+E2 commercial/legal parallel** runs sequentially in one node (LangGraph `Send()` refactor planned); BLOCK terminates
- **F1 final readiness** gates on human APPROVE/REJECT

Routing logic lives in `rfp_automation/orchestration/transitions.py`.

## Agent Implementation Status

| Agent | Status | Description |
|---|---|---|
| A1 IntakeAgent | ✅ **Implemented** | File validation, PDF/DOCX parsing, Pinecone embedding, metadata extraction, WebSocket progress |
| A2 StructuringAgent | ✅ **Implemented** | LLM-based section classification with confidence scoring |
| A3 GoNoGoAgent | ⬜ Stub | `NotImplementedError` — needs LLM + policy rules evaluation |
| B1 RequirementsExtractionAgent | ⬜ Stub | `NotImplementedError` — needs LLM requirement extraction |
| B2 RequirementsValidationAgent | ⬜ Stub | `NotImplementedError` — needs validation rules check |
| C1 ArchitecturePlanningAgent | ⬜ Stub | `NotImplementedError` — needs LLM architecture design |
| C2 RequirementWritingAgent | ⬜ Stub | `NotImplementedError` — needs LLM response writing |
| C3 NarrativeAssemblyAgent | ⬜ Stub | `NotImplementedError` — needs LLM narrative assembly |
| D1 TechnicalValidationAgent | ⬜ Stub | `NotImplementedError` — needs LLM + validation rules |
| E1 CommercialAgent | ⬜ Stub | `NotImplementedError` — needs LLM + commercial rules |
| E2 LegalAgent | ⬜ Stub | `NotImplementedError` — needs LLM + legal rules |
| F1 FinalReadinessAgent | ⬜ Stub | `NotImplementedError` — needs approval package assembly |
| F2 SubmissionAgent | ⬜ Stub | `NotImplementedError` — needs document generation + delivery |

### Implementing an Agent

Every agent inherits from `BaseAgent` which provides a single abstract method `_real_process(state)`. LangGraph calls `process(state_dict)` → hydrates `RFPGraphState` → calls `_real_process()` → appends audit entry → returns `model_dump()`.

```python
# Example: rfp_automation/agents/requirement_extraction_agent.py
from pathlib import Path
from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState
from rfp_automation.mcp import MCPService
from rfp_automation.services.llm_service import llm_json_call

class RequirementsExtractionAgent(BaseAgent):
    name = AgentName.B1_REQUIREMENTS_EXTRACTION

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        mcp = MCPService()

        # 1. Query embedded RFP chunks for requirement-related sections
        chunks = mcp.query_rfp("requirements", rfp_id=state.rfp_metadata.rfp_id)

        # 2. Load prompt template
        prompt_path = Path(__file__).parent.parent / "prompts" / "extraction_prompt.txt"
        prompt_template = prompt_path.read_text()

        # 3. Call LLM via Groq (structured JSON output)
        result = llm_json_call(prompt_template, context=chunks, schema=RequirementList)

        # 4. Update state
        state.requirements = result.requirements
        return state
```

## Service Responsibilities

| Service | What it does |
|---|---|
| `MCPService` | Facade over all MCP layers — the only import agents need |
| `RFPVectorStore` | Pinecone-backed: chunk + embed + upsert RFP documents, semantic query |
| `KnowledgeStore` | Pinecone for capabilities/proposals + MongoDB for certs/pricing/legal (query_all_types, query_by_type) |
| `PipelineProgress` | WebSocket broadcast singleton — agents emit node_start/node_end/error events in real-time |
| `PolicyRules` | Hard disqualification checks: required certifications, contract value limits |
| `ValidationRules` | Prohibited language detection, SLA compliance checks |
| `CommercialRules` | Pricing margin validation, max contract value enforcement |
| `LegalRules` | Combined E1+E2 gate: clause scoring, BLOCK/CLEAR/CONDITIONAL decisions |
| `ParsingService` | PDF (PyMuPDF) / DOCX (python-docx) → text extraction + overlapping chunking |
| `EmbeddingModel` | Sentence Transformers `all-MiniLM-L6-v2` → 384-dim vectors |
| `FileService` | Save/load files to local disk (S3 backend planned) |
| `StorageService` | Coordinates `FileService` + `StateRepository` |
| `AuditService` | In-memory audit trail recording (MongoDB persistence planned) |
| `StateRepository` | In-memory state versioning per RFP (MongoDB persistence planned) |
| `MongoClient` | MongoDB connection wrapper (used by KnowledgeStore) |

## Governance Checkpoints

| Point | Agent | Condition | Outcome |
|---|---|---|---|
| Structuring confidence | A2 | confidence < 0.6 after 3 retries | Escalate to human |
| Go / No-Go | A3 | Policy violation or low scores | Pipeline END (NO_GO) |
| Technical validation | D1 | REJECT | Loop to C3 (max 3x), then escalate |
| Legal veto | E2 | BLOCK (critical risk) | Pipeline END (LEGAL_BLOCK) |
| Human approval | F1 | REJECT | Pipeline END (REJECTED) |

## Tests

```bash
pytest rfp_automation/tests/ -v
```

| Test File | Tests | Coverage |
|---|---|---|
| `test_agents.py` | 4 | Intake agent validation (missing file, no path, stub agents) |
| `test_pipeline.py` | 1 | Pipeline halts at A1 for non-existent file |
| `test_rules.py` | 11 | Policy rules, validation rules, commercial rules, legal gate logic |

## Documentation

- **[Documentation/project-description.md](Documentation/project-description.md)** — Full system specification
- **[Documentation/data-flow.md](Documentation/data-flow.md)** — Pipeline walkthrough, file by file
- **[Documentation/implementation-plan.md](Documentation/implementation-plan.md)** — Phased plan with current status
