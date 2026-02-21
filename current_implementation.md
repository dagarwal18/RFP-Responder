# RFP Responder Codebase Dump

## File: `.env`

```bash
# API Server
API_HOST=0.0.0.0
API_PORT=8000

# LLM (Groq Cloud)
GROQ_API_KEY=gsk_your-groq-api-key-here
LLM_MODEL=llama-3.3-70b-versatile

# MongoDB (company config, rules, audit)
MONGODB_URI=mongodb+srv://user:password@cluster0.example.net/?appName=Cluster0
MONGODB_DATABASE=rfp_automation

# Storage
STORAGE_BACKEND=local
LOCAL_STORAGE_PATH=./storage

# Pinecone Vector DB (serverless)
PINECONE_API_KEY=your-pinecone-api-key-here
PINECONE_INDEX_NAME=rfp-automation
PINECONE_CLOUD=aws
PINECONE_REGION=us-east-1

# Embeddings (first run downloads ~80 MB model)
EMBEDDING_MODEL=all-MiniLM-L6-v2

# Knowledge Data (optional: override path to seed JSON files)
# KNOWLEDGE_DATA_PATH=

# Pipeline
MAX_VALIDATION_RETRIES=3
MAX_STRUCTURING_RETRIES=3

# Logging
LOG_LEVEL=INFO

```

## File: `.env.example`

```
# API Server
API_HOST=0.0.0.0
API_PORT=8000

# LLM (Groq Cloud)
GROQ_API_KEY=gsk_your-key-here
LLM_MODEL=llama-3.3-70b-versatile

# MongoDB (company config, rules, audit)
MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=rfp_automation

# Storage
STORAGE_BACKEND=local
LOCAL_STORAGE_PATH=./storage

# Pinecone Vector DB (serverless)
PINECONE_API_KEY=your-pinecone-key-here
PINECONE_INDEX_NAME=rfp-automation
PINECONE_CLOUD=aws
PINECONE_REGION=us-east-1

# Embeddings (first run downloads ~80 MB model)
EMBEDDING_MODEL=all-MiniLM-L6-v2

# Knowledge Data (optional: override path to seed JSON files)
# KNOWLEDGE_DATA_PATH=

# Pipeline
MAX_VALIDATION_RETRIES=3
MAX_STRUCTURING_RETRIES=3

# Logging
LOG_LEVEL=INFO

```

## File: `.gitignore`

```bash
.venv
.pytest_cache
__pycache__
.env
storage/
uvicorn

```

## File: `README.md`

```markdown
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

```

## File: `requirements.txt`

```text
# ── Core ─────────────────────────────────────────────────
pydantic>=2.12.5,<3.0
pydantic-settings>=2.13.0,<3.0

# ── API Server ───────────────────────────────────────────
fastapi>=0.129.0
uvicorn[standard]>=0.41.0
python-multipart>=0.0.22        # required for FastAPI file uploads
websockets>=16.0                # WebSocket support for uvicorn

# ── Orchestration ────────────────────────────────────────
langgraph>=1.0.8
langchain>=1.2.10

# ── LLM Provider (Groq Cloud) ───────────────────────────
langchain-groq>=1.1.2           # lazy-loaded in llm_service.py

# ── Document Parsing ────────────────────────────────────
PyMuPDF>=1.27.1                 # PDF text extraction (used by ParsingService)
python-docx>=1.1.0              # DOCX text extraction (lazy-loaded in ParsingService)

# ── Embeddings ───────────────────────────────────────────
sentence-transformers>=5.2.3    # used by EmbeddingModel (all-MiniLM-L6-v2)
torch>=2.10.0                   # PyTorch backend for sentence-transformers

# ── Vector DB (Pinecone) ────────────────────────────────
pinecone>=8.0.1                 # renamed from pinecone-client in v8

# ── Persistence ──────────────────────────────────────────
pymongo>=4.8.0                  # MongoDB (KnowledgeStore, rules_config, mongo_client)

# ── Utilities ────────────────────────────────────────────
python-dotenv>=1.2.1            # .env file loading for pydantic-settings

# ── Testing ──────────────────────────────────────────────
pytest>=9.0.2

```

## File: `uvicorn`

```bash

```

## File: `frontend\index.html`

```html
<!DOCTYPE html>
<html lang="en">

<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>RFP Responder — Dashboard</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {
      --bg-primary: #0a0e1a;
      --bg-secondary: #111827;
      --bg-card: rgba(17, 24, 39, 0.8);
      --bg-card-hover: rgba(31, 41, 55, 0.9);
      --border: rgba(75, 85, 99, 0.4);
      --border-accent: rgba(99, 102, 241, 0.5);
      --text-primary: #f9fafb;
      --text-secondary: #9ca3af;
      --text-muted: #6b7280;
      --accent: #6366f1;
      --accent-light: #818cf8;
      --accent-glow: rgba(99, 102, 241, 0.15);
      --success: #10b981;
      --warning: #f59e0b;
      --error: #ef4444;
      --info: #3b82f6;
      --radius: 12px;
      --radius-sm: 8px;
      --shadow: 0 4px 24px rgba(0, 0, 0, 0.3);
      --transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    }

    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }

    body {
      font-family: 'Inter', -apple-system, sans-serif;
      background: var(--bg-primary);
      color: var(--text-primary);
      min-height: 100vh;
      overflow-x: hidden;
    }

    /* background gradient */
    body::before {
      content: '';
      position: fixed;
      top: -50%;
      left: -50%;
      width: 200%;
      height: 200%;
      background: radial-gradient(ellipse at 30% 20%, rgba(99, 102, 241, 0.08) 0%, transparent 50%),
        radial-gradient(ellipse at 70% 80%, rgba(16, 185, 129, 0.05) 0%, transparent 50%);
      z-index: 0;
      pointer-events: none;
    }

    /* ── Header ────────────────────────────────────── */
    .header {
      position: sticky;
      top: 0;
      z-index: 100;
      background: rgba(10, 14, 26, 0.85);
      backdrop-filter: blur(20px);
      border-bottom: 1px solid var(--border);
      padding: 0 32px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      height: 64px;
    }

    .header h1 {
      font-size: 18px;
      font-weight: 600;
      background: linear-gradient(135deg, var(--accent-light), var(--success));
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }

    .header .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--success);
      box-shadow: 0 0 8px var(--success);
      display: inline-block;
      margin-right: 8px;
    }

    .header .api-status {
      font-size: 13px;
      color: var(--text-secondary);
      display: flex;
      align-items: center;
      gap: 6px;
    }

    /* ── Main layout ───────────────────────────────── */
    .main {
      position: relative;
      z-index: 1;
      max-width: 1400px;
      margin: 0 auto;
      padding: 24px 32px 64px;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 24px;
    }

    @media (max-width: 900px) {
      .main {
        grid-template-columns: 1fr;
      }
    }

    /* ── Cards ──────────────────────────────────────── */
    .card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      backdrop-filter: blur(12px);
      box-shadow: var(--shadow);
      transition: var(--transition);
      overflow: hidden;
    }

    .card:hover {
      border-color: var(--border-accent);
    }

    .card-header {
      padding: 20px 24px 16px;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .card-header h2 {
      font-size: 16px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .card-header .badge {
      font-size: 11px;
      font-weight: 500;
      padding: 3px 10px;
      border-radius: 20px;
      background: var(--accent-glow);
      color: var(--accent-light);
      border: 1px solid rgba(99, 102, 241, 0.3);
    }

    .card-body {
      padding: 20px 24px;
    }

    /* ── Dropzone ───────────────────────────────────── */
    .dropzone {
      border: 2px dashed var(--border);
      border-radius: var(--radius-sm);
      padding: 32px 20px;
      text-align: center;
      cursor: pointer;
      transition: var(--transition);
      position: relative;
    }

    .dropzone:hover,
    .dropzone.drag-over {
      border-color: var(--accent);
      background: var(--accent-glow);
    }

    .dropzone input {
      display: none;
    }

    .dropzone .icon {
      font-size: 32px;
      margin-bottom: 8px;
      opacity: 0.6;
    }

    .dropzone .label {
      font-size: 14px;
      color: var(--text-secondary);
    }

    .dropzone .label strong {
      color: var(--accent-light);
    }

    /* ── Select / Buttons ──────────────────────────── */
    .form-row {
      display: flex;
      gap: 10px;
      margin-top: 14px;
      align-items: center;
    }

    select,
    .btn {
      font-family: inherit;
      font-size: 13px;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--bg-secondary);
      color: var(--text-primary);
      padding: 8px 14px;
      outline: none;
      transition: var(--transition);
    }

    select:focus {
      border-color: var(--accent);
    }

    .btn {
      cursor: pointer;
      font-weight: 500;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }

    .btn-primary {
      background: linear-gradient(135deg, var(--accent) 0%, #4f46e5 100%);
      border-color: transparent;
      color: #fff;
    }

    .btn-primary:hover {
      box-shadow: 0 0 20px rgba(99, 102, 241, 0.4);
      transform: translateY(-1px);
    }

    .btn-primary:disabled {
      opacity: 0.5;
      cursor: not-allowed;
      transform: none;
      box-shadow: none;
    }

    .btn-outline {
      background: transparent;
    }

    .btn-outline:hover {
      background: rgba(99, 102, 241, 0.1);
      border-color: var(--accent);
    }

    .btn-sm {
      padding: 6px 12px;
      font-size: 12px;
    }

    /* ── Stats grid ─────────────────────────────────── */
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      margin-top: 16px;
    }

    .stat-box {
      background: var(--bg-secondary);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 14px;
      text-align: center;
    }

    .stat-box .stat-value {
      font-size: 22px;
      font-weight: 700;
      background: linear-gradient(135deg, var(--accent-light), var(--success));
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }

    .stat-box .stat-label {
      font-size: 11px;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-top: 4px;
    }

    /* ── Query input ────────────────────────────────── */
    .query-row {
      display: flex;
      gap: 10px;
      margin-top: 16px;
    }

    .query-row input {
      flex: 1;
      font-family: inherit;
      font-size: 13px;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--bg-secondary);
      color: var(--text-primary);
      padding: 8px 14px;
      outline: none;
    }

    .query-row input:focus {
      border-color: var(--accent);
    }

    /* ── Pipeline stepper ──────────────────────────── */
    .pipeline-stepper {
      display: flex;
      flex-direction: column;
      gap: 0;
      margin-top: 16px;
    }

    .step {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 10px 14px;
      border-left: 2px solid var(--border);
      position: relative;
      transition: var(--transition);
    }

    .step::before {
      content: '';
      width: 10px;
      height: 10px;
      border-radius: 50%;
      border: 2px solid var(--border);
      background: var(--bg-primary);
      flex-shrink: 0;
      transition: var(--transition);
      margin-left: -6px;
    }

    .step.active {
      border-left-color: var(--accent);
    }

    .step.active::before {
      border-color: var(--accent);
      background: var(--accent);
      box-shadow: 0 0 8px var(--accent);
    }

    .step.complete {
      border-left-color: var(--success);
    }

    .step.complete::before {
      border-color: var(--success);
      background: var(--success);
    }

    .step.failed {
      border-left-color: var(--error);
    }

    .step.failed::before {
      border-color: var(--error);
      background: var(--error);
    }

    .step-label {
      font-size: 13px;
      font-weight: 500;
      color: var(--text-secondary);
    }

    .step.active .step-label {
      color: var(--text-primary);
    }

    .step.complete .step-label {
      color: var(--success);
    }

    .step.failed .step-label {
      color: var(--error);
    }

    .step-detail {
      font-size: 11px;
      color: var(--text-muted);
      margin-top: 2px;
    }

    /* ── Logs ───────────────────────────────────────── */
    .log-box {
      margin-top: 16px;
      background: var(--bg-secondary);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 14px 16px;
      max-height: 200px;
      overflow-y: auto;
      font-size: 12px;
      line-height: 1.7;
      font-family: 'Cascadia Code', 'Fira Code', monospace;
      color: var(--text-secondary);
    }

    .log-box:empty::after {
      content: 'No activity yet...';
      color: var(--text-muted);
      font-style: italic;
    }

    .log-entry {
      display: flex;
      gap: 8px;
    }

    .log-time {
      color: var(--text-muted);
      flex-shrink: 0;
    }

    .log-msg {
      word-break: break-word;
    }

    .log-msg.success {
      color: var(--success);
    }

    .log-msg.error {
      color: var(--error);
    }

    .log-msg.info {
      color: var(--info);
    }

    /* ── Query results ─────────────────────────────── */
    .query-results {
      margin-top: 12px;
      max-height: 200px;
      overflow-y: auto;
    }

    .query-result-item {
      padding: 10px 14px;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      margin-bottom: 8px;
      background: var(--bg-secondary);
      font-size: 12px;
      line-height: 1.5;
    }

    .query-result-item .score {
      color: var(--accent-light);
      font-weight: 600;
    }

    .query-result-item .text {
      color: var(--text-secondary);
      margin-top: 4px;
    }

    /* ── Spinner ────────────────────────────────────── */
    .spinner {
      display: inline-block;
      width: 14px;
      height: 14px;
      border: 2px solid rgba(255, 255, 255, 0.2);
      border-top-color: var(--accent-light);
      border-radius: 50%;
      animation: spin 0.6s linear infinite;
    }

    @keyframes spin {
      to {
        transform: rotate(360deg);
      }
    }

    /* fade in */
    @keyframes fadeUp {
      from {
        opacity: 0;
        transform: translateY(12px);
      }

      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    .card {
      animation: fadeUp 0.4s ease-out;
    }

    .card:nth-child(2) {
      animation-delay: 0.1s;
    }

    /* ── Runs list ──────────────────────────────────── */
    .runs-list {
      margin-top: 16px;
    }

    /* ── Auto-classified badge ──────────────────────── */
    .classified-badge {
      font-size: 11px;
      font-weight: 600;
      padding: 4px 12px;
      border-radius: 20px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .classified-badge.type-capability {
      background: rgba(99, 102, 241, 0.15);
      color: var(--accent-light);
    }

    .classified-badge.type-past_proposal {
      background: rgba(245, 158, 11, 0.15);
      color: var(--warning);
    }

    .classified-badge.type-certification {
      background: rgba(16, 185, 129, 0.15);
      color: var(--success);
    }

    .classified-badge.type-pricing {
      background: rgba(59, 130, 246, 0.15);
      color: var(--info);
    }

    .classified-badge.type-legal {
      background: rgba(239, 68, 68, 0.15);
      color: var(--error);
    }

    /* ── Filename display ──────────────────────────── */
    .file-info {
      font-size: 12px;
      color: var(--text-secondary);
      margin-top: 8px;
      padding: 6px 12px;
      background: var(--bg-secondary);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .file-info .fname {
      font-weight: 500;
      color: var(--text-primary);
    }

    .file-info .fsize {
      color: var(--text-muted);
    }

    /* ── Uploaded files list ────────────────────────── */
    .kb-files-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-top: 16px;
      margin-bottom: 8px;
    }

    .kb-files-header h3 {
      font-size: 13px;
      font-weight: 600;
      color: var(--text-secondary);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .kb-file-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px 12px;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      margin-bottom: 6px;
      background: var(--bg-secondary);
      font-size: 12px;
    }

    .kb-file-item .kb-file-name {
      font-weight: 500;
      color: var(--text-primary);
      flex: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .kb-file-item .kb-file-meta {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
      margin-left: 8px;
    }

    .kb-file-item .kb-file-chunks {
      font-size: 11px;
      color: var(--text-muted);
    }

    .type-badge {
      font-size: 10px;
      font-weight: 600;
      padding: 2px 8px;
      border-radius: 12px;
      text-transform: uppercase;
      letter-spacing: 0.3px;
    }

    .type-badge.type-capability {
      background: rgba(99, 102, 241, 0.15);
      color: var(--accent-light);
    }

    .type-badge.type-past_proposal {
      background: rgba(245, 158, 11, 0.15);
      color: var(--warning);
    }

    .type-badge.type-certification {
      background: rgba(16, 185, 129, 0.15);
      color: var(--success);
    }

    .type-badge.type-pricing {
      background: rgba(59, 130, 246, 0.15);
      color: var(--info);
    }

    .type-badge.type-legal {
      background: rgba(239, 68, 68, 0.15);
      color: var(--error);
    }

    .kb-files-list {
      max-height: 200px;
      overflow-y: auto;
    }

    .run-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 10px 14px;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      margin-bottom: 8px;
      background: var(--bg-secondary);
      cursor: pointer;
      transition: var(--transition);
    }

    .run-item:hover {
      border-color: var(--accent);
    }

    .run-item .run-id {
      font-size: 13px;
      font-weight: 500;
    }

    .run-item .run-file {
      font-size: 12px;
      color: var(--text-muted);
    }

    .run-item .run-status {
      font-size: 11px;
      font-weight: 500;
      padding: 3px 10px;
      border-radius: 20px;
    }

    .run-status.INTAKE_COMPLETE {
      background: rgba(16, 185, 129, 0.15);
      color: var(--success);
    }

    .run-status.FAILED {
      background: rgba(239, 68, 68, 0.15);
      color: var(--error);
    }

    .run-status.RUNNING {
      background: rgba(99, 102, 241, 0.15);
      color: var(--accent-light);
    }

    .run-status.STRUCTURING {
      background: rgba(245, 158, 11, 0.15);
      color: var(--warning);
    }

    /* ── Requirement Mappings Table ──────────────── */
    .mapping-summary {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 16px;
    }

    .mapping-summary .summary-pill {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 6px 14px;
      border-radius: 20px;
      font-size: 13px;
      font-weight: 600;
      border: 1px solid var(--border);
      background: var(--bg-secondary);
    }

    .summary-pill .pill-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
    }

    .mapping-scores {
      display: flex;
      gap: 16px;
      margin-bottom: 16px;
      flex-wrap: wrap;
    }

    .mapping-scores .score-item {
      background: var(--bg-secondary);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 12px 18px;
      text-align: center;
      min-width: 120px;
    }

    .score-item .score-val {
      font-size: 24px;
      font-weight: 700;
    }

    .score-item .score-lbl {
      font-size: 11px;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-top: 2px;
    }

    .mapping-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }

    .mapping-table thead th {
      padding: 10px 8px;
      text-align: left;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted);
      border-bottom: 2px solid var(--border);
      position: sticky;
      top: 0;
      background: var(--bg-card);
      z-index: 2;
    }

    .mapping-table tbody td {
      padding: 10px 8px;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }

    .mapping-table tbody tr:hover {
      background: rgba(99, 102, 241, 0.05);
    }

    .status-chip {
      display: inline-block;
      padding: 3px 10px;
      border-radius: 12px;
      font-weight: 600;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.3px;
    }

    .status-chip.ALIGNS {
      background: rgba(16, 185, 129, 0.15);
      color: #10b981;
    }

    .status-chip.VIOLATES {
      background: rgba(239, 68, 68, 0.15);
      color: #ef4444;
    }

    .status-chip.RISK {
      background: rgba(245, 158, 11, 0.15);
      color: #f59e0b;
    }

    .status-chip.NO_MATCH {
      background: rgba(107, 114, 128, 0.15);
      color: #9ca3af;
    }

    .conf-bar {
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .conf-bar-track {
      width: 50px;
      height: 5px;
      background: rgba(255,255,255,0.08);
      border-radius: 3px;
      overflow: hidden;
    }

    .conf-bar-fill {
      height: 100%;
      border-radius: 3px;
      transition: width 0.4s ease;
    }

    .conf-bar-val {
      font-size: 11px;
      color: var(--text-muted);
      min-width: 32px;
    }

    .mapping-decision-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 16px;
      border-radius: 24px;
      font-weight: 700;
      font-size: 15px;
      letter-spacing: 0.5px;
    }

    .mapping-decision-badge.GO {
      background: rgba(16, 185, 129, 0.15);
      color: #10b981;
      border: 1px solid rgba(16, 185, 129, 0.3);
    }

    .mapping-decision-badge.NO_GO {
      background: rgba(239, 68, 68, 0.15);
      color: #ef4444;
      border: 1px solid rgba(239, 68, 68, 0.3);
    }

    .mapping-filter-row {
      display: flex;
      gap: 10px;
      align-items: center;
      margin-bottom: 12px;
    }
  </style>
</head>

<body>

  <!-- ── Header ────────────────────────────────── -->
  <header class="header">
    <h1>⚡ RFP Responder</h1>
    <div class="api-status">
      <span class="status-dot" id="apiDot"></span>
      <span id="apiLabel">Connecting…</span>
    </div>
  </header>

  <!-- ── Main grid ─────────────────────────────── -->
  <main class="main">

    <!-- ═══════════ LEFT: Knowledge Base ═══════════ -->
    <div class="card">
      <div class="card-header">
        <h2>📚 Knowledge Base</h2>
        <span class="badge" id="kbBadge">—</span>
      </div>
      <div class="card-body">

        <!-- Upload -->
        <div class="dropzone" id="kbDropzone" onclick="document.getElementById('kbFile').click()">
          <input type="file" id="kbFile" accept=".pdf" />
          <div class="icon">📄</div>
          <div class="label">Drop a company doc or <strong>click to browse</strong></div>
        </div>
        <div class="file-info" id="kbFileInfo" style="display:none">
          📄 <span class="fname" id="kbFileName"></span>
          <span class="fsize" id="kbFileSize"></span>
        </div>
        <div class="form-row">
          <span id="kbClassifiedType" class="classified-badge" style="display:none"></span>
          <button class="btn btn-primary" id="kbUploadBtn" disabled>
            Upload to KB
          </button>
          <button class="btn btn-outline btn-sm" id="kbSeedBtn">
            🌱 Seed from JSON
          </button>
        </div>

        <!-- Stats -->
        <div class="stats-grid" id="kbStats">
          <div class="stat-box">
            <div class="stat-value" id="kbVectors">—</div>
            <div class="stat-label">Vectors</div>
          </div>
          <div class="stat-box">
            <div class="stat-value" id="kbNamespaces">—</div>
            <div class="stat-label">Namespaces</div>
          </div>
          <div class="stat-box">
            <div class="stat-value" id="kbConfigs">—</div>
            <div class="stat-label">Configs</div>
          </div>
        </div>

        <!-- Uploaded Files -->
        <div class="kb-files-header">
          <h3>📁 Uploaded Documents</h3>
          <button class="btn btn-outline btn-sm" id="kbRefreshFilesBtn"
            style="padding:3px 8px;font-size:11px">🔄</button>
        </div>
        <div class="kb-files-list" id="kbFilesList">
          <div style="padding:8px;color:var(--text-muted);font-size:12px">No uploads yet.</div>
        </div>

        <!-- Query -->
        <div class="query-row">
          <input type="text" id="kbQueryInput" placeholder="Test query against knowledge base…" />
          <select id="kbQueryType" style="width:auto;min-width:90px">
            <option value="">All Types</option>
            <option value="capability">Capability</option>
            <option value="past_proposal">Past Proposal</option>
            <option value="certification">Certification</option>
            <option value="pricing">Pricing</option>
            <option value="legal">Legal</option>
          </select>
          <button class="btn btn-outline btn-sm" id="kbQueryBtn">🔍 Query</button>
        </div>
        <div class="query-results" id="kbQueryResults"></div>

        <!-- Log -->
        <div class="log-box" id="kbLog"></div>
      </div>
    </div>

    <!-- ═══════════ RIGHT: RFP Pipeline ═══════════ -->
    <div class="card">
      <div class="card-header">
        <h2>🚀 RFP Pipeline</h2>
        <span class="badge" id="rfpBadge">Ready</span>
      </div>
      <div class="card-body">

        <!-- Upload -->
        <div class="dropzone" id="rfpDropzone" onclick="document.getElementById('rfpFile').click()">
          <input type="file" id="rfpFile" accept=".pdf" />
          <div class="icon">📑</div>
          <div class="label">Drop an RFP document or <strong>click to browse</strong></div>
        </div>
        <div class="file-info" id="rfpFileInfo" style="display:none">
          📑 <span class="fname" id="rfpFileName"></span>
          <span class="fsize" id="rfpFileSize"></span>
        </div>
        <div class="form-row">
          <button class="btn btn-primary" id="rfpUploadBtn" disabled>
            Run Pipeline
          </button>
          <button class="btn btn-outline btn-sm" id="rfpRefreshBtn">
            🔄 Refresh Runs
          </button>
        </div>

        <!-- Pipeline progress -->
        <div class="pipeline-stepper" id="pipelineStepper">
          <!-- steps injected by JS -->
        </div>

        <!-- Recent runs -->
        <div class="runs-list" id="runsList"></div>

        <!-- Log -->
        <div class="log-box" id="rfpLog"></div>
      </div>
    </div>

    <!-- ═══════════════════════════════════════════════════ -->
    <!--  COMPANY POLICIES PANEL                             -->
    <!-- ═══════════════════════════════════════════════════ -->
    <div class="card" style="margin-top:20px">
      <div class="card-header">
        <h2>📜 Company Policies</h2>
        <div style="display:flex;gap:8px;align-items:center">
          <select id="policyCategoryFilter"
            style="padding:4px 8px;border-radius:6px;border:1px solid var(--border);background:var(--surface-2);color:var(--text);font-size:12px">
            <option value="">All Categories</option>
            <option value="certification">Certification</option>
            <option value="legal">Legal</option>
            <option value="compliance">Compliance</option>
            <option value="operational">Operational</option>
            <option value="commercial">Commercial</option>
            <option value="governance">Governance</option>
            <option value="capability">Capability</option>
          </select>
          <button class="btn btn-primary btn-sm" id="addPolicyBtn">+ Add Policy</button>
          <button class="btn btn-outline btn-sm" id="deleteAllPoliciesBtn" style="color:#ef4444;border-color:#ef4444">🗑 Delete All</button>
        </div>
      </div>
      <div class="card-body">
        <div id="policiesContainer" style="max-height:400px;overflow-y:auto">
          <table style="width:100%;border-collapse:collapse;font-size:13px" id="policiesTable">
            <thead>
              <tr style="text-align:left;border-bottom:1px solid var(--border)">
                <th style="padding:8px 6px;width:40%">Policy</th>
                <th style="padding:8px 6px">Category</th>
                <th style="padding:8px 6px">Severity</th>
                <th style="padding:8px 6px">Source</th>
                <th style="padding:8px 6px;width:100px">Actions</th>
              </tr>
            </thead>
            <tbody id="policiesTableBody">
              <tr>
                <td colspan="5" style="padding:16px;text-align:center;color:var(--text-muted)">Loading policies…</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════════════════════════════ -->
    <!--  ADD/EDIT POLICY MODAL                              -->
    <!-- ═══════════════════════════════════════════════════ -->
    <div id="policyModal"
      style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:1000;align-items:center;justify-content:center">
      <div
        style="background:var(--card-bg);border-radius:12px;padding:24px;max-width:500px;width:90%;border:1px solid var(--border)">
        <h3 id="policyModalTitle" style="margin:0 0 16px">Add Policy</h3>
        <input type="hidden" id="policyEditId" />
        <div style="display:flex;flex-direction:column;gap:10px">
          <textarea id="policyTextInput" rows="3" placeholder="Policy text…"
            style="padding:8px;border-radius:6px;border:1px solid var(--border);background:var(--surface-2);color:var(--text);font-size:13px;resize:vertical"></textarea>
          <div style="display:flex;gap:8px">
            <select id="policyCatInput"
              style="flex:1;padding:6px;border-radius:6px;border:1px solid var(--border);background:var(--surface-2);color:var(--text);font-size:12px">
              <option value="capability">Capability</option>
              <option value="certification">Certification</option>
              <option value="legal">Legal</option>
              <option value="compliance">Compliance</option>
              <option value="operational">Operational</option>
              <option value="commercial">Commercial</option>
              <option value="governance">Governance</option>
            </select>
            <select id="policySevInput"
              style="flex:1;padding:6px;border-radius:6px;border:1px solid var(--border);background:var(--surface-2);color:var(--text);font-size:12px">
              <option value="medium">Medium</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="low">Low</option>
            </select>
          </div>
          <input id="policySectionInput" placeholder="Source section (optional)"
            style="padding:8px;border-radius:6px;border:1px solid var(--border);background:var(--surface-2);color:var(--text);font-size:13px" />
          <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:8px">
            <button class="btn btn-outline btn-sm" onclick="closePolicyModal()">Cancel</button>
            <button class="btn btn-primary btn-sm" id="policySaveBtn" onclick="savePolicy()">Save</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════════════════════════════ -->
    <!--  REQUIREMENT MAPPINGS                               -->
    <!-- ═══════════════════════════════════════════════════ -->
    <div class="card" style="margin-top:20px" id="mappingsCard">
      <div class="card-header">
        <h2>📋 Requirement Mappings</h2>
        <div style="display:flex;gap:8px;align-items:center">
          <span style="font-size:12px;color:var(--text-muted)" id="mappingsHint">Run a pipeline or select a completed run</span>
          <span class="mapping-decision-badge" id="mappingDecisionBadge" style="display:none"></span>
        </div>
      </div>
      <div class="card-body">
        <div id="mappingsContainer">
          <div style="padding:24px;text-align:center;color:var(--text-muted);font-size:13px">
            No requirement mappings available. Upload an RFP and run the pipeline to see how each requirement maps to your company policies.
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════════════════════════════ -->
    <!--  AGENT OUTPUT LOGS                                  -->
    <!-- ═══════════════════════════════════════════════════ -->
    <div class="card" style="margin-top:20px">
      <div class="card-header">
        <h2>🤖 Agent Output Logs</h2>
        <span style="font-size:12px;color:var(--text-muted)" id="agentLogsHint">Select a completed pipeline run to view
          agent outputs</span>
      </div>
      <div class="card-body">
        <div id="agentLogsContainer">
          <div style="padding:16px;text-align:center;color:var(--text-muted);font-size:13px">
            No agent logs loaded. Click a pipeline run above to view its agent outputs.
          </div>
        </div>
      </div>
    </div>

  </main>

  <script>
    // ── Config ─────────────────────────────────────
    const API = 'http://localhost:8000';
    const WS_BASE = API.replace(/^http/, 'ws');

    // ── Pipeline stages ────────────────────────────
    const STAGES = [
      { key: 'A1_INTAKE', label: 'A1 — Intake', status: 'INTAKE_COMPLETE' },
      { key: 'A2_STRUCTURING', label: 'A2 — Structuring', status: 'STRUCTURING' },
      { key: 'A3_GO_NO_GO', label: 'A3 — Go / No-Go', status: 'GO_NO_GO' },
      { key: 'B1_REQUIREMENTS_EXTRACTION', label: 'B1 — Requirement Extract', status: 'EXTRACTING_REQUIREMENTS' },
      { key: 'B2_REQUIREMENTS_VALIDATION', label: 'B2 — Requirement Valid.', status: 'VALIDATING_REQUIREMENTS' },
      { key: 'C1_ARCHITECTURE_PLANNING', label: 'C1 — Architecture Plan', status: 'ARCHITECTURE_PLANNING' },
      { key: 'C2_REQUIREMENT_WRITING', label: 'C2 — Response Writing', status: 'WRITING_RESPONSES' },
      { key: 'C3_NARRATIVE_ASSEMBLY', label: 'C3 — Narrative Assembly', status: 'ASSEMBLING_NARRATIVE' },
      { key: 'D1_TECHNICAL_VALIDATION', label: 'D1 — Technical Validation', status: 'TECHNICAL_VALIDATION' },
      { key: 'E1_COMMERCIAL', label: 'E1 — Commercial Review', status: 'COMMERCIAL_LEGAL_REVIEW' },
      { key: 'E2_LEGAL', label: 'E2 — Legal Review', status: 'COMMERCIAL_LEGAL_REVIEW' },
      { key: 'F1_FINAL_READINESS', label: 'F1 — Final Readiness', status: 'FINAL_READINESS' },
      { key: 'F2_SUBMISSION', label: 'F2 — Submission', status: 'SUBMITTED' },
    ];

    // ── Stepper state ──────────────────────────────
    // Maps stage key → 'pending' | 'active' | 'complete' | 'failed'
    let stepperState = {};
    function resetStepperState() {
      stepperState = {};
      STAGES.forEach(s => stepperState[s.key] = 'pending');
    }
    resetStepperState();

    // ── Helper: format file size ───────────────────
    function formatSize(bytes) {
      if (bytes < 1024) return bytes + ' B';
      if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
      return (bytes / 1048576).toFixed(1) + ' MB';
    }

    // ── Helper: log to a log-box ───────────────────
    function addLog(boxId, msg, cls = '') {
      const box = document.getElementById(boxId);
      const time = new Date().toLocaleTimeString();
      const entry = document.createElement('div');
      entry.className = 'log-entry';
      entry.innerHTML = `<span class="log-time">${time}</span><span class="log-msg ${cls}">${msg}</span>`;
      box.appendChild(entry);
      box.scrollTop = box.scrollHeight;
    }

    // ── Helper: fetch with error handling ──────────
    async function apiFetch(path, opts = {}) {
      try {
        const res = await fetch(`${API}${path}`, opts);
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(err.detail || res.statusText);
        }
        return await res.json();
      } catch (e) {
        throw e;
      }
    }

    // ── Health check ───────────────────────────────
    async function checkHealth() {
      const dot = document.getElementById('apiDot');
      const label = document.getElementById('apiLabel');
      try {
        await apiFetch('/health');
        dot.style.background = 'var(--success)';
        dot.style.boxShadow = '0 0 8px var(--success)';
        label.textContent = 'API Connected';
      } catch {
        dot.style.background = 'var(--error)';
        dot.style.boxShadow = '0 0 8px var(--error)';
        label.textContent = 'API Offline';
      }
    }

    // ══════════════════════════════════════════════
    //  KNOWLEDGE BASE
    // ══════════════════════════════════════════════

    const kbFile = document.getElementById('kbFile');
    const kbUploadBtn = document.getElementById('kbUploadBtn');
    const kbDropzone = document.getElementById('kbDropzone');
    const kbFileInfo = document.getElementById('kbFileInfo');

    function showKBFile(file) {
      document.getElementById('kbFileName').textContent = file.name;
      document.getElementById('kbFileSize').textContent = `(${formatSize(file.size)})`;
      kbFileInfo.style.display = 'flex';
    }

    function hideKBFile() {
      kbFileInfo.style.display = 'none';
    }

    kbFile.addEventListener('change', () => {
      kbUploadBtn.disabled = !kbFile.files.length;
      if (kbFile.files.length) {
        showKBFile(kbFile.files[0]);
        kbDropzone.querySelector('.label').innerHTML =
          `<strong>${kbFile.files[0].name}</strong> selected`;
      } else {
        hideKBFile();
      }
    });

    // Drag & drop
    kbDropzone.addEventListener('dragover', e => { e.preventDefault(); kbDropzone.classList.add('drag-over'); });
    kbDropzone.addEventListener('dragleave', () => kbDropzone.classList.remove('drag-over'));
    kbDropzone.addEventListener('drop', e => {
      e.preventDefault(); kbDropzone.classList.remove('drag-over');
      if (e.dataTransfer.files.length) {
        kbFile.files = e.dataTransfer.files;
        kbFile.dispatchEvent(new Event('change'));
      }
    });

    // Upload — no doc_type sent ⇒ backend auto-classifies
    kbUploadBtn.addEventListener('click', async () => {
      const file = kbFile.files[0];
      if (!file) return;

      const typeBadge = document.getElementById('kbClassifiedType');
      typeBadge.style.display = 'none';

      kbUploadBtn.disabled = true;
      kbUploadBtn.innerHTML = '<span class="spinner"></span> Uploading…';
      addLog('kbLog', `Uploading ${file.name} — auto-classifying…`, 'info');

      // Pause background polling so it doesn't compete with the upload
      pausePolling();

      const form = new FormData();
      form.append('file', file);
      // No doc_type → backend auto-classifies

      try {
        const data = await apiFetch('/api/knowledge/upload', { method: 'POST', body: form });

        // Show auto-classified type badge
        const classLabel = data.auto_classified ? `Auto: ${data.doc_type}` : data.doc_type;
        typeBadge.textContent = classLabel;
        typeBadge.className = `classified-badge type-${data.doc_type}`;
        typeBadge.style.display = 'inline-block';

        addLog('kbLog', `✓ ${data.message}`, 'success');
        if (data.auto_classified) {
          addLog('kbLog', `📋 Auto-classified as "${data.doc_type}"`, 'info');
        }
        loadKBStats();
        loadKBFiles();
      } catch (e) {
        addLog('kbLog', `✗ Upload failed: ${e.message}`, 'error');
      } finally {
        kbUploadBtn.innerHTML = 'Upload to KB';
        kbUploadBtn.disabled = false;
        kbFile.value = '';
        kbDropzone.querySelector('.label').innerHTML =
          'Drop a company doc or <strong>click to browse</strong>';
        hideKBFile();
        resumePolling();
      }
    });

    // Seed
    document.getElementById('kbSeedBtn').addEventListener('click', async () => {
      const btn = document.getElementById('kbSeedBtn');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> Seeding…';
      addLog('kbLog', 'Seeding knowledge base from JSON files…', 'info');
      pausePolling();

      try {
        const data = await apiFetch('/api/knowledge/seed', { method: 'POST' });
        addLog('kbLog', `✓ ${data.message}`, 'success');
        loadKBStats();
      } catch (e) {
        addLog('kbLog', `✗ Seed failed: ${e.message}`, 'error');
      } finally {
        btn.disabled = false;
        btn.innerHTML = '🌱 Seed from JSON';
        resumePolling();
      }
    });

    // Stats
    async function loadKBStats() {
      try {
        const data = await apiFetch('/api/knowledge/status');
        document.getElementById('kbVectors').textContent = data.pinecone.total_vectors ?? '—';
        const nsCount = data.pinecone.namespaces ? Object.keys(data.pinecone.namespaces).length : 0;
        document.getElementById('kbNamespaces').textContent = nsCount;
        document.getElementById('kbConfigs').textContent =
          data.mongodb.configs ? data.mongodb.configs.length : 0;
        document.getElementById('kbBadge').textContent =
          `${data.pinecone.total_vectors ?? 0} vectors`;
      } catch {
        document.getElementById('kbBadge').textContent = 'Offline';
      }
    }

    // Query — with optional doc_type filter
    document.getElementById('kbQueryBtn').addEventListener('click', async () => {
      const q = document.getElementById('kbQueryInput').value.trim();
      if (!q) return;
      const docType = document.getElementById('kbQueryType').value;
      const box = document.getElementById('kbQueryResults');
      box.innerHTML = '<div style="padding:8px;color:var(--text-muted)"><span class="spinner"></span> Querying…</div>';

      try {
        const payload = { query: q, top_k: 5 };
        if (docType) payload.doc_type = docType;

        const data = await apiFetch('/api/knowledge/query', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!data.results.length) {
          box.innerHTML = '<div style="padding:8px;color:var(--text-muted)">No results.</div>';
          return;
        }
        box.innerHTML = data.results.map(r => `
          <div class="query-result-item">
            <span class="score">[${(r.score || 0).toFixed(3)}]</span>
            ${r.id || ''}
            <div class="text">${(r.text || '').substring(0, 200)}…</div>
          </div>
        `).join('');
      } catch (e) {
        box.innerHTML = `<div style="padding:8px;color:var(--error)">Query failed: ${e.message}</div>`;
      }
    });

    // ── Uploaded KB files list ───────────────────────
    async function loadKBFiles() {
      try {
        const files = await apiFetch('/api/knowledge/files');
        const box = document.getElementById('kbFilesList');
        if (!files.length) {
          box.innerHTML = '<div style="padding:8px;color:var(--text-muted);font-size:12px">No uploads yet.</div>';
          return;
        }
        box.innerHTML = files.map(f => {
          const autoTag = f.auto_classified ? ' (auto)' : '';
          return `
            <div class="kb-file-item">
              <span class="kb-file-name" title="${f.filename}">📄 ${f.filename}</span>
              <div class="kb-file-meta">
                <span class="kb-file-chunks">${f.chunks_stored} chunks</span>
                <span class="type-badge type-${f.doc_type}">${f.doc_type}${autoTag}</span>
              </div>
            </div>
          `;
        }).join('');
      } catch {
        // silently ignore
      }
    }

    document.getElementById('kbRefreshFilesBtn').addEventListener('click', loadKBFiles);

    // ══════════════════════════════════════════════
    //  RFP PIPELINE
    // ══════════════════════════════════════════════

    const rfpFile = document.getElementById('rfpFile');
    const rfpUploadBtn = document.getElementById('rfpUploadBtn');
    const rfpDropzone = document.getElementById('rfpDropzone');
    const rfpFileInfo = document.getElementById('rfpFileInfo');
    let activeWS = null;
    let activeRfpId = null;

    function showRFPFile(file) {
      document.getElementById('rfpFileName').textContent = file.name;
      document.getElementById('rfpFileSize').textContent = `(${formatSize(file.size)})`;
      rfpFileInfo.style.display = 'flex';
    }

    function hideRFPFile() {
      rfpFileInfo.style.display = 'none';
    }

    rfpFile.addEventListener('change', () => {
      rfpUploadBtn.disabled = !rfpFile.files.length;
      if (rfpFile.files.length) {
        showRFPFile(rfpFile.files[0]);
        rfpDropzone.querySelector('.label').innerHTML =
          `<strong>${rfpFile.files[0].name}</strong> selected`;
      } else {
        hideRFPFile();
      }
    });

    rfpDropzone.addEventListener('dragover', e => { e.preventDefault(); rfpDropzone.classList.add('drag-over'); });
    rfpDropzone.addEventListener('dragleave', () => rfpDropzone.classList.remove('drag-over'));
    rfpDropzone.addEventListener('drop', e => {
      e.preventDefault(); rfpDropzone.classList.remove('drag-over');
      if (e.dataTransfer.files.length) {
        rfpFile.files = e.dataTransfer.files;
        rfpFile.dispatchEvent(new Event('change'));
      }
    });

    // Build pipeline stepper from stepperState
    function renderStepper() {
      const box = document.getElementById('pipelineStepper');
      box.innerHTML = STAGES.map(s => {
        const state = stepperState[s.key] || 'pending';
        let cls = '';
        if (state === 'active') cls = 'active';
        if (state === 'complete') cls = 'complete';
        if (state === 'failed') cls = 'failed';
        return `<div class="step ${cls}"><div><div class="step-label">${s.label}</div></div></div>`;
      }).join('');
    }
    renderStepper(); // initial empty

    // ── WebSocket connection for real-time progress ─────
    function connectPipelineWS(rfpId) {
      // Close any existing connection
      if (activeWS) {
        try { activeWS.close(); } catch { }
      }
      activeRfpId = rfpId;

      const url = `${WS_BASE}/api/rfp/ws/${rfpId}`;
      addLog('rfpLog', `Connecting to live progress…`, 'info');
      const ws = new WebSocket(url);
      activeWS = ws;

      ws.onopen = () => {
        addLog('rfpLog', `🔗 Live progress connected`, 'info');
      };

      ws.onmessage = (evt) => {
        let data;
        try { data = JSON.parse(evt.data); } catch { return; }

        switch (data.event) {
          case 'node_start':
            stepperState[data.agent] = 'active';
            addLog('rfpLog', `▶ Starting ${data.agent}`, 'info');
            renderStepper();
            break;

          case 'node_end':
            stepperState[data.agent] = 'complete';
            addLog('rfpLog', `✓ ${data.agent} → ${data.status || 'done'}`, 'success');
            renderStepper();
            break;

          case 'error':
            stepperState[data.agent] = 'failed';
            addLog('rfpLog', `✗ ${data.agent}: ${data.message}`, 'error');
            renderStepper();
            break;

          case 'pipeline_end':
            const endStatus = data.status || 'UNKNOWN';
            document.getElementById('rfpBadge').textContent = endStatus;
            addLog('rfpLog', `══ Pipeline finished: ${endStatus}`,
              endStatus === 'FAILED' ? 'error' : 'success');

            // Re-enable upload button
            rfpUploadBtn.innerHTML = 'Run Pipeline';
            rfpUploadBtn.disabled = false;

            // Refresh runs list and load mappings
            loadRuns();
            if (activeRfpId) loadMappings(activeRfpId);
            break;
        }
      };

      ws.onclose = () => {
        addLog('rfpLog', `WebSocket closed`, '');
        if (activeWS === ws) activeWS = null;
      };

      ws.onerror = () => {
        addLog('rfpLog', `WebSocket error — falling back to polling`, 'error');
        if (activeWS === ws) activeWS = null;
        // Fallback: poll status until done
        startPolling(rfpId);
      };
    }

    // ── Polling fallback ────────────────────────────
    function startPolling(rfpId) {
      const interval = setInterval(async () => {
        try {
          const status = await apiFetch(`/api/rfp/${rfpId}/status`);
          if (status.status !== 'RUNNING') {
            clearInterval(interval);
            document.getElementById('rfpBadge').textContent = status.status;
            updateStepperFromStatus(status);
            rfpUploadBtn.innerHTML = 'Run Pipeline';
            rfpUploadBtn.disabled = false;
            loadRuns();
          }
        } catch {
          clearInterval(interval);
        }
      }, 2000);
    }

    // ── Update stepper from a status response (for polling/viewRun) ──
    function updateStepperFromStatus(status) {
      resetStepperState();
      const currentAgent = status.current_agent || '';
      const failed = status.status === 'FAILED';
      let hitCurrent = false;

      for (const s of STAGES) {
        if (s.key === currentAgent) {
          stepperState[s.key] = failed ? 'failed' : 'active';
          hitCurrent = true;
        } else if (!hitCurrent && currentAgent) {
          stepperState[s.key] = 'complete';
        }
      }
      renderStepper();
    }

    // Upload & run pipeline (returns immediately, progress via WS)
    rfpUploadBtn.addEventListener('click', async () => {
      const file = rfpFile.files[0];
      if (!file) return;

      rfpUploadBtn.disabled = true;
      rfpUploadBtn.innerHTML = '<span class="spinner"></span> Starting…';
      document.getElementById('rfpBadge').textContent = 'Running';
      addLog('rfpLog', `Uploading ${file.name}…`, 'info');

      // Reset stepper for a new run
      resetStepperState();
      renderStepper();

      const form = new FormData();
      form.append('file', file);

      try {
        const data = await apiFetch('/api/rfp/upload', { method: 'POST', body: form });
        addLog('rfpLog', `Pipeline started → ${data.rfp_id}`, 'info');
        document.getElementById('rfpBadge').textContent = 'Running';

        // Keep filename visible during pipeline execution
        rfpUploadBtn.innerHTML = '<span class="spinner"></span> Running…';

        // Connect WebSocket for live progress
        connectPipelineWS(data.rfp_id);

        // Clear file input but keep filename info visible
        rfpFile.value = '';
        rfpDropzone.querySelector('.label').innerHTML =
          'Drop an RFP document or <strong>click to browse</strong>';

      } catch (e) {
        addLog('rfpLog', `✗ Upload failed: ${e.message}`, 'error');
        document.getElementById('rfpBadge').textContent = 'Failed';
        rfpUploadBtn.innerHTML = 'Run Pipeline';
        rfpUploadBtn.disabled = false;
      }
    });

    // Load runs list
    async function loadRuns() {
      try {
        const data = await apiFetch('/api/rfp/list');
        const box = document.getElementById('runsList');
        if (!data.length) {
          box.innerHTML = '<div style="padding:8px;color:var(--text-muted);font-size:13px">No pipeline runs yet.</div>';
          return;
        }
        box.innerHTML = data.map(r => `
          <div class="run-item" onclick="viewRun('${r.rfp_id}')">
            <div>
              <div class="run-id">${r.rfp_id}</div>
              <div class="run-file">${r.filename || '—'}</div>
            </div>
            <div class="run-status ${r.status}">${r.status}</div>
          </div>
        `).join('');
      } catch { }
    }

    async function viewRun(rfpId) {
      try {
        const status = await apiFetch(`/api/rfp/${rfpId}/status`);
        document.getElementById('rfpBadge').textContent = status.status;
        addLog('rfpLog', `Viewing run ${rfpId}: ${status.status}`, 'info');

        updateStepperFromStatus(status);

        // Load agent output logs
        loadAgentLogs(rfpId);

        // Load requirement mappings
        loadMappings(rfpId);

        // If it's still running, connect the WebSocket
        if (status.status === 'RUNNING') {
          connectPipelineWS(rfpId);
        }
      } catch (e) {
        addLog('rfpLog', `Failed to load run: ${e.message}`, 'error');
      }
    }

    document.getElementById('rfpRefreshBtn').addEventListener('click', loadRuns);

    // ══════════════════════════════════════════════
    //  COMPANY POLICIES
    // ══════════════════════════════════════════════

    async function loadPolicies() {
      const category = document.getElementById('policyCategoryFilter').value;
      const qs = category ? `?category=${category}` : '';
      try {
        const data = await apiFetch(`/api/knowledge/policies${qs}`);
        const tbody = document.getElementById('policiesTableBody');
        if (!data.length) {
          tbody.innerHTML = '<tr><td colspan="5" style="padding:16px;text-align:center;color:var(--text-muted)">No policies extracted yet. Upload a company document to extract policies.</td></tr>';
          return;
        }
        const sevColors = { critical: '#ef4444', high: '#f97316', medium: '#eab308', low: '#22c55e' };
        tbody.innerHTML = data.map(p => `
          <tr style="border-bottom:1px solid var(--border)">
            <td style="padding:8px 6px;max-width:300px;overflow:hidden;text-overflow:ellipsis" title="${(p.policy_text || '').replace(/"/g, '&quot;')}">${p.policy_text || ''}</td>
            <td style="padding:8px 6px"><span class="type-badge">${p.category || ''}</span></td>
            <td style="padding:8px 6px"><span style="color:${sevColors[p.severity] || '#888'};font-weight:600;font-size:12px">${(p.severity || '').toUpperCase()}</span></td>
            <td style="padding:8px 6px;font-size:12px;color:var(--text-muted)" title="${p.source_filename || ''}">${(p.source_filename || 'manual').substring(0, 20)}</td>
            <td style="padding:8px 6px">
              <button class="btn btn-outline btn-sm" style="font-size:11px;padding:2px 8px;margin-right:4px" onclick="editPolicy('${p.policy_id}')">✏️</button>
              <button class="btn btn-outline btn-sm" style="font-size:11px;padding:2px 8px;color:#ef4444" onclick="deletePolicy('${p.policy_id}')">🗑</button>
            </td>
          </tr>
        `).join('');
      } catch (e) {
        document.getElementById('policiesTableBody').innerHTML = `<tr><td colspan="5" style="padding:16px;text-align:center;color:#ef4444">Failed to load policies: ${e.message}</td></tr>`;
      }
    }

    function openPolicyModal(title = 'Add Policy', policy = null) {
      document.getElementById('policyModalTitle').textContent = title;
      document.getElementById('policyEditId').value = policy ? policy.policy_id : '';
      document.getElementById('policyTextInput').value = policy ? policy.policy_text : '';
      document.getElementById('policyCatInput').value = policy ? policy.category : 'capability';
      document.getElementById('policySevInput').value = policy ? policy.severity : 'medium';
      document.getElementById('policySectionInput').value = policy ? (policy.source_section || '') : '';
      const modal = document.getElementById('policyModal');
      modal.style.display = 'flex';
    }
    window.closePolicyModal = function () {
      document.getElementById('policyModal').style.display = 'none';
    };

    document.getElementById('addPolicyBtn').addEventListener('click', () => openPolicyModal());

    window.savePolicy = async function () {
      const editId = document.getElementById('policyEditId').value;
      const body = {
        policy_text: document.getElementById('policyTextInput').value.trim(),
        category: document.getElementById('policyCatInput').value,
        severity: document.getElementById('policySevInput').value,
        source_section: document.getElementById('policySectionInput').value.trim(),
      };
      if (!body.policy_text) return alert('Policy text is required');
      try {
        if (editId) {
          await apiFetch(`/api/knowledge/policies/${editId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          });
        } else {
          await apiFetch('/api/knowledge/policies', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          });
        }
        closePolicyModal();
        loadPolicies();
      } catch (e) {
        alert('Failed to save: ' + e.message);
      }
    };

    window.editPolicy = async function (policyId) {
      try {
        const policies = await apiFetch('/api/knowledge/policies');
        const pol = policies.find(p => p.policy_id === policyId);
        if (pol) openPolicyModal('Edit Policy', pol);
      } catch (e) {
        alert('Failed to load policy: ' + e.message);
      }
    };

    window.deletePolicy = async function (policyId) {
      if (!confirm(`Delete policy ${policyId}?`)) return;
      try {
        await apiFetch(`/api/knowledge/policies/${policyId}`, { method: 'DELETE' });
        loadPolicies();
      } catch (e) {
        alert('Failed to delete: ' + e.message);
      }
    };

    document.getElementById('policyCategoryFilter').addEventListener('change', loadPolicies);

    document.getElementById('deleteAllPoliciesBtn').addEventListener('click', async () => {
      if (!confirm('Delete ALL policies? This cannot be undone.')) return;
      try {
        const res = await apiFetch('/api/knowledge/policies', { method: 'DELETE' });
        alert(res.message || 'All policies deleted');
        loadPolicies();
      } catch (e) {
        alert('Failed to delete policies: ' + e.message);
      }
    });

    // ══════════════════════════════════════════════
    //  REQUIREMENT MAPPINGS
    // ══════════════════════════════════════════════

    async function loadMappings(rfpId) {
      const container = document.getElementById('mappingsContainer');
      const badge = document.getElementById('mappingDecisionBadge');
      const hint = document.getElementById('mappingsHint');
      container.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted)"><span class="spinner"></span> Loading mappings…</div>';
      hint.textContent = `Run: ${rfpId}`;
      badge.style.display = 'none';

      try {
        const data = await apiFetch(`/api/rfp/${rfpId}/mappings`);
        if (!data.available) {
          container.innerHTML = `<div style="padding:24px;text-align:center;color:var(--text-muted);font-size:13px">${data.message || 'No mapping data available.'}</div>`;
          return;
        }

        // Decision badge
        badge.textContent = data.decision === 'GO' ? '✅ GO' : '❌ NO GO';
        badge.className = `mapping-decision-badge ${data.decision}`;
        badge.style.display = 'inline-flex';

        // Build HTML
        let html = '';

        // ── Scores row ──
        const sc = data.scores || {};
        const scoreColor = (val, invert) => {
          const v = parseFloat(val) || 0;
          if (invert) return v > 7 ? '#ef4444' : v > 4 ? '#f59e0b' : '#10b981';
          return v >= 7 ? '#10b981' : v >= 4 ? '#f59e0b' : '#ef4444';
        };
        html += `<div class="mapping-scores">
          <div class="score-item"><div class="score-val" style="color:${scoreColor(sc.strategic_fit)}">${(sc.strategic_fit || 0).toFixed(1)}</div><div class="score-lbl">Strategic Fit</div></div>
          <div class="score-item"><div class="score-val" style="color:${scoreColor(sc.technical_feasibility)}">${(sc.technical_feasibility || 0).toFixed(1)}</div><div class="score-lbl">Technical</div></div>
          <div class="score-item"><div class="score-val" style="color:${scoreColor(sc.regulatory_risk, true)}">${(sc.regulatory_risk || 0).toFixed(1)}</div><div class="score-lbl">Reg. Risk</div></div>
        </div>`;

        // ── Justification ──
        if (data.justification) {
          html += `<div style="margin-bottom:14px;padding:10px 14px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;font-size:13px">
            <strong>Justification:</strong> ${data.justification}
          </div>`;
        }

        // ── Red flags & violations ──
        if (data.red_flags && data.red_flags.length) {
          html += `<div style="margin-bottom:10px;padding:8px 14px;background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.2);border-radius:8px;font-size:12px;color:#f59e0b">
            <strong>⚠ Red Flags:</strong> ${data.red_flags.join(' • ')}
          </div>`;
        }
        if (data.policy_violations && data.policy_violations.length) {
          html += `<div style="margin-bottom:10px;padding:8px 14px;background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.2);border-radius:8px;font-size:12px;color:#ef4444">
            <strong>❌ Policy Violations:</strong> ${data.policy_violations.join(' • ')}
          </div>`;
        }

        // ── Summary pills ──
        const sm = data.summary || {};
        html += `<div class="mapping-summary">
          <div class="summary-pill"><span class="pill-dot" style="background:#6366f1"></span> ${sm.total || 0} Total</div>
          <div class="summary-pill"><span class="pill-dot" style="background:#10b981"></span> ${sm.aligned || 0} Aligned</div>
          <div class="summary-pill"><span class="pill-dot" style="background:#ef4444"></span> ${sm.violated || 0} Violated</div>
          <div class="summary-pill"><span class="pill-dot" style="background:#f59e0b"></span> ${sm.risk || 0} Risk</div>
          <div class="summary-pill"><span class="pill-dot" style="background:#9ca3af"></span> ${sm.no_match || 0} No Match</div>
        </div>`;

        // ── Filter row ──
        html += `<div class="mapping-filter-row">
          <select id="mappingStatusFilter" style="padding:5px 10px;border-radius:6px;border:1px solid var(--border);background:var(--bg-secondary);color:var(--text-primary);font-size:12px">
            <option value="">All Statuses</option>
            <option value="ALIGNS">✅ Aligns</option>
            <option value="VIOLATES">❌ Violates</option>
            <option value="RISK">⚠️ Risk</option>
            <option value="NO_MATCH">❓ No Match</option>
          </select>
          <span style="font-size:11px;color:var(--text-muted)" id="mappingFilterCount">${(data.mappings || []).length} mappings</span>
        </div>`;

        // ── Table ──
        const mappings = data.mappings || [];
        html += `<div style="max-height:400px;overflow-y:auto;border:1px solid var(--border);border-radius:8px">
          <table class="mapping-table" id="mappingTable">
            <thead>
              <tr>
                <th style="width:100px">ID</th>
                <th style="width:90px">Status</th>
                <th style="width:75px">Confidence</th>
                <th>Requirement</th>
                <th>Matched Policy</th>
                <th>Reasoning</th>
              </tr>
            </thead>
            <tbody>
              ${mappings.map(m => {
                const conf = parseFloat(m.confidence) || 0;
                const confColor = conf >= 0.8 ? '#10b981' : conf >= 0.5 ? '#f59e0b' : '#ef4444';
                return `<tr data-status="${m.mapping_status}">
                  <td style="font-weight:500;font-size:11px;color:var(--accent-light)">${m.requirement_id || '—'}</td>
                  <td><span class="status-chip ${m.mapping_status}">${m.mapping_status}</span></td>
                  <td>
                    <div class="conf-bar">
                      <div class="conf-bar-track"><div class="conf-bar-fill" style="width:${conf*100}%;background:${confColor}"></div></div>
                      <span class="conf-bar-val">${(conf*100).toFixed(0)}%</span>
                    </div>
                  </td>
                  <td style="max-width:220px;line-height:1.4" title="${(m.requirement_text || '').replace(/"/g, '&quot;')}">${m.requirement_text || '—'}</td>
                  <td style="font-size:11px;max-width:180px;line-height:1.4;color:var(--text-secondary)" title="${(m.matched_policy || '').replace(/"/g, '&quot;')}">${m.matched_policy || '—'}</td>
                  <td style="font-size:11px;max-width:180px;line-height:1.4;color:var(--text-muted)">${m.reasoning || '—'}</td>
                </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>`;

        container.innerHTML = html;

        // ── Wire up filter ──
        const filterSelect = document.getElementById('mappingStatusFilter');
        if (filterSelect) {
          filterSelect.addEventListener('change', () => {
            const val = filterSelect.value;
            const rows = document.querySelectorAll('#mappingTable tbody tr');
            let visible = 0;
            rows.forEach(row => {
              const show = !val || row.dataset.status === val;
              row.style.display = show ? '' : 'none';
              if (show) visible++;
            });
            document.getElementById('mappingFilterCount').textContent = `${visible} mappings`;
          });
        }

      } catch (e) {
        container.innerHTML = `<div style="padding:24px;text-align:center;color:#ef4444;font-size:13px">Failed to load mappings: ${e.message}</div>`;
      }
    }

    // ══════════════════════════════════════════════
    //  AGENT OUTPUT LOGS
    // ══════════════════════════════════════════════

    async function loadAgentLogs(rfpId) {
      const container = document.getElementById('agentLogsContainer');
      container.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted)">Loading agent outputs…</div>';
      document.getElementById('agentLogsHint').textContent = `Run: ${rfpId}`;
      try {
        const status = await apiFetch(`/api/rfp/${rfpId}/status`);
        const outputs = status.agent_outputs || {};
        if (!Object.keys(outputs).length) {
          container.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted)">No agent outputs available for this run.</div>';
          return;
        }
        let html = '';
        // A1 Intake
        if (outputs.A1_INTAKE) {
          const a1 = outputs.A1_INTAKE;
          html += `<details style="margin-bottom:12px"><summary style="cursor:pointer;font-weight:600;padding:8px 0">📥 A1 Intake</summary>
            <div style="padding:8px 16px;font-size:13px">
              <div><strong>RFP ID:</strong> ${a1.rfp_id || '—'}</div>
              <div><strong>Title:</strong> ${a1.title || '—'}</div>
              <div><strong>Pages:</strong> ${a1.page_count ?? '—'} | <strong>Words:</strong> ${a1.word_count ?? '—'}</div>
            </div></details>`;
        }
        // A2 Structuring
        if (outputs.A2_STRUCTURING) {
          const a2 = outputs.A2_STRUCTURING;
          const sections = a2.sections || [];
          html += `<details style="margin-bottom:12px"><summary style="cursor:pointer;font-weight:600;padding:8px 0">📑 A2 Structuring (${sections.length} sections, confidence: ${(a2.overall_confidence || 0).toFixed(2)})</summary>
            <div style="padding:8px 16px;font-size:13px">
              ${sections.map(s => `<div style="padding:4px 0"><span class="type-badge">${s.category}</span> <strong>${s.title}</strong> — ${s.content_summary || ''}</div>`).join('')}
            </div></details>`;
        }
        // A3 Go/No-Go
        if (outputs.A3_GO_NO_GO) {
          const a3 = outputs.A3_GO_NO_GO;
          const mappings = a3.requirement_mappings || [];
          const statusColors = { ALIGNS: '#22c55e', VIOLATES: '#ef4444', RISK: '#f97316', NO_MATCH: '#888' };
          html += `<details open style="margin-bottom:12px"><summary style="cursor:pointer;font-weight:600;padding:8px 0">📊 A3 Go/No-Go — <span style="color:${a3.decision === 'GO' ? '#22c55e' : '#ef4444'}">${a3.decision || '—'}</span></summary>
            <div style="padding:8px 16px;font-size:13px">
              <div style="display:flex;gap:16px;margin-bottom:12px">
                <div><strong>Strategic Fit:</strong> ${a3.strategic_fit_score ?? '—'}/10</div>
                <div><strong>Technical:</strong> ${a3.technical_feasibility_score ?? '—'}/10</div>
                <div><strong>Risk:</strong> ${a3.regulatory_risk_score ?? '—'}/10</div>
              </div>
              <div style="margin-bottom:8px"><strong>Justification:</strong> ${a3.justification || '—'}</div>
              ${a3.red_flags && a3.red_flags.length ? `<div style="margin-bottom:8px;color:#f97316"><strong>Red Flags:</strong> ${a3.red_flags.join(', ')}</div>` : ''}
              <div style="margin-bottom:4px"><strong>Requirements:</strong> ${a3.total_requirements || 0} total | ✅ ${a3.aligned_count || 0} aligned | ❌ ${a3.violated_count || 0} violated | ⚠️ ${a3.risk_count || 0} risk | ❓ ${a3.no_match_count || 0} unmatched</div>
              ${mappings.length ? `<table style="width:100%;border-collapse:collapse;margin-top:8px;font-size:12px">
                <thead><tr style="border-bottom:1px solid var(--border);text-align:left">
                  <th style="padding:6px">Requirement</th><th style="padding:6px">Status</th><th style="padding:6px">Matched Policy</th><th style="padding:6px">Reasoning</th>
                </tr></thead>
                <tbody>${mappings.map(m => `<tr style="border-bottom:1px solid var(--border)">
                  <td style="padding:6px;max-width:200px;overflow:hidden;text-overflow:ellipsis" title="${(m.requirement_text || '').replace(/"/g, '&quot;')}">${m.requirement_text || ''}</td>
                  <td style="padding:6px"><span style="color:${statusColors[m.mapping_status] || '#888'};font-weight:600">${m.mapping_status}</span></td>
                  <td style="padding:6px;font-size:11px;max-width:200px;overflow:hidden;text-overflow:ellipsis">${m.matched_policy || '—'}</td>
                  <td style="padding:6px;font-size:11px;color:var(--text-muted)">${m.reasoning || ''}</td>
                </tr>`).join('')}</tbody>
              </table>` : ''}
            </div></details>`;
        }
        // Other agents — raw JSON
        for (const [key, val] of Object.entries(outputs)) {
          if (['A1_INTAKE', 'A2_STRUCTURING', 'A3_GO_NO_GO'].includes(key)) continue;
          html += `<details style="margin-bottom:12px"><summary style="cursor:pointer;font-weight:600;padding:8px 0">🔧 ${key}</summary>
            <pre style="padding:12px;background:var(--surface-2);border-radius:8px;font-size:11px;overflow-x:auto;max-height:300px">${JSON.stringify(val, null, 2)}</pre></details>`;
        }
        container.innerHTML = html;
      } catch (e) {
        container.innerHTML = `<div style="padding:16px;text-align:center;color:#ef4444">Failed to load agent outputs: ${e.message}</div>`;
      }
    }

    // ── Init ───────────────────────────────────────
    let _healthInterval = null;
    let _statsInterval = null;

    function pausePolling() {
      if (_healthInterval) { clearInterval(_healthInterval); _healthInterval = null; }
      if (_statsInterval) { clearInterval(_statsInterval); _statsInterval = null; }
    }
    function resumePolling() {
      if (!_healthInterval) _healthInterval = setInterval(checkHealth, 60000);
      if (!_statsInterval) _statsInterval = setInterval(loadKBStats, 60000);
    }

    checkHealth();
    loadKBStats();
    loadKBFiles();
    loadRuns();
    loadPolicies();
    resumePolling();
  </script>
</body>

</html>
```

## File: `frontend\README.md`

```markdown
# RFP Responder — Frontend

> **Status:** ✅ Implemented — single-page vanilla JS dashboard served by FastAPI

The frontend is a single HTML file (`index.html`) with inline CSS and JavaScript.  
FastAPI serves it at `GET /` so there is no separate build step or dev server.

## Architecture

| Aspect | Detail |
|---|---|
| Framework | None — vanilla HTML / CSS / JS |
| Served by | FastAPI `StaticFiles` + `FileResponse` at `/` |
| Real-time | WebSocket (`/api/rfp/ws/{rfp_id}`) for live pipeline progress |
| Fallback | Polling `/api/rfp/{rfp_id}/status` with pause/resume support |
| Styling | Embedded CSS with CSS variables for theming |

## Layout

The dashboard is split into two panels:

### Left Panel — Knowledge Base

| Feature | Description |
|---|---|
| **Document Upload** | Drag-and-drop or click to upload PDF/DOCX/JSON/CSV files |
| **Auto-Classification** | Regex keyword scoring assigns a `doc_type` badge automatically |
| **Uploaded Files** | Lists all uploaded files with name, doc type, vector count, and timestamp |
| **Query** | Search the knowledge base with an optional `doc_type` filter dropdown |
| **Seed & Status** | Seed bundled knowledge data and check KB vector count |

### Right Panel — RFP Pipeline

| Feature | Description |
|---|---|
| **RFP Upload** | Drag-and-drop or click to upload an RFP document |
| **WebSocket Stepper** | Real-time stage-by-stage progress bar driven by WebSocket events |
| **Stage Cards** | Each agent stage shows status (pending / running / completed / error) |
| **Run History** | Lists previous pipeline runs with status, filename, and timestamps |

## API Endpoints Used

### RFP Pipeline

```
POST /api/rfp/upload               → Upload RFP + start pipeline in background thread
GET  /api/rfp/{rfp_id}/status      → Poll pipeline status (fallback)
WS   /api/rfp/ws/{rfp_id}          → WebSocket real-time progress stream
GET  /api/rfp/list                 → List all pipeline runs
```

### Knowledge Base

```
POST /api/knowledge/upload         → Upload + auto-classify + embed document
GET  /api/knowledge/query          → Semantic search (?q=...&doc_type=...)
POST /api/knowledge/seed           → Seed bundled JSON knowledge data
GET  /api/knowledge/status         → KB vector count + health
GET  /api/knowledge/files          → List uploaded KB files
```

## Running

No separate install or build is required. Start the FastAPI server and
open your browser:

```bash
# from project root
python -m rfp_automation          # → http://localhost:8000
```

The frontend loads automatically at `http://localhost:8000/`.

```

## File: `rfp_automation\config.py`

```python
"""
Application configuration using Pydantic Settings.
All environment-specific values are centralized here.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── App / API Server ───────────────────────────────
    app_name: str = "RFP Response Automation"
    debug: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # ── LLM (Groq Cloud) ────────────────────────────────
    groq_api_key: str = ""
    llm_model: str = "llama-3.3-70b-versatile"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 4096

    # ── MongoDB ──────────────────────────────────────────
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "rfp_automation"

    # ── File Storage ─────────────────────────────────────
    storage_backend: str = "local"  # "local" | "s3"
    local_storage_path: str = "./storage"
    aws_s3_bucket: str = ""
    aws_access_key: str = ""
    aws_secret_key: str = ""
    aws_region: str = "us-east-1"

    # ── Pinecone Vector DB ───────────────────────────────
    pinecone_api_key: str = ""
    pinecone_index_name: str = "rfp-automation"
    pinecone_cloud: str = "aws"  # serverless cloud provider
    pinecone_region: str = "us-east-1"  # serverless region

    # ── Embeddings ───────────────────────────────────────
    embedding_model: str = "all-MiniLM-L6-v2"

    # ── Knowledge Data ───────────────────────────────────
    knowledge_data_path: str = ""  # override path to seed JSON files

    # ── Pipeline Limits ──────────────────────────────────
    max_validation_retries: int = 3
    max_structuring_retries: int = 3
    approval_timeout_hours: int = 48

    # ── Logging ──────────────────────────────────────────
    log_level: str = "INFO"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings (singleton)."""
    return Settings()

```

## File: `rfp_automation\main.py`

```python
"""
RFP Response Automation — Main Entry Point

Run the pipeline directly (CLI):
    python -m rfp_automation.main

Run as an API server (for the frontend):
    python -m rfp_automation.main --serve
    # or: uvicorn rfp_automation.api:app --reload --port 8000

Or import and run programmatically:
    from rfp_automation.main import run
    result = run("path/to/rfp.pdf")
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from rfp_automation.orchestration.graph import run_pipeline
from rfp_automation.utils.logger import setup_logging


def run(file_path: str = "") -> dict:
    """Run the full RFP pipeline and return the final state."""
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("  RFP RESPONSE AUTOMATION SYSTEM")
    logger.info(f"  Mode: MOCK | Started: {datetime.now(timezone.utc).isoformat()}")
    logger.info("=" * 60)

    final_state = run_pipeline(uploaded_file_path=file_path)

    # Print summary
    _print_summary(final_state)

    return final_state


def _print_summary(state: dict) -> None:
    """Print a human-readable summary of the pipeline result."""
    logger = logging.getLogger(__name__)

    rfp_meta = state.get("rfp_metadata", {})
    status = state.get("status", "UNKNOWN")
    go_no_go = state.get("go_no_go_result", {})
    requirements = state.get("requirements", [])
    validation = state.get("technical_validation", {})
    commercial = state.get("commercial_result", {})
    legal = state.get("legal_result", {})
    approval = state.get("approval_package", {})
    submission = state.get("submission_record", {})

    logger.info("")
    logger.info("-" * 60)
    logger.info("  PIPELINE RESULT SUMMARY")
    logger.info("-" * 60)
    logger.info(f"  RFP ID:         {rfp_meta.get('rfp_id', 'N/A')}")
    logger.info(f"  Client:         {rfp_meta.get('client_name', 'N/A')}")
    logger.info(f"  Title:          {rfp_meta.get('rfp_title', 'N/A')}")
    logger.info(f"  Final Status:   {status}")
    logger.info(f"  Go/No-Go:       {go_no_go.get('decision', 'N/A')}")
    logger.info(f"  Requirements:   {len(requirements)} extracted")
    logger.info(f"  Validation:     {validation.get('decision', 'N/A')}")
    logger.info(f"  Legal:          {legal.get('decision', 'N/A')}")
    logger.info(f"  Approval:       {approval.get('approval_decision', 'N/A')}")

    pricing = commercial.get("pricing", {})
    if pricing:
        logger.info(f"  Total Price:    ${pricing.get('total_price', 0):,.2f}")

    if submission.get("submitted_at"):
        logger.info(f"  Submitted At:   {submission['submitted_at']}")
        logger.info(f"  File Hash:      {submission.get('file_hash', 'N/A')[:16]}...")

    logger.info("-" * 60)

    # Audit trail summary
    audit = state.get("audit_trail", [])
    logger.info(f"\n  Audit Trail: {len(audit)} entries")
    for entry in audit:
        logger.info(
            f"    v{entry.get('state_version', '?')} | "
            f"{entry.get('agent', '?')} | "
            f"{entry.get('action', '?')} | "
            f"{entry.get('details', '')}"
        )
    logger.info("")


def serve(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Start the FastAPI server (for frontend communication)."""
    import uvicorn

    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info(f"Starting API server on {host}:{port}")
    uvicorn.run("rfp_automation.api:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve()
    else:
        file_arg = sys.argv[1] if len(sys.argv) > 1 else ""
        run(file_arg)

```

## File: `rfp_automation\__init__.py`

```python
# RFP Response Automation System

```

## File: `rfp_automation\__main__.py`

```python
"""Allow running as: python -m rfp_automation"""

from rfp_automation.main import run, serve
import sys

if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve()
    else:
        file_arg = sys.argv[1] if len(sys.argv) > 1 else ""
        run(file_arg)

```

## File: `rfp_automation\agents\architecture_agent.py`

```python
"""
C1 — Architecture Planning Agent
Responsibility: Group requirements into response sections, map each to
                company capabilities.  Verify every mandatory requirement
                appears in the plan.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class ArchitecturePlanningAgent(BaseAgent):
    name = AgentName.C1_ARCHITECTURE_PLANNING

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: LLM grouping + MCP capability matching
        raise NotImplementedError(f"{self.name.value} not yet implemented")

```

## File: `rfp_automation\agents\base_agent.py`

```python
"""
Base agent class that every pipeline agent inherits.

Design:
  - `process()` is called by the LangGraph node.
  - `_real_process()` is the single abstract method — override in each agent.
  - Pipeline halts with NotImplementedError if an agent isn't implemented yet.
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.enums import AgentName

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base for all pipeline agents."""

    name: AgentName  # set in each subclass

    # ── Public entry point (called by LangGraph node) ────

    def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        LangGraph calls this as the node function.
        Accepts and returns a dict so LangGraph can merge updates
        into the shared state automatically.
        """
        t0 = time.perf_counter()
        separator = "═" * 70
        logger.info(f"\n{separator}")
        logger.info(f"▶ [{self.name.value}] STARTING")
        logger.info(separator)

        # Log incoming state keys + sizes
        _log_state_summary("INPUT STATE", state)

        # Hydrate state from dict
        graph_state = RFPGraphState(**state)
        graph_state.current_agent = self.name.value

        # Broadcast real-time progress — prefer the tracking id the
        # frontend connected to, fall back to rfp_metadata.rfp_id
        rfp_id = state.get("tracking_rfp_id", "")
        if not rfp_id:
            meta = state.get("rfp_metadata")
            if isinstance(meta, dict):
                rfp_id = meta.get("rfp_id", "")
            elif hasattr(meta, "rfp_id"):
                rfp_id = meta.rfp_id or ""

        progress = None
        try:
            from rfp_automation.api.websocket import PipelineProgress
            progress = PipelineProgress.get()
            progress.on_node_start(rfp_id, self.name.value)
        except Exception:
            pass

        try:
            updated = self._real_process(graph_state)

            updated.add_audit(
                agent=self.name.value,
                action="completed",
                details="",
            )
            elapsed = time.perf_counter() - t0
            logger.info(f"✔ [{self.name.value}] COMPLETED in {elapsed:.3f}s")

            # Log output state diff
            out_dict = updated.model_dump()
            _log_state_summary("OUTPUT STATE", out_dict)
            _log_state_diff("STATE CHANGES", state, out_dict)

            logger.info(f"{separator}\n")

            try:
                if progress:
                    status = updated.status.value if hasattr(updated.status, 'value') else str(updated.status)
                    progress.on_node_end(rfp_id, self.name.value, status)
            except Exception:
                pass

        except NotImplementedError as exc:
            # Agent not yet implemented — gracefully skip so earlier
            # results (e.g. A3 requirement mappings) are preserved in
            # the pipeline state rather than lost.
            elapsed = time.perf_counter() - t0
            graph_state.error_message = f"[{self.name.value}] {exc}"
            graph_state.add_audit(
                agent=self.name.value,
                action="skipped",
                details=str(exc),
            )
            logger.warning(
                f"⚠ [{self.name.value}] NOT IMPLEMENTED — skipping after {elapsed:.3f}s: {exc}"
            )
            logger.info(f"{separator}\n")

            try:
                if progress:
                    progress.on_error(rfp_id, self.name.value, str(exc))
            except Exception:
                pass

            # Return current state so the pipeline can continue or end
            # with all previously-accumulated data intact.
            return graph_state.model_dump()

        except Exception as exc:
            elapsed = time.perf_counter() - t0
            graph_state.error_message = f"[{self.name.value}] {exc}"
            graph_state.add_audit(
                agent=self.name.value,
                action="error",
                details=str(exc),
            )
            logger.exception(
                f"✘ [{self.name.value}] FAILED after {elapsed:.3f}s: {exc}"
            )
            logger.info(f"{separator}\n")

            try:
                if progress:
                    progress.on_error(rfp_id, self.name.value, str(exc))
            except Exception:
                pass

            raise

        return updated.model_dump()

    # ── Subclass hook ────────────────────────────────────

    @abstractmethod
    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        """
        Real implementation using LLM + MCP.
        Must be overridden by each agent.
        """
        ...


# ── Debug helpers (module-level) ─────────────────────────

def _log_state_summary(label: str, state: dict[str, Any]) -> None:
    """Log key names, non-empty values, and approximate sizes."""
    lines = [f"  ┌─ {label}"]
    for key in sorted(state.keys()):
        val = state[key]
        if val is None or val == "" or val == [] or val == {}:
            lines.append(f"  │  {key}: <empty>")
        elif isinstance(val, str):
            lines.append(f"  │  {key}: str({len(val)} chars)")
        elif isinstance(val, list):
            lines.append(f"  │  {key}: list({len(val)} items)")
        elif isinstance(val, dict):
            lines.append(f"  │  {key}: dict({len(val)} keys)")
        else:
            lines.append(f"  │  {key}: {type(val).__name__} = {_truncate(val)}")
    lines.append(f"  └─ ({len(state)} keys total)")
    logger.debug("\n".join(lines))


def _log_state_diff(label: str, before: dict[str, Any], after: dict[str, Any]) -> None:
    """Log which keys changed between input and output state."""
    changes: list[str] = []
    all_keys = set(before.keys()) | set(after.keys())
    for key in sorted(all_keys):
        old = before.get(key)
        new = after.get(key)
        if old != new:
            changes.append(f"  │  {key}: {_truncate(old)} → {_truncate(new)}")
    if changes:
        logger.debug(f"  ┌─ {label}\n" + "\n".join(changes) + f"\n  └─ ({len(changes)} fields changed)")
    else:
        logger.debug(f"  ── {label}: no changes")


def _truncate(val: Any, max_len: int = 120) -> str:
    """Produce a short repr for debug logging."""
    if val is None:
        return "<None>"
    if isinstance(val, str):
        if len(val) > max_len:
            return repr(val[:max_len]) + f"…({len(val)} chars)"
        return repr(val)
    if isinstance(val, list):
        return f"list({len(val)} items)"
    if isinstance(val, dict):
        try:
            s = json.dumps(val, default=str)
            if len(s) > max_len:
                return s[:max_len] + f"…({len(s)} chars)"
            return s
        except Exception:
            return f"dict({len(val)} keys)"
    s = str(val)
    if len(s) > max_len:
        return s[:max_len] + "…"
    return s

```

## File: `rfp_automation\agents\commercial_agent.py`

```python
"""
E1 — Commercial Agent
Responsibility: Generate pricing breakdown using MCP knowledge base pricing
                rules.  Runs in parallel with E2 Legal.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class CommercialAgent(BaseAgent):
    name = AgentName.E1_COMMERCIAL

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: LLM pricing + MCP pricing rules
        raise NotImplementedError(f"{self.name.value} not yet implemented")

```

## File: `rfp_automation\agents\final_readiness_agent.py`

```python
"""
F1 — Final Readiness Agent
Responsibility: Compile the approval package (proposal, pricing, legal risk
                register, coverage matrix, decision brief) and trigger the
                human approval gate.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class FinalReadinessAgent(BaseAgent):
    name = AgentName.F1_FINAL_READINESS

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: Compile approval package from state fields
        raise NotImplementedError(f"{self.name.value} not yet implemented")

```

## File: `rfp_automation\agents\go_no_go_agent.py`

```python
"""
A3 — Go / No-Go Agent
Responsibility: Extract requirements from RFP, map them against pre-extracted
                company policies, score strategic fit / feasibility / risk,
                produce GO or NO_GO with detailed requirement mappings.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, PipelineStatus, GoNoGoDecision
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import GoNoGoResult, RequirementMapping
from rfp_automation.mcp import MCPService
from rfp_automation.services.llm_service import llm_text_call

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "go_no_go_prompt.txt"


class GoNoGoAgent(BaseAgent):
    name = AgentName.A3_GO_NO_GO

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # ── 1. Validate rfp_id ──────────────────────────
        rfp_id = state.rfp_metadata.rfp_id
        if not rfp_id:
            raise ValueError("No rfp_id in state — A1 Intake must run first")

        logger.info(f"[A3] Starting Go/No-Go analysis for {rfp_id}")

        # ── 2. Gather RFP sections from structuring result ──
        sections = state.structuring_result.sections
        logger.debug(f"[A3] Structuring result has {len(sections)} sections")
        rfp_sections_text = self._format_sections(sections)

        # If no structured sections, fall back to RFP store
        if not rfp_sections_text.strip():
            logger.debug("[A3] No structured sections — falling back to MCP RFP store")
            mcp = MCPService()
            chunks = mcp.query_rfp_all_chunks(rfp_id, top_k=50)
            logger.debug(f"[A3] Retrieved {len(chunks)} chunks from MCP")
            rfp_sections_text = "\n\n".join(
                c.get("text", "") for c in chunks if c.get("text")
            )

        if not rfp_sections_text.strip():
            logger.warning("[A3] No RFP content available — defaulting to GO")
            state.go_no_go_result = GoNoGoResult(
                decision=GoNoGoDecision.GO,
                justification="No RFP content available for analysis. Defaulting to GO.",
            )
            state.status = PipelineStatus.EXTRACTING_REQUIREMENTS
            return state

        # ── 3. Load pre-extracted company policies ──────
        mcp = MCPService()
        policies = mcp.get_extracted_policies()
        logger.debug(f"[A3] Loaded {len(policies)} pre-extracted policies")
        policies_text = json.dumps(policies, indent=2) if policies else "No company policies extracted yet."

        # ── 4. Load company capabilities for enrichment ─
        capabilities = mcp.query_knowledge("company capabilities services", top_k=10)
        logger.debug(f"[A3] Loaded {len(capabilities)} capability chunks")
        capabilities_text = "\n".join(
            c.get("text", "") for c in capabilities if c.get("text")
        )
        if not capabilities_text.strip():
            capabilities_text = "No capability data available."

        # ── 5. Build prompt ─────────────────────────────
        prompt = self._build_prompt(rfp_sections_text, policies_text, capabilities_text)
        logger.debug(
            f"[A3] Prompt built — {len(prompt)} chars "
            f"(RFP: {len(rfp_sections_text)} | Policies: {len(policies_text)} | Capabilities: {len(capabilities_text)})"
        )

        # ── 6. Call LLM ─────────────────────────────────
        logger.info("[A3] Calling LLM for Go/No-Go analysis…")
        raw_response = llm_text_call(prompt)
        logger.debug(f"[A3] Raw LLM response ({len(raw_response)} chars):\n{raw_response[:2000]}")

        # ── 7. Parse response ───────────────────────────
        result = self._parse_response(raw_response)

        # ── 8. Update state ─────────────────────────────
        state.go_no_go_result = result

        if result.decision == GoNoGoDecision.NO_GO:
            state.status = PipelineStatus.NO_GO
            logger.info(f"[A3] Decision: NO_GO — {result.justification}")
        else:
            state.status = PipelineStatus.EXTRACTING_REQUIREMENTS
            logger.info(f"[A3] Decision: GO — {result.justification}")

        # ── Detailed decision dump (INFO for visibility) ──
        self._log_mapping_table(result)

        return state

    # ── Helpers ──────────────────────────────────────────

    def _format_sections(self, sections: list) -> str:
        """Format structuring result sections into readable text."""
        if not sections:
            return ""
        parts = []
        for s in sections:
            title = getattr(s, "title", str(s)) if not isinstance(s, dict) else s.get("title", "")
            category = getattr(s, "category", "") if not isinstance(s, dict) else s.get("category", "")
            summary = getattr(s, "content_summary", "") if not isinstance(s, dict) else s.get("content_summary", "")
            parts.append(f"### {title} [{category}]\n{summary}")
        return "\n\n".join(parts)

    def _log_mapping_table(self, result: GoNoGoResult) -> None:
        """Log a formatted requirement-mapping table at INFO level."""
        # ── Scores summary ──
        logger.info(
            f"[A3] Scores → strategic_fit={result.strategic_fit_score:.1f}/10, "
            f"technical_feasibility={result.technical_feasibility_score:.1f}/10, "
            f"regulatory_risk={result.regulatory_risk_score:.1f}/10"
        )

        # ── Counts ──
        logger.info(
            f"[A3] Mappings → total={result.total_requirements}, "
            f"aligned={result.aligned_count}, violated={result.violated_count}, "
            f"risk={result.risk_count}, no_match={result.no_match_count}"
        )

        if result.policy_violations:
            logger.info(f"[A3] Policy violations: {result.policy_violations}")
        if result.red_flags:
            logger.info(f"[A3] Red flags: {result.red_flags}")

        # ── Formatted table ──
        if not result.requirement_mappings:
            logger.info("[A3] No requirement mappings produced.")
            return

        # Column widths
        id_w, status_w, conf_w = 14, 10, 6
        req_w, policy_w, reason_w = 40, 30, 30

        sep = f"╠{'═'*id_w}╬{'═'*status_w}╬{'═'*conf_w}╬{'═'*req_w}╬{'═'*policy_w}╬{'═'*reason_w}╣"
        top = f"╔{'═'*id_w}╦{'═'*status_w}╦{'═'*conf_w}╦{'═'*req_w}╦{'═'*policy_w}╦{'═'*reason_w}╗"
        bot = f"╚{'═'*id_w}╩{'═'*status_w}╩{'═'*conf_w}╩{'═'*req_w}╩{'═'*policy_w}╩{'═'*reason_w}╝"

        def pad(text: str, width: int) -> str:
            return (text[:width-1] + "…" if len(text) >= width else text).ljust(width)

        header = (
            f"║{pad('Requirement ID', id_w)}║{pad('Status', status_w)}║{pad('Conf.', conf_w)}"
            f"║{pad('Requirement Text', req_w)}║{pad('Matched Policy', policy_w)}║{pad('Reasoning', reason_w)}║"
        )

        lines = [
            f"[A3] ╔{'═' * (id_w + status_w + conf_w + req_w + policy_w + reason_w + 5)}╗",
            f"[A3] ║  REQUIREMENT MAPPING RESULTS — {result.total_requirements} requirements{' ' * max(0, id_w + status_w + conf_w + req_w + policy_w + reason_w + 5 - 35 - len(str(result.total_requirements)))}║",
            f"[A3] {top}",
            f"[A3] {header}",
            f"[A3] {sep}",
        ]

        for m in result.requirement_mappings:
            row = (
                f"║{pad(m.requirement_id, id_w)}"
                f"║{pad(m.mapping_status, status_w)}"
                f"║{pad(f'{m.confidence:.2f}', conf_w)}"
                f"║{pad(m.requirement_text, req_w)}"
                f"║{pad(m.matched_policy or '—', policy_w)}"
                f"║{pad(m.reasoning or '—', reason_w)}║"
            )
            lines.append(f"[A3] {row}")

        lines.append(f"[A3] {bot}")

        logger.info("\n".join(lines))

    def _build_prompt(
        self, rfp_sections: str, policies: str, capabilities: str
    ) -> str:
        template = _PROMPT_PATH.read_text(encoding="utf-8")
        return (
            template
            .replace("{rfp_sections}", rfp_sections[:12_000])
            .replace("{company_policies}", policies[:8_000])
            .replace("{capabilities}", capabilities[:5_000])
        )

    def _parse_response(self, raw: str) -> GoNoGoResult:
        """Parse the LLM JSON response into a GoNoGoResult."""
        # Strip markdown fencing
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        data: dict[str, Any] = {}
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Fallback: find first { ... } block
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        if not data:
            logger.error("[A3] Failed to parse LLM response — defaulting to GO")
            return GoNoGoResult(
                decision=GoNoGoDecision.GO,
                justification="LLM response parsing failed. Defaulting to GO for manual review.",
            )

        # Parse requirement mappings
        mappings: list[RequirementMapping] = []
        for m in data.get("requirement_mappings", []):
            if isinstance(m, dict):
                mappings.append(RequirementMapping(
                    requirement_id=m.get("requirement_id", ""),
                    requirement_text=m.get("requirement_text", ""),
                    source_section=m.get("source_section", ""),
                    mapping_status=m.get("mapping_status", "NO_MATCH").upper(),
                    matched_policy=m.get("matched_policy", ""),
                    matched_policy_id=m.get("matched_policy_id", ""),
                    confidence=float(m.get("confidence", 0.0)),
                    reasoning=m.get("reasoning", ""),
                ))

        # Compute counts
        aligned = sum(1 for m in mappings if m.mapping_status == "ALIGNS")
        violated = sum(1 for m in mappings if m.mapping_status == "VIOLATES")
        risk = sum(1 for m in mappings if m.mapping_status == "RISK")
        no_match = sum(1 for m in mappings if m.mapping_status == "NO_MATCH")

        # Determine decision
        decision_str = data.get("decision", "GO").upper()
        decision = GoNoGoDecision.NO_GO if decision_str == "NO_GO" else GoNoGoDecision.GO

        return GoNoGoResult(
            decision=decision,
            strategic_fit_score=float(data.get("strategic_fit_score", 0.0)),
            technical_feasibility_score=float(data.get("technical_feasibility_score", 0.0)),
            regulatory_risk_score=float(data.get("regulatory_risk_score", 0.0)),
            policy_violations=data.get("policy_violations", []),
            red_flags=data.get("red_flags", []),
            justification=data.get("justification", ""),
            requirement_mappings=mappings,
            total_requirements=len(mappings),
            aligned_count=aligned,
            violated_count=violated,
            risk_count=risk,
            no_match_count=no_match,
        )

```

## File: `rfp_automation\agents\intake_agent.py`

```python
"""
A1 — Intake Agent

Responsibility:
  Validate uploaded PDF, compute SHA-256 hash, extract structured text blocks,
  extract metadata via regex, prepare chunks, send to MCP, update state.

Does NOT: summarize, interpret, extract requirements, call LLM, embed,
          vectorize, or parse table cells.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, PipelineStatus
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import RFPMetadata
from rfp_automation.services.parsing_service import ParsingService
from rfp_automation.mcp import MCPService

logger = logging.getLogger(__name__)


class IntakeAgent(BaseAgent):
    name = AgentName.A1_INTAKE

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        file_path = state.uploaded_file_path

        # ── 1. File validation ───────────────────────────
        if not file_path:
            raise ValueError("No file path provided in state")

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Uploaded file not found: {file_path}")

        if path.suffix.lower() != ".pdf":
            raise ValueError(
                f"Unsupported file type: {path.suffix}. Only .pdf supported."
            )

        # ── 1b. SHA-256 hash ─────────────────────────────
        file_bytes = path.read_bytes()
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        logger.info(f"[A1] File validated — size: {len(file_bytes):,} bytes, SHA-256: {file_hash}")

        # ── 2. Extract structured blocks ─────────────────
        logger.info(f"[A1] Parsing file: {file_path}")
        blocks = ParsingService.parse_pdf_blocks(file_path)

        if not blocks:
            raise ValueError("No text blocks extracted from document")

        logger.debug(f"[A1] Extracted {len(blocks)} raw blocks")
        block_types = {}
        for b in blocks:
            bt = b.get("type", "unknown")
            block_types[bt] = block_types.get(bt, 0) + 1
        logger.debug(f"[A1] Block type distribution: {block_types}")

        # ── 3. Extract metadata via regex ────────────────
        extracted_meta = ParsingService.extract_metadata(blocks)
        logger.info(f"[A1] Extracted metadata: {extracted_meta}")

        # ── 4. Prepare structured chunks ─────────────────
        chunks = ParsingService.prepare_chunks(blocks)
        logger.info(f"[A1] Prepared {len(chunks)} chunks")
        for i, c in enumerate(chunks[:5]):
            logger.debug(f"[A1]   Chunk {i}: type={c.get('content_type')} section={c.get('section_hint')} len={len(c.get('text',''))}")
        if len(chunks) > 5:
            logger.debug(f"[A1]   ... and {len(chunks) - 5} more chunks")

        # ── 5. Build concatenated raw text ───────────────
        raw_text = "\n".join(b["text"] for b in blocks)

        # ── 6. Build metadata object ─────────────────────
        rfp_id = (
            extracted_meta.get("rfp_number")
            or f"RFP-{uuid.uuid4().hex[:8].upper()}"
        )

        # ── 7. Send chunks to MCP (rfp_id must exist) ───
        mcp = MCPService()
        mcp.store_rfp_chunks(rfp_id, chunks, source_file=file_path)
        logger.info(f"[A1] Sent {len(chunks)} chunks to MCP for rfp_id={rfp_id}")
        word_count = len(raw_text.split())
        logger.debug(f"[A1] Raw text: {word_count} words, {len(raw_text)} chars")

        # ── 8. Page count, title, final metadata ────────
        # Real page count from extracted blocks
        page_numbers = {b["page_number"] for b in blocks}
        page_count = max(page_numbers) if page_numbers else 0

        # Title: first heading block, else first text line
        title = "Untitled RFP"
        for b in blocks:
            if b["type"] == "heading":
                title = b["text"][:200]
                break
        if title == "Untitled RFP":
            first_text = next(
                (b["text"] for b in blocks if b["type"] != "table_mock"), ""
            )
            if first_text:
                title = first_text.split("\n")[0][:200]

        metadata = RFPMetadata(
            rfp_id=rfp_id,
            rfp_title=title,
            rfp_number=extracted_meta.get("rfp_number") or "",
            client_name=extracted_meta.get("organization") or "",
            source_file_path=str(path.resolve()),
            page_count=page_count,
            word_count=word_count,
            file_hash=file_hash,
            contact_email=extracted_meta.get("contact_email"),
            contact_phone=extracted_meta.get("contact_phone"),
            issue_date=extracted_meta.get("issue_date"),
            deadline_text=extracted_meta.get("deadline"),
        )

        # ── 9. Update state ──────────────────────────────
        state.rfp_metadata = metadata
        state.uploaded_file_path = str(path.resolve())
        state.raw_text = raw_text
        state.status = PipelineStatus.INTAKE_COMPLETE

        logger.info(
            f"[A1] Intake complete — rfp_id={rfp_id}, title={metadata.rfp_title!r}, "
            f"pages={metadata.page_count}, words={word_count}"
        )
        logger.debug(f"[A1] Full metadata: {metadata.model_dump_json(indent=2)}")

        return state

```

## File: `rfp_automation\agents\legal_agent.py`

```python
"""
E2 — Legal Agent
Responsibility: Analyse contract clauses for risk, check compliance
                certifications.  Has VETO authority (BLOCK → pipeline ends).
                Runs in parallel with E1 Commercial.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class LegalAgent(BaseAgent):
    name = AgentName.E2_LEGAL

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: LLM clause analysis + MCP legal templates
        raise NotImplementedError(f"{self.name.value} not yet implemented")

```

## File: `rfp_automation\agents\narrative_agent.py`

```python
"""
C3 — Narrative Assembly Agent
Responsibility: Combine section responses into a cohesive proposal with
                executive summary, transitions, and coverage appendix.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class NarrativeAssemblyAgent(BaseAgent):
    name = AgentName.C3_NARRATIVE_ASSEMBLY

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: LLM assembly + executive summary
        raise NotImplementedError(f"{self.name.value} not yet implemented")

```

## File: `rfp_automation\agents\requirement_extraction_agent.py`

```python
"""
B1 — Requirements Extraction Agent
Responsibility: Extract every requirement from the RFP, classify by type,
                category, and impact, and assign unique IDs.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class RequirementsExtractionAgent(BaseAgent):
    name = AgentName.B1_REQUIREMENTS_EXTRACTION

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: LLM extraction per section via MCP
        raise NotImplementedError(f"{self.name.value} not yet implemented")

```

## File: `rfp_automation\agents\requirement_validation_agent.py`

```python
"""
B2 — Requirements Validation Agent
Responsibility: Cross-check extracted requirements for completeness,
                duplicates, contradictions, and ambiguities.
                Issues do NOT block the pipeline — they flow forward as context.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class RequirementsValidationAgent(BaseAgent):
    name = AgentName.B2_REQUIREMENTS_VALIDATION

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: LLM validation of extracted requirements
        raise NotImplementedError(f"{self.name.value} not yet implemented")

```

## File: `rfp_automation\agents\structuring_agent.py`

```python
"""
A2 — RFP Structuring Agent
Responsibility: Query MCP RFP store, classify document into sections,
                assign confidence scores.  Retry up to 3x if confidence is low.

Chunking strategies (one per retry):
  Attempt 0 — retrieve all stored chunks (broad retrieval)
  Attempt 1 — category-specific targeted queries (6 queries, deduplicated)
  Attempt 2 — re-chunk raw text with smaller windows (500 chars, 100 overlap)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.config import get_settings
from rfp_automation.mcp import MCPService
from rfp_automation.models.enums import AgentName, PipelineStatus
from rfp_automation.models.schemas import RFPSection, StructuringResult
from rfp_automation.models.state import RFPGraphState
from rfp_automation.services.llm_service import llm_text_call
from rfp_automation.services.parsing_service import ParsingService

logger = logging.getLogger(__name__)

# Section categories the agent classifies into
SECTION_CATEGORIES = [
    "scope",
    "technical",
    "compliance",
    "legal",
    "submission",
    "evaluation",
]

# Prompt template path
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "structuring_prompt.txt"


class StructuringAgent(BaseAgent):
    name = AgentName.A2_STRUCTURING

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        rfp_id = state.rfp_metadata.rfp_id
        if not rfp_id:
            raise ValueError("No rfp_id in state — A1 Intake must run first")

        retry_count = state.structuring_result.retry_count
        logger.info(f"[A2] Structuring attempt {retry_count} for {rfp_id}")
        logger.debug(f"[A2] Previous confidence: {state.structuring_result.overall_confidence:.4f}")
        logger.debug(f"[A2] Previous sections: {len(state.structuring_result.sections)}")

        # ── 1. Retrieve chunks using strategy based on retry count ───
        mcp = MCPService()
        chunks = self._retrieve_chunks(mcp, rfp_id, retry_count, state.raw_text)
        logger.debug(f"[A2] Retrieved {len(chunks) if chunks else 0} chunks with strategy {retry_count}")

        if not chunks:
            logger.warning(f"[A2] No chunks retrieved for {rfp_id}")
            state.structuring_result = StructuringResult(
                sections=[],
                overall_confidence=0.0,
                retry_count=retry_count + 1,
            )
            state.status = PipelineStatus.STRUCTURING
            return state

        # ── 2. Build prompt ──────────────────────────────────────────
        prompt = self._build_prompt(chunks, retry_count, state.structuring_result)

        # ── 3. Call LLM ──────────────────────────────────────────────
        logger.info(f"[A2] Calling LLM with {len(chunks)} chunks ({len(prompt)} char prompt)")
        sections = self._call_llm_and_parse(prompt)
        for s in sections:
            logger.debug(
                f"[A2]   Section: {s.section_id} | {s.category} | "
                f"confidence={s.confidence:.3f} | {s.title[:60]}"
            )

        # ── 4. Compute confidence ────────────────────────────────────
        if sections:
            overall_confidence = sum(s.confidence for s in sections) / len(sections)
        else:
            overall_confidence = 0.0

        logger.info(
            f"[A2] Got {len(sections)} sections, "
            f"overall_confidence={overall_confidence:.3f}"
        )
        if overall_confidence < 0.6:
            logger.debug(
                f"[A2] Confidence {overall_confidence:.3f} < 0.6 threshold — will retry "
                f"(attempt {retry_count + 1})"
            )
        else:
            logger.debug(f"[A2] Confidence {overall_confidence:.3f} >= 0.6 — proceeding to Go/No-Go")

        # ── 5. Build result and update state ─────────────────────────
        result = StructuringResult(
            sections=sections,
            overall_confidence=round(overall_confidence, 4),
            retry_count=retry_count + 1 if overall_confidence < 0.6 else retry_count,
        )
        state.structuring_result = result

        # Let the orchestration router decide next step based on confidence
        if overall_confidence >= 0.6:
            state.status = PipelineStatus.GO_NO_GO
        else:
            state.status = PipelineStatus.STRUCTURING

        return state

    # ── Chunking strategies ──────────────────────────────────────

    def _retrieve_chunks(
        self,
        mcp: MCPService,
        rfp_id: str,
        retry_count: int,
        raw_text: str,
    ) -> list[dict[str, Any]]:
        """
        Pick retrieval strategy based on retry count:
          0 → all stored chunks (broad retrieval)
          1 → category-specific targeted queries
          2+ → re-chunk raw text with smaller windows
        """
        if retry_count == 0:
            return self._strategy_all_chunks(mcp, rfp_id)
        elif retry_count == 1:
            return self._strategy_category_queries(mcp, rfp_id)
        else:
            return self._strategy_rechunk(raw_text)

    def _strategy_all_chunks(
        self, mcp: MCPService, rfp_id: str
    ) -> list[dict[str, Any]]:
        """Attempt 0: retrieve all stored chunks in document order."""
        logger.info("[A2] Strategy 0: retrieving all stored chunks")
        return mcp.query_rfp_all_chunks(rfp_id, top_k=100)

    def _strategy_category_queries(
        self, mcp: MCPService, rfp_id: str
    ) -> list[dict[str, Any]]:
        """Attempt 1: run 6 category-specific queries and deduplicate."""
        logger.info("[A2] Strategy 1: category-specific targeted queries")
        category_queries = {
            "scope": "project scope objectives deliverables background overview",
            "technical": "technical requirements specifications architecture system design",
            "compliance": "compliance regulatory standards certifications requirements",
            "legal": "legal terms contract liability indemnification intellectual property",
            "submission": "submission instructions deadline format proposal delivery",
            "evaluation": "evaluation criteria scoring methodology selection process weighting",
        }

        seen_ids: set[str] = set()
        all_chunks: list[dict[str, Any]] = []

        for category, query in category_queries.items():
            results = mcp.query_rfp(query, rfp_id, top_k=10)
            for chunk in results:
                chunk_id = chunk.get("id", "")
                if chunk_id not in seen_ids:
                    seen_ids.add(chunk_id)
                    all_chunks.append(chunk)

        # Sort by chunk_index for document order
        all_chunks.sort(key=lambda c: c.get("chunk_index", -1))
        return all_chunks

    def _strategy_rechunk(self, raw_text: str) -> list[dict[str, Any]]:
        """Attempt 2+: re-chunk raw text with smaller windows for finer granularity."""
        logger.info("[A2] Strategy 2: re-chunking raw text with smaller windows")
        if not raw_text:
            logger.warning("[A2] No raw_text available for re-chunking")
            return []

        small_chunks = ParsingService.chunk_text(
            raw_text, chunk_size=500, overlap=100
        )
        return [
            {
                "id": f"rechunk_{i:04d}",
                "score": 1.0,
                "text": chunk,
                "chunk_index": i,
                "metadata": {"rechunked": True},
            }
            for i, chunk in enumerate(small_chunks)
        ]

    # ── Prompt building ──────────────────────────────────────────

    def _build_prompt(
        self,
        chunks: list[dict[str, Any]],
        retry_count: int,
        previous_result: StructuringResult,
    ) -> str:
        """Load the prompt template and fill placeholders."""
        template = _PROMPT_PATH.read_text(encoding="utf-8")

        # Format chunks as numbered text blocks
        chunk_texts = []
        for i, chunk in enumerate(chunks):
            text = chunk.get("text", "").strip()
            if text:
                chunk_texts.append(f"[Chunk {i + 1}]\n{text}")

        chunks_str = "\n\n".join(chunk_texts)

        # Build retry hint
        retry_hint = ""
        if retry_count > 0 and previous_result.sections:
            low_conf_sections = [
                s.title for s in previous_result.sections if s.confidence < 0.6
            ]
            if low_conf_sections:
                retry_hint = (
                    f"NOTE: This is retry attempt {retry_count}. "
                    f"Previous classification had low confidence on these sections: "
                    f"{', '.join(low_conf_sections)}. "
                    f"Try a different grouping or re-examine chunk boundaries."
                )
            else:
                retry_hint = (
                    f"NOTE: This is retry attempt {retry_count}. "
                    f"Previous overall confidence was {previous_result.overall_confidence:.2f}. "
                    f"Be more precise in your classification."
                )

        return template.format(chunks=chunks_str, retry_hint=retry_hint)

    # ── LLM call and response parsing ────────────────────────────

    def _call_llm_and_parse(self, prompt: str) -> list[RFPSection]:
        """Call LLM and parse JSON response into RFPSection objects."""
        try:
            raw_response = llm_text_call(prompt)
            logger.debug(f"[A2] Raw LLM response ({len(raw_response)} chars):\n{raw_response[:2000]}")
        except Exception as exc:
            logger.error(f"[A2] LLM call failed: {exc}")
            return []

        parsed = self._parse_sections_json(raw_response)
        logger.debug(f"[A2] Parsed {len(parsed)} sections from LLM response")
        return parsed

    def _parse_sections_json(self, raw_response: str) -> list[RFPSection]:
        """
        Parse the LLM response into a list of RFPSection.
        Handles common issues: markdown fencing, extra text around JSON.
        Returns empty list on failure (triggers retry via low confidence).
        """
        text = raw_response.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (fences)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        # Try to extract JSON array from the response
        try:
            start = text.index("[")
            end = text.rindex("]") + 1
            text = text[start:end]
        except ValueError:
            logger.warning("[A2] No JSON array found in LLM response")
            return []

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning(f"[A2] JSON parse error: {exc}")
            return []

        if not isinstance(data, list):
            logger.warning("[A2] LLM response is not a JSON array")
            return []

        # Validate and build RFPSection objects
        sections: list[RFPSection] = []
        for i, item in enumerate(data):
            try:
                section = RFPSection(
                    section_id=item.get("section_id", f"SEC-{i + 1:02d}"),
                    title=item.get("title", "Untitled"),
                    category=self._normalize_category(
                        item.get("category", "scope")
                    ),
                    content_summary=item.get("content_summary", ""),
                    confidence=float(item.get("confidence", 0.0)),
                    page_range=item.get("page_range", ""),
                )
                sections.append(section)
            except (ValueError, TypeError) as exc:
                logger.warning(f"[A2] Skipping invalid section {i}: {exc}")
                continue

        return sections

    @staticmethod
    def _normalize_category(category: str) -> str:
        """Ensure category is one of the valid values."""
        normalized = category.strip().lower()
        if normalized in SECTION_CATEGORIES:
            return normalized
        # Fuzzy fallback
        for valid in SECTION_CATEGORIES:
            if valid in normalized or normalized in valid:
                return valid
        return "scope"  # default fallback

```

## File: `rfp_automation\agents\submission_agent.py`

```python
"""
F2 — Submission & Archive Agent
Responsibility: Apply final formatting, package deliverables, archive to
                storage with file hashes for auditability.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class SubmissionAgent(BaseAgent):
    name = AgentName.F2_SUBMISSION

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: Packaging + hashing + archiving
        raise NotImplementedError(f"{self.name.value} not yet implemented")

```

## File: `rfp_automation\agents\technical_validation_agent.py`

```python
"""
D1 — Technical Validation Agent
Responsibility: Validate assembled proposal against original requirements.
                Check completeness, alignment, realism, consistency.
                REJECT loops back to C3 (max 3 retries).
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class TechnicalValidationAgent(BaseAgent):
    name = AgentName.D1_TECHNICAL_VALIDATION

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: LLM validation + MCP rule checks
        raise NotImplementedError(f"{self.name.value} not yet implemented")

```

## File: `rfp_automation\agents\writing_agent.py`

```python
"""
C2 — Requirement Writing Agent
Responsibility: Generate prose response per section using requirement context
                and capability evidence.  Build a coverage matrix.
"""

from __future__ import annotations

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName
from rfp_automation.models.state import RFPGraphState


class RequirementWritingAgent(BaseAgent):
    name = AgentName.C2_REQUIREMENT_WRITING

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        # TODO: LLM prose generation per section
        raise NotImplementedError(f"{self.name.value} not yet implemented")

```

## File: `rfp_automation\agents\__init__.py`

```python
from .base_agent import BaseAgent
from .intake_agent import IntakeAgent
from .structuring_agent import StructuringAgent
from .go_no_go_agent import GoNoGoAgent
from .requirement_extraction_agent import RequirementsExtractionAgent
from .requirement_validation_agent import RequirementsValidationAgent
from .architecture_agent import ArchitecturePlanningAgent
from .writing_agent import RequirementWritingAgent
from .narrative_agent import NarrativeAssemblyAgent
from .technical_validation_agent import TechnicalValidationAgent
from .commercial_agent import CommercialAgent
from .legal_agent import LegalAgent
from .final_readiness_agent import FinalReadinessAgent
from .submission_agent import SubmissionAgent

__all__ = [
    "BaseAgent",
    "IntakeAgent",
    "StructuringAgent",
    "GoNoGoAgent",
    "RequirementsExtractionAgent",
    "RequirementsValidationAgent",
    "ArchitecturePlanningAgent",
    "RequirementWritingAgent",
    "NarrativeAssemblyAgent",
    "TechnicalValidationAgent",
    "CommercialAgent",
    "LegalAgent",
    "FinalReadinessAgent",
    "SubmissionAgent",
]

```

## File: `rfp_automation\api\knowledge_routes.py`

```python
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

```

## File: `rfp_automation\api\routes.py`

```python
"""
API routes — thin HTTP layer that delegates to the orchestration.

Routes:
  GET  /health                  → API health check
  POST /api/rfp/upload          → Upload an RFP file and start the pipeline (background)
  GET  /api/rfp/{rfp_id}/status → Poll current pipeline status
  POST /api/rfp/{rfp_id}/approve → Human approval gate action
  GET  /api/rfp/list            → List all RFP runs
  WS   /ws/{rfp_id}             → Real-time pipeline progress
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from rfp_automation.config import get_settings
from rfp_automation.api.websocket import PipelineProgress

logger = logging.getLogger(__name__)

# ── Routers ──────────────────────────────────────────────
health_router = APIRouter()
rfp_router = APIRouter()

# ── In-memory store (replaced by MongoDB/Redis later) ────
_runs: dict[str, dict[str, Any]] = {}


# ── Response schemas ─────────────────────────────────────
class UploadResponse(BaseModel):
    rfp_id: str
    status: str
    message: str


class StatusResponse(BaseModel):
    rfp_id: str
    status: str
    current_agent: str
    started_at: str
    filename: str = ""
    pipeline_log: list[dict[str, str]] = []
    result: dict[str, Any] | None = None
    agent_outputs: dict[str, Any] = {}


class ApprovalRequest(BaseModel):
    decision: str  # "APPROVE" | "REJECT"
    reviewer: str = ""
    comments: str = ""


class ApprovalResponse(BaseModel):
    rfp_id: str
    decision: str
    message: str


# ── Health ───────────────────────────────────────────────

@health_router.get("/health")
async def health_check():
    settings = get_settings()
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Upload & Start Pipeline (background thread) ─────────

def _run_pipeline_thread(rfp_id: str, local_path: str) -> None:
    """Run the pipeline in a background thread so the HTTP response returns immediately."""
    from rfp_automation.orchestration.graph import run_pipeline

    progress = PipelineProgress.get()

    try:
        result = run_pipeline(
            uploaded_file_path=local_path,
            initial_state={"tracking_rfp_id": rfp_id},
        )
        status = str(result.get("status", "UNKNOWN"))

        # Use the real rfp_id extracted by intake if available
        real_rfp_id = ""
        meta = result.get("rfp_metadata")
        if isinstance(meta, dict):
            real_rfp_id = meta.get("rfp_id", "")

        audit = result.get("audit_trail", [])
        pipeline_log = [
            {"agent": a.get("agent", ""), "status": a.get("action", ""),
             "timestamp": a.get("timestamp", "")}
            for a in audit
        ] if audit else []

        _runs[rfp_id].update({
            "status": status,
            "current_agent": result.get("current_agent", ""),
            "pipeline_log": pipeline_log,
            "result": result,
            "real_rfp_id": real_rfp_id,
        })

        progress.on_pipeline_end(rfp_id, status)

    except Exception as e:
        logger.error(f"Pipeline failed for {rfp_id}: {e}")
        status = "FAILED"
        _runs[rfp_id].update({
            "status": "FAILED",
            "current_agent": "",
            "pipeline_log": [{"agent": "SYSTEM", "status": f"FAILED: {e}",
                              "timestamp": datetime.now(timezone.utc).isoformat()}],
            "result": {"error": str(e)},
        })
        progress.on_error(rfp_id, "SYSTEM", str(e))
        progress.on_pipeline_end(rfp_id, "FAILED")
    finally:
        # Clean up the temporary uploaded file
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
                logger.info(f"Cleaned up temp file: {local_path}")
        except OSError as cleanup_err:
            logger.warning(f"Failed to clean up {local_path}: {cleanup_err}")


@rfp_router.post("/upload", response_model=UploadResponse)
async def upload_rfp(file: UploadFile = File(...)):
    """
    Upload an RFP document and start the processing pipeline
    in a background thread.  Returns immediately with the rfp_id
    so the frontend can connect via WebSocket for live progress.
    """
    rfp_id = f"RFP-{uuid.uuid4().hex[:8].upper()}"
    filename = file.filename or "unknown.pdf"

    logger.info(f"Received upload: {filename} → {rfp_id}")

    # Save file temporarily
    file_bytes = await file.read()
    local_path = f"./storage/uploads/{rfp_id}_{filename}"
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(file_bytes)

    started_at = datetime.now(timezone.utc).isoformat()
    _runs[rfp_id] = {
        "rfp_id": rfp_id,
        "filename": filename,
        "status": "RUNNING",
        "current_agent": "A1_INTAKE",
        "started_at": started_at,
        "pipeline_log": [],
        "result": None,
    }

    # Launch pipeline in background thread
    thread = threading.Thread(
        target=_run_pipeline_thread,
        args=(rfp_id, local_path),
        daemon=True,
    )
    thread.start()

    return UploadResponse(
        rfp_id=rfp_id,
        status="RUNNING",
        message=f"Pipeline started for {filename}. Connect to /ws/{rfp_id} for live progress.",
    )


# ── Status Polling ───────────────────────────────────────

@rfp_router.get("/{rfp_id}/status", response_model=StatusResponse)
async def get_rfp_status(rfp_id: str):
    run = _runs.get(rfp_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"RFP {rfp_id} not found")

    # Build agent_outputs from the stored pipeline result
    agent_outputs: dict[str, Any] = {}
    result_data = run.get("result")
    if isinstance(result_data, dict):
        # A1 Intake
        meta = result_data.get("rfp_metadata")
        if isinstance(meta, dict) and meta.get("rfp_id"):
            agent_outputs["A1_INTAKE"] = meta
        # A2 Structuring
        struct = result_data.get("structuring_result")
        if isinstance(struct, dict) and struct.get("sections"):
            agent_outputs["A2_STRUCTURING"] = struct
        # A3 Go/No-Go
        gng = result_data.get("go_no_go_result")
        if isinstance(gng, dict) and gng.get("decision"):
            agent_outputs["A3_GO_NO_GO"] = gng

    return StatusResponse(
        rfp_id=run["rfp_id"],
        status=run["status"],
        current_agent=run.get("current_agent", ""),
        started_at=run["started_at"],
        filename=run.get("filename", ""),
        pipeline_log=run.get("pipeline_log", []),
        result=run.get("result"),
        agent_outputs=agent_outputs,
    )


# ── Human Approval Gate ─────────────────────────────────

@rfp_router.post("/{rfp_id}/approve", response_model=ApprovalResponse)
async def approve_rfp(rfp_id: str, body: ApprovalRequest):
    run = _runs.get(rfp_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"RFP {rfp_id} not found")

    if body.decision not in ("APPROVE", "REJECT"):
        raise HTTPException(status_code=400, detail="Decision must be APPROVE or REJECT")

    logger.info(f"[{rfp_id}] Human gate: {body.decision} by {body.reviewer}")
    run["status"] = "SUBMITTED" if body.decision == "APPROVE" else "REJECTED"

    return ApprovalResponse(
        rfp_id=rfp_id,
        decision=body.decision,
        message=f"RFP {rfp_id} {body.decision.lower()}d",
    )


# ── List All Runs ────────────────────────────────────────

@rfp_router.get("/list")
async def list_rfps():
    return [
        {
            "rfp_id": r["rfp_id"],
            "filename": r.get("filename", ""),
            "status": r["status"],
            "started_at": r["started_at"],
        }
        for r in _runs.values()
    ]


# ── Requirement Mappings ─────────────────────────────────

@rfp_router.get("/{rfp_id}/mappings")
async def get_requirement_mappings(rfp_id: str):
    """
    Return the requirement-mapping table for a given RFP run.
    Provides scores, summary counts, and individual mappings.
    """
    run = _runs.get(rfp_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"RFP {rfp_id} not found")

    result_data = run.get("result")
    if not isinstance(result_data, dict):
        return {
            "rfp_id": rfp_id,
            "available": False,
            "message": "Pipeline has not completed yet",
        }

    gng = result_data.get("go_no_go_result")
    if not isinstance(gng, dict) or not gng.get("requirement_mappings"):
        return {
            "rfp_id": rfp_id,
            "available": False,
            "message": "No requirement mapping data available for this run",
        }

    return {
        "rfp_id": rfp_id,
        "available": True,
        "decision": gng.get("decision", "UNKNOWN"),
        "justification": gng.get("justification", ""),
        "scores": {
            "strategic_fit": gng.get("strategic_fit_score", 0),
            "technical_feasibility": gng.get("technical_feasibility_score", 0),
            "regulatory_risk": gng.get("regulatory_risk_score", 0),
        },
        "summary": {
            "total": gng.get("total_requirements", 0),
            "aligned": gng.get("aligned_count", 0),
            "violated": gng.get("violated_count", 0),
            "risk": gng.get("risk_count", 0),
            "no_match": gng.get("no_match_count", 0),
        },
        "red_flags": gng.get("red_flags", []),
        "policy_violations": gng.get("policy_violations", []),
        "mappings": gng.get("requirement_mappings", []),
    }


# ── WebSocket endpoint for real-time pipeline progress ───

@rfp_router.websocket("/ws/{rfp_id}")
async def ws_pipeline_progress(websocket: WebSocket, rfp_id: str):
    """
    WebSocket endpoint — client connects here after POSTing /upload.
    Receives JSON events: node_start, node_end, pipeline_end, error.
    """
    progress = PipelineProgress.get()
    await progress.connect(rfp_id, websocket)
    try:
        while True:
            # Keep the connection alive; client can send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        progress.disconnect(rfp_id, websocket)
    except Exception:
        progress.disconnect(rfp_id, websocket)

```

## File: `rfp_automation\api\websocket.py`

```python
"""
WebSocket support for real-time pipeline progress.

Provides:
  - PipelineProgress singleton that agents/routes use to broadcast events
  - WebSocket clients connect via /ws/{rfp_id} to get live updates
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class PipelineProgress:
    """
    In-process event bus.
    Every connected WebSocket client for a given rfp_id receives
    JSON messages like:
        { "event": "node_start", "agent": "A1_INTAKE", "ts": "..." }
        { "event": "node_end",   "agent": "A1_INTAKE", "status": "INTAKE_COMPLETE" }
        { "event": "pipeline_end", "status": "SUBMITTED" }
        { "event": "error", "agent": "A3_GO_NO_GO", "message": "..." }
    """

    _instance: PipelineProgress | None = None

    def __init__(self) -> None:
        self._clients: dict[str, list[WebSocket]] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def get(cls) -> PipelineProgress:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ── Client management ────────────────────────────────

    async def connect(self, rfp_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.setdefault(rfp_id, []).append(ws)
        for msg in self._history.get(rfp_id, []):
            try:
                await ws.send_json(msg)
            except Exception:
                break

    def disconnect(self, rfp_id: str, ws: WebSocket) -> None:
        clients = self._clients.get(rfp_id, [])
        if ws in clients:
            clients.remove(ws)

    # ── Broadcasting (thread-safe for sync pipeline) ─────

    def emit(self, rfp_id: str, event: dict[str, Any]) -> None:
        event.setdefault("ts", datetime.now(timezone.utc).isoformat())
        self._history.setdefault(rfp_id, []).append(event)

        clients = self._clients.get(rfp_id, [])
        if not clients:
            return

        loop = self._loop
        if loop is None or loop.is_closed():
            return

        asyncio.run_coroutine_threadsafe(self._broadcast(rfp_id, event), loop)

    async def _broadcast(self, rfp_id: str, event: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in self._clients.get(rfp_id, []):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(rfp_id, ws)

    # ── Convenience helpers ──────────────────────────────

    def on_node_start(self, rfp_id: str, agent: str) -> None:
        self.emit(rfp_id, {"event": "node_start", "agent": agent})
        logger.info(f"▶  [{rfp_id}] Starting node: {agent}")

    def on_node_end(self, rfp_id: str, agent: str, status: str) -> None:
        self.emit(rfp_id, {"event": "node_end", "agent": agent, "status": status})
        logger.info(f"✓  [{rfp_id}] Completed node: {agent} → {status}")

    def on_pipeline_end(self, rfp_id: str, status: str) -> None:
        self.emit(rfp_id, {"event": "pipeline_end", "status": status})
        logger.info(f"══ [{rfp_id}] Pipeline finished: {status}")

    def on_error(self, rfp_id: str, agent: str, message: str) -> None:
        self.emit(rfp_id, {"event": "error", "agent": agent, "message": message})
        logger.error(f"✗  [{rfp_id}] Error in {agent}: {message}")

    def clear(self, rfp_id: str) -> None:
        self._history.pop(rfp_id, None)

```

## File: `rfp_automation\api\__init__.py`

```python
"""
FastAPI application factory and API package.

Run with:
    uvicorn rfp_automation.api:app --reload --port 8000

Or via main.py:
    python -m rfp_automation.main --serve
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rfp_automation.config import get_settings
from rfp_automation.api.routes import rfp_router, health_router
from rfp_automation.api.knowledge_routes import knowledge_router
from rfp_automation.api.websocket import PipelineProgress
from rfp_automation.utils.logger import setup_logging

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Application factory — create and configure the FastAPI instance."""
    settings = get_settings()
    setup_logging(settings.log_level)

    application = FastAPI(
        title="RFP Response Automation API",
        description="Backend API for the multi-agent RFP response system",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — allow the frontend (adjust origins in production)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register route groups (includes WebSocket at /api/rfp/ws/{rfp_id})
    application.include_router(health_router, tags=["Health"])
    application.include_router(rfp_router, prefix="/api/rfp", tags=["RFP"])
    application.include_router(knowledge_router, prefix="/api/knowledge", tags=["Knowledge"])

    # Serve frontend static files
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
    if frontend_dir.exists():
        application.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

        @application.get("/")
        async def serve_frontend():
            return FileResponse(str(frontend_dir / "index.html"))

    @application.on_event("startup")
    async def startup():
        # Give the PipelineProgress singleton the server's event loop
        # so background pipeline threads can push WebSocket messages.
        PipelineProgress.get().set_loop(asyncio.get_running_loop())
        logger.info(f"Starting {settings.app_name} API")
        logger.info(f"Dashboard: http://localhost:8000/")

    return application


# Module-level instance for `uvicorn rfp_automation.api:app`
app = create_app()

```

## File: `rfp_automation\mcp\knowledge_loader.py`

```python
"""
Knowledge Loader — utility to seed company knowledge into Pinecone + MongoDB.

Usage:
    python -m rfp_automation.mcp.knowledge_loader          # seed all
    python -m rfp_automation.mcp.knowledge_loader --type capabilities
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from rfp_automation.config import get_settings
from rfp_automation.mcp.vector_store.knowledge_store import KnowledgeStore

logger = logging.getLogger(__name__)

# Default path to seed data (relative to this file)
_DATA_DIR = Path(__file__).parent / "knowledge_data"


def _load_json(filename: str) -> Any:
    """Read a JSON file from the knowledge_data directory."""
    path = _DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Seed file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def seed_capabilities(store: KnowledgeStore) -> int:
    """Seed company capabilities into Pinecone knowledge namespace."""
    caps = _load_json("capabilities.json")
    texts = [
        f"{c['name']}: {c['description']} Evidence: {c.get('evidence', '')}"
        for c in caps
    ]
    metadatas = [
        {
            "id": c["id"],
            "name": c["name"],
            "category": c.get("category", ""),
            "tags": ",".join(c.get("tags", [])),
        }
        for c in caps
    ]
    return store.ingest_company_docs(texts, metadatas, doc_type="capability")


def seed_past_proposals(store: KnowledgeStore) -> int:
    """Seed past winning proposals into Pinecone knowledge namespace."""
    proposals = _load_json("past_proposals.json")
    texts = [
        f"{p['title']}: {p['excerpt']} Outcome: {p.get('outcome', '')}"
        for p in proposals
    ]
    metadatas = [
        {
            "id": p["id"],
            "title": p["title"],
            "category": p.get("category", ""),
            "tags": ",".join(p.get("tags", [])),
        }
        for p in proposals
    ]
    return store.ingest_company_docs(texts, metadatas, doc_type="past_proposal")


def seed_certifications_to_mongo(store: KnowledgeStore) -> None:
    """Seed certification holdings into MongoDB company_config."""
    certs = _load_json("certifications.json")
    db = store._get_db()
    db.company_config.update_one(
        {"config_type": "certifications"},
        {"$set": {"config_type": "certifications", "certifications": certs}},
        upsert=True,
    )
    held = sum(1 for v in certs.values() if v)
    logger.info(f"Seeded {len(certs)} certifications ({held} held) into MongoDB")


def seed_pricing_rules_to_mongo(store: KnowledgeStore) -> None:
    """Seed pricing rules into MongoDB company_config."""
    rules = _load_json("pricing_rules.json")
    db = store._get_db()
    db.company_config.update_one(
        {"config_type": "pricing_rules"},
        {"$set": {"config_type": "pricing_rules", "rules": rules}},
        upsert=True,
    )
    logger.info("Seeded pricing rules into MongoDB")


def seed_legal_templates_to_mongo(store: KnowledgeStore) -> None:
    """Seed legal templates into MongoDB company_config."""
    templates = _load_json("legal_templates.json")
    db = store._get_db()
    db.company_config.update_one(
        {"config_type": "legal_templates"},
        {"$set": {"config_type": "legal_templates", "templates": templates}},
        upsert=True,
    )
    logger.info(f"Seeded {len(templates)} legal templates into MongoDB")


def seed_all() -> dict[str, int | str]:
    """Run all seed operations. Returns a summary dict."""
    store = KnowledgeStore()
    results: dict[str, int | str] = {}

    logger.info("═" * 50)
    logger.info("  SEEDING COMPANY KNOWLEDGE")
    logger.info("═" * 50)

    # Pinecone vectors
    results["capabilities"] = seed_capabilities(store)
    results["past_proposals"] = seed_past_proposals(store)

    # MongoDB structured data
    seed_certifications_to_mongo(store)
    results["certifications"] = "seeded"

    seed_pricing_rules_to_mongo(store)
    results["pricing_rules"] = "seeded"

    seed_legal_templates_to_mongo(store)
    results["legal_templates"] = "seeded"

    logger.info(f"Seed results: {results}")
    return results


# ── CLI entry point ──────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    parser = argparse.ArgumentParser(description="Seed company knowledge")
    parser.add_argument(
        "--type",
        choices=["capabilities", "proposals", "certifications", "pricing", "legal", "all"],
        default="all",
        help="Which data to seed (default: all)",
    )
    args = parser.parse_args()

    store = KnowledgeStore()

    if args.type == "all":
        seed_all()
    elif args.type == "capabilities":
        seed_capabilities(store)
    elif args.type == "proposals":
        seed_past_proposals(store)
    elif args.type == "certifications":
        seed_certifications_to_mongo(store)
    elif args.type == "pricing":
        seed_pricing_rules_to_mongo(store)
    elif args.type == "legal":
        seed_legal_templates_to_mongo(store)

    print("Done.")

```

## File: `rfp_automation\mcp\mcp_server.py`

```python
"""
MCPService — the ONLY class agents should import.

This is the facade over:
  • RFP Vector Store   (embed + query incoming RFP chunks)
  • Knowledge Base     (company capabilities, certs, pricing, legal templates)
  • Rules Engine       (policy / validation / commercial-legal gates)

Internally the stores use embeddings/ helpers
but agents never see those.
"""

from __future__ import annotations

import logging
from typing import Any

from rfp_automation.services.parsing_service import ParsingService

logger = logging.getLogger(__name__)


class MCPService:
    """
    Facade over all MCP layers.
    Agents depend on this single class.

    Usage in any agent:
        from rfp_automation.mcp import MCPService
        mcp = MCPService()
        mcp.store_rfp_document(rfp_id, raw_text, metadata)
        chunks = mcp.query_rfp("security requirements", rfp_id)
    """

    def __init__(self):
        from .vector_store.rfp_store import RFPVectorStore
        from .vector_store.knowledge_store import KnowledgeStore
        from .rules.policy_rules import PolicyRules
        from .rules.validation_rules import ValidationRules
        from .rules.commercial_rules import CommercialRules
        from .rules.legal_rules import LegalRules

        self.rfp_store = RFPVectorStore()
        self.knowledge_base = KnowledgeStore()
        self.policy_rules = PolicyRules()
        self.validation_rules = ValidationRules()
        self.commercial_rules = CommercialRules()
        self.legal_rules = LegalRules()

    # ── Convenience: RFP document storage ────────────────

    def store_rfp_document(
        self,
        rfp_id: str,
        raw_text: str,
        metadata: dict[str, Any] | None = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> int:
        """
        Convenience: chunk raw_text, embed, and store into Pinecone.
        Used by Intake Agent.  Returns chunk count.
        """
        return self.rfp_store.embed_document(
            rfp_id=rfp_id,
            raw_text=raw_text,
            metadata=metadata,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    # ── Convenience: Structured chunk storage ────────────

    def store_rfp_chunks(
        self,
        rfp_id: str,
        chunks: list[dict[str, Any]],
        source_file: str = "",
    ) -> int:
        """
        Embed pre-structured chunks and store into Pinecone.
        Each chunk must have: chunk_id, content_type, section_hint,
        text, page_start, page_end.
        Returns vector count.
        """
        logger.debug(f"[MCPService] store_rfp_chunks: rfp_id={rfp_id}, {len(chunks)} chunks, source={source_file}")
        extra = {"source_file": source_file} if source_file else {}
        count = self.rfp_store.embed_chunks(rfp_id, chunks, extra_metadata=extra)
        logger.info(f"[MCPService] Stored {count} vectors for {rfp_id}")
        return count

    # ── Convenience: RFP query ───────────────────────────

    def query_rfp(
        self,
        query: str,
        rfp_id: str = "",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Convenience: semantic search over RFP chunks."""
        logger.debug(f"[MCPService] query_rfp: q={query[:60]!r}, rfp_id={rfp_id}, top_k={top_k}")
        results = self.rfp_store.query(query, rfp_id, top_k)
        logger.debug(f"[MCPService] query_rfp returned {len(results)} results")
        return results

    # ── Convenience: RFP full retrieval ────────────────────

    def query_rfp_all_chunks(
        self,
        rfp_id: str,
        top_k: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve all chunks for an RFP (for full-document classification)."""
        logger.debug(f"[MCPService] query_rfp_all_chunks: rfp_id={rfp_id}, top_k={top_k}")
        results = self.rfp_store.query_all(rfp_id, top_k)
        logger.debug(f"[MCPService] query_rfp_all_chunks returned {len(results)} chunks")
        return results

    # ── Convenience: Knowledge query ─────────────────────

    def query_knowledge(
        self,
        query: str,
        top_k: int = 5,
        doc_type: str = "",
    ) -> list[dict[str, Any]]:
        """Convenience: semantic search over company knowledge. If doc_type is empty, search all."""
        logger.debug(f"[MCPService] query_knowledge: q={query[:60]!r}, doc_type={doc_type!r}, top_k={top_k}")
        if doc_type:
            results = self.knowledge_base.query_by_type(query, doc_type, top_k)
        else:
            results = self.knowledge_base.query_all_types(query, top_k)
        logger.debug(f"[MCPService] query_knowledge returned {len(results)} results")
        return results

    # ── Knowledge base admin ─────────────────────────────

    def ingest_knowledge_doc(
        self,
        doc_type: str,
        texts: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> int:
        """Ingest company documents into the knowledge namespace."""
        return self.knowledge_base.ingest_company_docs(texts, metadatas, doc_type)

    def store_knowledge_config(
        self,
        config_type: str,
        data: dict[str, Any],
    ) -> None:
        """Store structured config (certifications, pricing, legal) in MongoDB."""
        db = self.knowledge_base._get_db()
        db.company_config.update_one(
            {"config_type": config_type},
            {"$set": {"config_type": config_type, **data}},
            upsert=True,
        )
        logger.info(f"[MCPService] Stored {config_type} config in MongoDB")

    def get_knowledge_stats(self) -> dict[str, Any]:
        """Return knowledge base stats: Pinecone vectors + MongoDB configs."""
        stats: dict[str, Any] = {
            "pinecone": {"total_vectors": 0, "namespaces": {}},
            "mongodb": {"configs": []},
        }

        try:
            index = self.knowledge_base._get_index()
            idx_stats = index.describe_index_stats()
            total = getattr(idx_stats, "total_vector_count", 0)
            namespaces_raw = getattr(idx_stats, "namespaces", {})

            ns_dict = {}
            if isinstance(namespaces_raw, dict):
                for k, v in namespaces_raw.items():
                    ns_dict[k] = getattr(v, "vector_count", 0) if not isinstance(v, dict) else v.get("vector_count", 0)
            stats["pinecone"] = {"total_vectors": total, "namespaces": ns_dict}
        except Exception as e:
            stats["pinecone"]["error"] = str(e)

        try:
            db = self.knowledge_base._get_db()
            configs = list(db.company_config.find({}, {"_id": 0, "config_type": 1}))
            stats["mongodb"]["configs"] = [c["config_type"] for c in configs]
        except Exception as e:
            stats["mongodb"]["error"] = str(e)

        return stats

    # ── Pre-extracted policies (from JSON file) ────────

    def get_extracted_policies(self, category: str = "") -> list[dict[str, Any]]:
        """Read pre-extracted policies from the JSON file, optionally filtered by category."""
        from rfp_automation.services.policy_extraction_service import PolicyExtractionService
        policies = PolicyExtractionService.get_all_policies()
        if category:
            policies = [p for p in policies if p.get("category") == category]
        logger.debug(f"[MCPService] get_extracted_policies(category={category!r}): {len(policies)} policies")
        return policies

    def get_certifications_from_policies(self) -> dict[str, bool]:
        """Derive a cert map from extracted policies where category='certification'."""
        cert_policies = self.get_extracted_policies(category="certification")
        return {p.get("policy_text", ""): True for p in cert_policies if p.get("policy_text")}

    # ── Health check ─────────────────────────────────────

    async def health_check(self) -> dict[str, Any]:
        """Check connectivity of all sub-services."""
        status: dict[str, Any] = {
            "rfp_store": False,
            "knowledge_base": False,
            "rules_engine": True,  # rules are local/cached
        }

        try:
            self.rfp_store._get_index()
            status["rfp_store"] = True
        except Exception as e:
            status["rfp_store_error"] = str(e)

        try:
            self.knowledge_base._get_index()
            status["knowledge_base"] = True
        except Exception as e:
            status["knowledge_base_error"] = str(e)

        return status

```

## File: `rfp_automation\mcp\__init__.py`

```python
"""
MCP — the single boundary agents interact with.

Agents import ONLY from this package:
    from rfp_automation.mcp import MCPService

They never touch internal modules (embedding, vector DB).
"""

from .mcp_server import MCPService

__all__ = ["MCPService"]

```

## File: `rfp_automation\mcp\embeddings\embedding_model.py`

```python
"""
Embedding Model — generates vector embeddings for text.
Uses Sentence Transformers (all-MiniLM-L6-v2 by default, 384 dimensions).
"""

from __future__ import annotations

import logging

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """Generate embeddings for text chunks. Singleton-friendly."""

    def __init__(self):
        self.settings = get_settings()
        self._model = None
        self._dimension: int | None = None

    def _load_model(self):
        """Lazy-load the embedding model on first use."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.settings.embedding_model)
            self._dimension = self._model.get_sentence_embedding_dimension()
            logger.info(
                f"Loaded embedding model: {self.settings.embedding_model} "
                f"(dim={self._dimension})"
            )

    @property
    def dimension(self) -> int:
        """Return the embedding vector dimension (e.g. 384 for all-MiniLM-L6-v2)."""
        self._load_model()
        return self._dimension  # type: ignore[return-value]

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        self._load_model()
        embeddings = self._model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()

    def embed_single(self, text: str) -> list[float]:
        """Embed a single text string."""
        return self.embed([text])[0]

```

## File: `rfp_automation\mcp\embeddings\__init__.py`

```python

```

## File: `rfp_automation\mcp\knowledge_data\capabilities.json`

```json
[
  {
    "id": "cap-001",
    "name": "Cloud Infrastructure & Migration",
    "description": "End-to-end cloud infrastructure design, deployment, and migration services across AWS, Azure, and GCP. Includes lift-and-shift, re-platforming, and cloud-native application development.",
    "category": "cloud",
    "tags": ["aws", "azure", "gcp", "migration", "infrastructure"],
    "evidence": "Successfully migrated 50+ enterprise workloads to cloud, achieving average 40% cost reduction."
  },
  {
    "id": "cap-002",
    "name": "Cybersecurity & Compliance",
    "description": "Comprehensive cybersecurity services including threat assessment, penetration testing, SIEM deployment, zero-trust architecture, and compliance framework implementation (NIST, SOC 2, ISO 27001).",
    "category": "security",
    "tags": ["cybersecurity", "compliance", "penetration-testing", "SIEM", "zero-trust"],
    "evidence": "Achieved SOC 2 Type II compliance for 20+ clients. Zero major security incidents across managed services."
  },
  {
    "id": "cap-003",
    "name": "DevOps & CI/CD Automation",
    "description": "DevOps transformation services including CI/CD pipeline design, Infrastructure as Code (Terraform, Pulumi), container orchestration (Kubernetes, Docker), and GitOps workflows.",
    "category": "devops",
    "tags": ["devops", "ci-cd", "kubernetes", "terraform", "docker", "gitops"],
    "evidence": "Reduced deployment frequency from monthly to daily for Fortune 500 clients. 99.95% pipeline reliability."
  },
  {
    "id": "cap-004",
    "name": "AI/ML Solutions & Data Engineering",
    "description": "Machine learning model development, MLOps pipelines, NLP solutions, computer vision, and large-scale data engineering. Experience with LLMs, RAG architectures, and AI governance.",
    "category": "ai_ml",
    "tags": ["machine-learning", "nlp", "computer-vision", "data-engineering", "llm", "rag"],
    "evidence": "Deployed 30+ production ML models. Built enterprise RAG systems processing 10M+ documents."
  },
  {
    "id": "cap-005",
    "name": "Enterprise Application Development",
    "description": "Full-stack application development using modern frameworks (React, Angular, .NET, Java Spring). Microservices architecture, API design, and legacy system modernization.",
    "category": "development",
    "tags": ["full-stack", "microservices", "api", "react", "java", "dotnet"],
    "evidence": "Delivered 100+ enterprise applications. Average 35% improvement in system performance after modernization."
  },
  {
    "id": "cap-006",
    "name": "Data Analytics & Business Intelligence",
    "description": "End-to-end data analytics solutions including data warehousing (Snowflake, BigQuery), ETL pipelines, dashboard development (Power BI, Tableau), and advanced analytics.",
    "category": "analytics",
    "tags": ["analytics", "business-intelligence", "data-warehouse", "etl", "power-bi", "tableau"],
    "evidence": "Built data platforms processing 5TB+ daily. Enabled data-driven decision making for 40+ organizations."
  },
  {
    "id": "cap-007",
    "name": "Managed IT Services & Support",
    "description": "24/7 managed services including infrastructure monitoring, incident response, helpdesk support, patch management, and SLA-backed service delivery.",
    "category": "managed_services",
    "tags": ["managed-services", "monitoring", "incident-response", "helpdesk", "sla"],
    "evidence": "99.99% uptime SLA achievement across 200+ managed environments. Average 15-minute incident response time."
  },
  {
    "id": "cap-008",
    "name": "Project & Program Management",
    "description": "PMO services, Agile transformation, project delivery using Scrum/SAFe/Kanban, risk management, and stakeholder communication. PMP and SAFe certified team.",
    "category": "project_management",
    "tags": ["project-management", "agile", "scrum", "safe", "pmo"],
    "evidence": "95% on-time delivery rate across 500+ projects. Average client satisfaction score of 4.7/5.0."
  },
  {
    "id": "cap-009",
    "name": "Network & Telecommunications",
    "description": "Network design and implementation, SD-WAN, VPN, unified communications, and network security. Expertise in Cisco, Palo Alto, and Fortinet platforms.",
    "category": "networking",
    "tags": ["networking", "sd-wan", "vpn", "telecommunications", "cisco"],
    "evidence": "Designed and deployed networks for 50+ locations. Average 60% improvement in network performance."
  },
  {
    "id": "cap-010",
    "name": "Digital Transformation & Consulting",
    "description": "Strategic technology consulting, digital transformation roadmaps, technology assessment, vendor selection, and organizational change management.",
    "category": "consulting",
    "tags": ["consulting", "digital-transformation", "strategy", "change-management"],
    "evidence": "Guided 25+ organizations through digital transformation. Average ROI of 300% within 18 months."
  },
  {
    "id": "cap-011",
    "name": "Government & Public Sector Solutions",
    "description": "FedRAMP-compliant cloud solutions, government-grade security implementations, and public sector digital services. Experience with federal, state, and local government contracts.",
    "category": "government",
    "tags": ["government", "fedramp", "public-sector", "compliance", "federal"],
    "evidence": "Delivered 15+ government contracts worth $50M+. FedRAMP Moderate authorization achieved for 3 platforms."
  },
  {
    "id": "cap-012",
    "name": "Quality Assurance & Testing",
    "description": "Comprehensive QA services including automated testing, performance testing, security testing, accessibility testing, and test strategy development.",
    "category": "qa",
    "tags": ["qa", "testing", "automation", "performance-testing", "accessibility"],
    "evidence": "Achieved 95%+ automated test coverage for enterprise clients. Reduced production defects by 70% on average."
  }
]

```

## File: `rfp_automation\mcp\knowledge_data\certifications.json`

```json
{
    "ISO 27001": true,
    "SOC 2 Type II": true,
    "SOC 2 Type I": true,
    "FedRAMP Moderate": true,
    "FedRAMP High": false,
    "HIPAA": true,
    "PCI DSS": true,
    "GDPR Compliance": true,
    "CMMC Level 2": false,
    "CMMC Level 3": false,
    "StateRAMP": false,
    "NIST 800-53": true,
    "NIST 800-171": true,
    "CSA STAR": true,
    "ITIL v4": true,
    "AWS Solutions Architect Partner": true,
    "Azure Gold Partner": true,
    "Google Cloud Partner": true,
    "CISA Certified": true,
    "CISSP Certified Staff": true
}
```

## File: `rfp_automation\mcp\knowledge_data\extracted_policies.json`

```json
[
  {
    "policy_id": "POL-001",
    "policy_text": "To become a new generation connectivity and digital services provider for Europe and Africa, enabling an inclusive and sustainable digital society.",
    "category": "governance",
    "rule_type": "capability",
    "severity": "high",
    "source_section": "Company Profile & Executive Summary",
    "source_doc_id": "KB-D18BAAE6",
    "source_filename": "Vodafone Company Profile.pdf",
    "created_at": "2026-02-20T16:13:19.277460+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-002",
    "policy_text": "Connecting people and businesses globally – Facilitating communication and collaboration across geographical boundaries through seamless connectivity solutions",
    "category": "capability",
    "rule_type": "capability",
    "severity": "medium",
    "source_section": "Company Profile & Executive Summary",
    "source_doc_id": "KB-D18BAAE6",
    "source_filename": "Vodafone Company Profile.pdf",
    "created_at": "2026-02-20T16:13:19.277460+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-003",
    "policy_text": "Driving digital inclusion and sustainable practices – Making technology accessible to underserved communities while pursuing environmental sustainability with a net-zero emissions target by 2040",
    "category": "governance",
    "rule_type": "requirement",
    "severity": "high",
    "source_section": "Company Profile & Executive Summary",
    "source_doc_id": "KB-D18BAAE6",
    "source_filename": "Vodafone Company Profile.pdf",
    "created_at": "2026-02-20T16:13:19.277460+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-004",
    "policy_text": "Delivering superior customer experiences through technological innovation – Investing in cutting-edge technologies including 5G, artificial intelligence, and IoT to provide faster, more reliable, and personalized services",
    "category": "capability",
    "rule_type": "capability",
    "severity": "medium",
    "source_section": "Company Profile & Executive Summary",
    "source_doc_id": "KB-D18BAAE6",
    "source_filename": "Vodafone Company Profile.pdf",
    "created_at": "2026-02-20T16:13:19.277460+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-005",
    "policy_text": "Development of next-generation networks with significant investments in 5G infrastructure across key markets",
    "category": "capability",
    "rule_type": "capability",
    "severity": "medium",
    "source_section": "Company Profile & Executive Summary",
    "source_doc_id": "KB-D18BAAE6",
    "source_filename": "Vodafone Company Profile.pdf",
    "created_at": "2026-02-20T16:13:19.277460+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-006",
    "policy_text": "Creation of an inclusive digital ecosystem that bridges the digital divide, particularly in underserved rural communities",
    "category": "governance",
    "rule_type": "requirement",
    "severity": "high",
    "source_section": "Company Profile & Executive Summary",
    "source_doc_id": "KB-D18BAAE6",
    "source_filename": "Vodafone Company Profile.pdf",
    "created_at": "2026-02-20T16:13:19.277460+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-007",
    "policy_text": "Environmental sustainability through renewable energy adoption and carbon emission reduction initiatives",
    "category": "governance",
    "rule_type": "requirement",
    "severity": "high",
    "source_section": "Company Profile & Executive Summary",
    "source_doc_id": "KB-D18BAAE6",
    "source_filename": "Vodafone Company Profile.pdf",
    "created_at": "2026-02-20T16:13:19.277460+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-008",
    "policy_text": "Innovation in digital services including cloud computing, IoT platforms, cybersecurity, and unified communications",
    "category": "capability",
    "rule_type": "capability",
    "severity": "medium",
    "source_section": "Company Profile & Executive Summary",
    "source_doc_id": "KB-D18BAAE6",
    "source_filename": "Vodafone Company Profile.pdf",
    "created_at": "2026-02-20T16:13:19.277460+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-009",
    "policy_text": "Financial inclusion through mobile payment solutions, notably M-Pesa, which has transformed financial access in emerging markets",
    "category": "capability",
    "rule_type": "capability",
    "severity": "medium",
    "source_section": "Company Profile & Executive Summary",
    "source_doc_id": "KB-D18BAAE6",
    "source_filename": "Vodafone Company Profile.pdf",
    "created_at": "2026-02-20T16:13:19.277460+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-010",
    "policy_text": "Net-zero emissions target by 2040",
    "category": "governance",
    "rule_type": "requirement",
    "severity": "critical",
    "source_section": "Company Profile & Executive Summary",
    "source_doc_id": "KB-D18BAAE6",
    "source_filename": "Vodafone Company Profile.pdf",
    "created_at": "2026-02-20T16:13:19.277460+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-011",
    "policy_text": "The document is intended for internal teams involved in marketing, communications, product development, and commercial strategy.",
    "category": "governance",
    "rule_type": "constraint",
    "severity": "medium",
    "source_section": "1. Executive Summary",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-012",
    "policy_text": "Vi operates in one of the world's largest and fastest-growing telecom markets, with over 1.4 billion people and rapid digital adoption across urban and semi-urban geographies.",
    "category": "operational",
    "rule_type": "capability",
    "severity": "low",
    "source_section": "1. Executive Summary",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-013",
    "policy_text": "The brand's mission is to connect India, empower communities, and drive the digital economy through accessible, reliable, and innovative communication services.",
    "category": "governance",
    "rule_type": "requirement",
    "severity": "high",
    "source_section": "1. Executive Summary",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-014",
    "policy_text": "Vi's Vision: Connecting Every Indian to a Better Tomorrow",
    "category": "governance",
    "rule_type": "requirement",
    "severity": "high",
    "source_section": "1. Executive Summary",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-015",
    "policy_text": "Total Wireless Subscribers ~1.17 Billion",
    "category": "operational",
    "rule_type": "threshold",
    "severity": "low",
    "source_section": "2.1 Indian Telecom Market Overview",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-016",
    "policy_text": "Internet Subscribers ~900 Million",
    "category": "operational",
    "rule_type": "threshold",
    "severity": "low",
    "source_section": "2.1 Indian Telecom Market Overview",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-017",
    "policy_text": "4G Subscribers ~700 Million",
    "category": "operational",
    "rule_type": "threshold",
    "severity": "low",
    "source_section": "2.1 Indian Telecom Market Overview",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-018",
    "policy_text": "5G Subscribers (emerging) ~80 Million+",
    "category": "operational",
    "rule_type": "threshold",
    "severity": "low",
    "source_section": "2.1 Indian Telecom Market Overview",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-019",
    "policy_text": "Monthly Data Usage per User ~20 GB",
    "category": "operational",
    "rule_type": "threshold",
    "severity": "low",
    "source_section": "2.1 Indian Telecom Market Overview",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-020",
    "policy_text": "Average Revenue Per User (ARPU) INR 140–200",
    "category": "commercial",
    "rule_type": "threshold",
    "severity": "medium",
    "source_section": "2.1 Indian Telecom Market Overview",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-021",
    "policy_text": "5G coverage expected to reach 50+ cities by end of FY25 for major operators",
    "category": "operational",
    "rule_type": "requirement",
    "severity": "high",
    "source_section": "2.2.1 5G Rollout & Network Evolution",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-022",
    "policy_text": "Spectrum bands in use: Sub-GHz (700 MHz), mid-band (3.5 GHz), mmWave (26 GHz)",
    "category": "operational",
    "rule_type": "standard",
    "severity": "medium",
    "source_section": "2.2.1 5G Rollout & Network Evolution",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-023",
    "policy_text": "Enterprise 5G services — network slicing, private 5G — emerging as high-value segments",
    "category": "operational",
    "rule_type": "capability",
    "severity": "low",
    "source_section": "2.2.1 5G Rollout & Network Evolution",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-024",
    "policy_text": "OTT video accounts for 60%+ of total mobile data traffic in India",
    "category": "operational",
    "rule_type": "threshold",
    "severity": "low",
    "source_section": "2.2.2 Rising Data Consumption",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-025",
    "policy_text": "Online gaming subscribers growing at 25% CAGR",
    "category": "operational",
    "rule_type": "threshold",
    "severity": "low",
    "source_section": "2.2.2 Rising Data Consumption",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-026",
    "policy_text": "Vernacular content fueling digital adoption in Tier-2 and Tier-3 cities",
    "category": "operational",
    "rule_type": "capability",
    "severity": "low",
    "source_section": "2.2.2 Rising Data Consumption",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-027",
    "policy_text": "After years of aggressive price wars sparked by Jio's 2016 entry, the industry is entering a premiumization phase.",
    "category": "commercial",
    "rule_type": "requirement",
    "severity": "high",
    "source_section": "2.2.3 Premiumization & ARPU Improvement",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-028",
    "policy_text": "Multiple tariff hikes across all operators in 2023–24 have lifted ARPUs.",
    "category": "commercial",
    "rule_type": "requirement",
    "severity": "high",
    "source_section": "2.2.3 Premiumization & ARPU Improvement",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-029",
    "policy_text": "Higher-value postpaid plans, family bundles, and enterprise offerings are being prioritized.",
    "category": "commercial",
    "rule_type": "requirement",
    "severity": "high",
    "source_section": "2.2.3 Premiumization & ARPU Improvement",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-030",
    "policy_text": "Telecom operators are increasingly becoming digital service providers.",
    "category": "operational",
    "rule_type": "capability",
    "severity": "low",
    "source_section": "2.2.4 Convergence of Telecom & Digital Services",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-031",
    "policy_text": "Vi's partnerships with OTT platforms (Netflix, Amazon Prime, SonyLIV) are central to its value proposition, transforming SIM cards into digital lifestyle subscriptions.",
    "category": "operational",
    "rule_type": "capability",
    "severity": "low",
    "source_section": "2.2.4 Convergence of Telecom & Digital Services",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-032",
    "policy_text": "Rural tele-density still below 60% — significant headroom for subscriber addition",
    "category": "operational",
    "rule_type": "threshold",
    "severity": "low",
    "source_section": "2.2.5 Rural & Semi-Urban Expansion",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-033",
    "policy_text": "Feature phone-to-smartphone upgrade cycle continues in rural India",
    "category": "operational",
    "rule_type": "capability",
    "severity": "low",
    "source_section": "2.2.5 Rural & Semi-Urban Expansion",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-034",
    "policy_text": "Prepaid dominates rural mix; opportunity to upsell higher-value data packs",
    "category": "commercial",
    "rule_type": "requirement",
    "severity": "medium",
    "source_section": "2.2.5 Rural & Semi-Urban Expansion",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-035",
    "policy_text": "India's Department of Telecommunications (DoT) and TRAI (Telecom Regulatory Authority of India) continue to shape competitive dynamics.",
    "category": "compliance",
    "rule_type": "requirement",
    "severity": "critical",
    "source_section": "2.2.6 Regulatory Environment",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-036",
    "policy_text": "Key regulatory developments include: spectrum auction outcomes, the new Telecom Act 2023 (replacing the 138-year-old Telegraph Act), interconnection regulations, and data localization requirements.",
    "category": "compliance",
    "rule_type": "requirement",
    "severity": "critical",
    "source_section": "2.2.6 Regulatory Environment",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-037",
    "policy_text": "Favorable policy — including the government's equity stake in Vi and AGR relief measures — has been critical to Vi's financial restructuring.",
    "category": "compliance",
    "rule_type": "requirement",
    "severity": "critical",
    "source_section": "2.2.6 Regulatory Environment",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-038",
    "policy_text": "Vodafone Idea Limited trades commercially as 'Vi' — a unified brand launched in September 2020, merging the legacy Vodafone India and Idea Cellular identities.",
    "category": "governance",
    "rule_type": "requirement",
    "severity": "high",
    "source_section": "3. Brand Guidelines & Identity",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-039",
    "policy_text": "The Vi brand represents togetherness, optimism, and digital empowerment.",
    "category": "governance",
    "rule_type": "requirement",
    "severity": "high",
    "source_section": "3. Brand Guidelines & Identity",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  },
  {
    "policy_id": "POL-040",
    "policy_text": "It retains equity from both parent brands while projecting a fresh, youthful, and inclusive identity.",
    "category": "governance",
    "rule_type": "requirement",
    "severity": "high",
    "source_section": "3. Brand Guidelines & Identity",
    "source_doc_id": "KB-05564643",
    "source_filename": "Vodafone_India_Marketing_Brand_Guide.pdf",
    "created_at": "2026-02-20T16:14:10.622545+00:00",
    "is_manually_added": false
  }
]
```

## File: `rfp_automation\mcp\knowledge_data\legal_templates.json`

```json
[
    {
        "id": "legal-001",
        "clause_type": "limitation_of_liability",
        "acceptable_template": "Contractor's total aggregate liability under this Agreement shall not exceed the total fees paid under this Agreement during the twelve (12) months preceding the claim.",
        "risk_threshold": "Unlimited liability or liability exceeding 2x contract value",
        "auto_block": true,
        "notes": "Never accept unlimited liability clauses."
    },
    {
        "id": "legal-002",
        "clause_type": "intellectual_property",
        "acceptable_template": "All pre-existing intellectual property remains the property of the originating party. Work product created specifically for this engagement shall be owned by the Client upon full payment.",
        "risk_threshold": "Broad IP transfer that includes pre-existing IP or derivative works",
        "auto_block": true,
        "notes": "Protect pre-existing IP and tools."
    },
    {
        "id": "legal-003",
        "clause_type": "indemnification",
        "acceptable_template": "Each party shall indemnify the other for claims arising from its own negligence, willful misconduct, or breach of its representations and warranties under this Agreement.",
        "risk_threshold": "One-sided indemnification with no mutual obligation",
        "auto_block": false,
        "notes": "Flag but negotiate. Block only if extremely one-sided."
    },
    {
        "id": "legal-004",
        "clause_type": "termination",
        "acceptable_template": "Either party may terminate this Agreement for convenience upon sixty (60) days written notice. Termination for cause requires thirty (30) days written notice and opportunity to cure.",
        "risk_threshold": "Client-only termination for convenience without notice period",
        "auto_block": false,
        "notes": "Ensure mutual termination rights."
    },
    {
        "id": "legal-005",
        "clause_type": "non_compete",
        "acceptable_template": "During the term of this Agreement, Contractor shall not provide substantially similar services to a direct named competitor of Client within the same geographic market.",
        "risk_threshold": "Broad non-compete exceeding 2 years or covering all industries",
        "auto_block": true,
        "notes": "Block overly broad non-compete clauses."
    },
    {
        "id": "legal-006",
        "clause_type": "data_protection",
        "acceptable_template": "Contractor shall process Client data in accordance with applicable data protection laws including GDPR and CCPA. A Data Processing Agreement shall be executed as an addendum.",
        "risk_threshold": "No data protection provisions or unrestricted data sharing",
        "auto_block": false,
        "notes": "Do not accept contracts without data protection clauses."
    },
    {
        "id": "legal-007",
        "clause_type": "warranty",
        "acceptable_template": "Contractor warrants that services will be performed in a professional and workmanlike manner consistent with generally accepted industry standards for a period of ninety (90) days following delivery.",
        "risk_threshold": "Warranty period exceeding 12 months or covering fitness for particular purpose",
        "auto_block": false,
        "notes": "Standard 90-day warranty. Flag anything beyond 12 months."
    },
    {
        "id": "legal-008",
        "clause_type": "confidentiality",
        "acceptable_template": "Both parties shall maintain the confidentiality of all confidential information for three (3) years following disclosure. Standard exceptions apply for publicly known information.",
        "risk_threshold": "Perpetual confidentiality obligation with no standard exceptions",
        "auto_block": false,
        "notes": "Perpetual obligations are a yellow flag."
    }
]
```

## File: `rfp_automation\mcp\knowledge_data\past_proposals.json`

```json
[
    {
        "id": "prop-001",
        "title": "Enterprise Cloud Migration for National Bank",
        "category": "cloud",
        "excerpt": "Our team successfully migrated 200+ applications from on-premises data centers to AWS over an 18-month engagement. We employed a phased approach: discovery and assessment (3 months), pilot migration of 20 non-critical applications (3 months), and full migration of remaining workloads (12 months). Key outcomes included 42% reduction in infrastructure costs, 99.99% uptime during migration, and zero data loss. We utilized AWS Migration Hub for tracking, CloudEndure for live migration, and custom Terraform modules for infrastructure provisioning.",
        "outcome": "Won - $4.2M contract, completed on time and under budget",
        "tags": [
            "cloud",
            "migration",
            "aws",
            "banking",
            "enterprise"
        ]
    },
    {
        "id": "prop-002",
        "title": "Cybersecurity Overhaul for Healthcare Provider",
        "category": "security",
        "excerpt": "We designed and implemented a comprehensive cybersecurity program for a multi-site healthcare organization handling 500,000+ patient records. The engagement covered zero-trust network architecture implementation, SIEM deployment (Splunk), endpoint detection and response (CrowdStrike), security awareness training for 3,000 employees, and HIPAA compliance validation. We achieved SOC 2 Type II certification within 8 months and reduced security incidents by 85%.",
        "outcome": "Won - $2.8M contract, client renewed for 3 additional years",
        "tags": [
            "security",
            "healthcare",
            "hipaa",
            "compliance",
            "zero-trust"
        ]
    },
    {
        "id": "prop-003",
        "title": "AI-Powered Document Processing for Insurance Company",
        "category": "ai_ml",
        "excerpt": "We developed an intelligent document processing system that automated the extraction and classification of insurance claims documents. The solution used OCR (Tesseract + custom models), NLP for entity extraction, and a RAG-based Q&A system for claims adjusters. Processing time decreased from 45 minutes per claim to 3 minutes, with 97% extraction accuracy. The system handled 10,000+ documents daily and integrated with the client's existing Guidewire platform.",
        "outcome": "Won - $1.5M initial contract + $800K annual maintenance",
        "tags": [
            "ai",
            "ml",
            "nlp",
            "document-processing",
            "insurance",
            "rag"
        ]
    },
    {
        "id": "prop-004",
        "title": "DevOps Transformation for E-Commerce Platform",
        "category": "devops",
        "excerpt": "We led a DevOps transformation for a mid-size e-commerce platform serving 2M+ daily users. The engagement included migrating from manual deployments to fully automated CI/CD (GitLab CI + ArgoCD), containerizing 40+ microservices with Docker/Kubernetes, implementing Infrastructure as Code with Terraform, and establishing observability with Datadog. Deployment frequency increased from bi-weekly to 15x daily, lead time dropped from 2 weeks to 30 minutes, and MTTR decreased from 4 hours to 15 minutes.",
        "outcome": "Won - $1.2M contract, featured as case study at KubeCon",
        "tags": [
            "devops",
            "kubernetes",
            "ci-cd",
            "e-commerce",
            "terraform"
        ]
    },
    {
        "id": "prop-005",
        "title": "Government Portal Modernization",
        "category": "government",
        "excerpt": "We modernized a state government citizen services portal serving 8M+ residents. The legacy .NET 4.5 monolith was re-architected into microservices (Java Spring Boot + React), deployed on FedRAMP-authorized AWS GovCloud. We implemented WCAG 2.1 AA accessibility compliance, multi-language support, identity verification integration, and mobile-responsive design. Page load times improved from 8 seconds to under 1 second, and citizen satisfaction scores increased by 40%.",
        "outcome": "Won - $3.5M contract, awarded follow-on contracts for 2 additional agencies",
        "tags": [
            "government",
            "modernization",
            "fedramp",
            "accessibility",
            "cloud"
        ]
    }
]
```

## File: `rfp_automation\mcp\knowledge_data\pricing_rules.json`

```json
{
    "base_cost": 50000.0,
    "per_requirement_cost": 2000.0,
    "complexity_tiers": {
        "low": 1.0,
        "medium": 1.25,
        "high": 1.5,
        "critical": 2.0
    },
    "risk_margin_percent": 0.10,
    "currency": "USD",
    "discount_tiers": {
        "standard": 0.0,
        "preferred_client": 0.05,
        "strategic_partner": 0.10,
        "multi_year": 0.08
    },
    "payment_terms": "Net 30",
    "minimum_contract_value": 25000.0,
    "maximum_contract_value": 5000000.0,
    "minimum_margin_percent": 0.15,
    "maximum_discount_percent": 0.15
}
```

## File: `rfp_automation\mcp\rules\commercial_rules.py`

```python
"""
Commercial Rules — pricing constraints and commercial gate logic.
Applied at the E1 Commercial agent checkpoint.
Config loaded from MongoDB via RulesConfigStore.
"""

from __future__ import annotations

import logging
from typing import Any

from rfp_automation.mcp.rules.rules_config import RulesConfigStore

logger = logging.getLogger(__name__)


class CommercialRules:
    """E1 commercial pricing rules and constraints."""

    def __init__(self):
        self._config_store = RulesConfigStore()

    def validate_pricing(
        self,
        total_price: float,
        total_cost: float = 0.0,
        discount_percent: float = 0.0,
        payment_terms: str = "",
    ) -> list[dict[str, Any]]:
        """
        Validate pricing against commercial constraints.
        Returns list of violations: {rule, detail, severity}.
        """
        config = self._config_store.get_commercial_config()
        violations: list[dict[str, Any]] = []

        # ── Contract value cap ───────────────────────────
        if total_price > config.max_contract_value:
            violations.append({
                "rule": "contract_value_exceeded",
                "detail": (
                    f"Total price ${total_price:,.2f} exceeds max "
                    f"${config.max_contract_value:,.2f}"
                ),
                "severity": "high",
            })

        # ── Minimum margin check ─────────────────────────
        if total_cost > 0:
            margin = (total_price - total_cost) / total_price
            if margin < config.minimum_margin_percent:
                violations.append({
                    "rule": "margin_too_low",
                    "detail": (
                        f"Margin {margin:.1%} is below minimum "
                        f"{config.minimum_margin_percent:.1%}"
                    ),
                    "severity": "high",
                })

        # ── Discount limit ───────────────────────────────
        if discount_percent > config.maximum_discount_percent:
            violations.append({
                "rule": "discount_exceeded",
                "detail": (
                    f"Discount {discount_percent:.1%} exceeds maximum "
                    f"{config.maximum_discount_percent:.1%}"
                ),
                "severity": "medium",
            })

        # ── Payment terms validation ─────────────────────
        if payment_terms:
            terms_lower = payment_terms.lower()
            for risky in config.risky_payment_terms:
                if risky.lower() in terms_lower:
                    violations.append({
                        "rule": "risky_payment_terms",
                        "detail": f"Risky payment terms detected: '{payment_terms}'",
                        "severity": "medium",
                    })
                    break

        return violations

```

## File: `rfp_automation\mcp\rules\legal_rules.py`

```python
"""
Legal Rules — contract clause risk assessment and legal gate logic.
Applied at the E2 Legal agent checkpoint.
Config loaded from MongoDB via RulesConfigStore.
"""

from __future__ import annotations

import logging
from typing import Any

from rfp_automation.mcp.rules.rules_config import RulesConfigStore

logger = logging.getLogger(__name__)


class LegalRules:
    """E2 legal rules for contract clause risk and compliance checks."""

    def __init__(self):
        self._config_store = RulesConfigStore()

    def score_clause(self, clause_text: str) -> dict[str, Any]:
        """
        Score a single contract clause for risk.
        Returns: {score: 0-100, risk_level: str, triggers: list, blocked: bool}
        """
        config = self._config_store.get_legal_config()
        clause_lower = clause_text.lower()
        score = 0
        triggers: list[str] = []
        blocked = False

        # ── Auto-block triggers (critical) ───────────────
        for trigger in config.auto_block_triggers:
            if trigger.lower() in clause_lower:
                score += 50
                triggers.append(f"AUTO-BLOCK: {trigger}")
                blocked = True

        # ── High-risk keywords ───────────────────────────
        for keyword in config.high_risk_keywords:
            if keyword.lower() in clause_lower:
                score += 15
                triggers.append(f"HIGH-RISK: {keyword}")

        # Cap score at 100
        score = min(score, 100)

        # Determine risk level
        if score >= 50 or blocked:
            risk_level = "critical"
        elif score >= 30:
            risk_level = "high"
        elif score >= 15:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "score": score,
            "risk_level": risk_level,
            "triggers": triggers,
            "blocked": blocked,
        }

    def evaluate_clauses(
        self, clauses: list[str]
    ) -> dict[str, Any]:
        """
        Score all clauses and compute aggregate risk.
        Returns: {
            clause_scores: list[dict],
            aggregate_score: float,
            aggregate_risk: str,
            blocked: bool,
            block_reasons: list[str],
        }
        """
        clause_scores = [self.score_clause(c) for c in clauses]

        if not clause_scores:
            return {
                "clause_scores": [],
                "aggregate_score": 0,
                "aggregate_risk": "low",
                "blocked": False,
                "block_reasons": [],
            }

        # Aggregate: weighted average (heavier weight for higher scores)
        total = sum(cs["score"] for cs in clause_scores)
        avg = total / len(clause_scores)

        blocked = any(cs["blocked"] for cs in clause_scores)
        block_reasons = []
        for cs in clause_scores:
            if cs["blocked"]:
                block_reasons.extend(cs["triggers"])

        if avg >= 50 or blocked:
            agg_risk = "critical"
        elif avg >= 30:
            agg_risk = "high"
        elif avg >= 15:
            agg_risk = "medium"
        else:
            agg_risk = "low"

        return {
            "clause_scores": clause_scores,
            "aggregate_score": round(avg, 1),
            "aggregate_risk": agg_risk,
            "blocked": blocked,
            "block_reasons": block_reasons,
        }

    def evaluate_commercial_legal_gate(
        self,
        legal_decision: str,
        legal_block_reasons: list[str],
        pricing_total: float,
    ) -> dict[str, Any]:
        """
        Combined gate that merges E1 + E2 outputs.
        E2 BLOCK always overrides E1 → pipeline ends.
        """
        if legal_decision == "BLOCKED":
            return {
                "gate_decision": "BLOCK",
                "reason": "; ".join(legal_block_reasons),
            }
        return {
            "gate_decision": "CLEAR",
            "reason": "No blocking issues. Legal status: " + legal_decision,
        }

```

## File: `rfp_automation\mcp\rules\policy_rules.py`

```python
"""
Policy Rules — business rules applied at the A3 Go/No-Go gate.
Checks certifications, geography restrictions, contract value limits,
and conflict of interest.  Config loaded from MongoDB via RulesConfigStore.
"""

from __future__ import annotations

import logging
from typing import Any

from rfp_automation.mcp.rules.rules_config import RulesConfigStore

logger = logging.getLogger(__name__)


class PolicyRules:
    """Go/No-Go policy rules for the A3 governance checkpoint."""

    def __init__(self):
        self._config_store = RulesConfigStore()

    def check_policy_rules(
        self,
        required_certs: list[str],
        held_certs: dict[str, bool],
        contract_value: float | None = None,
        geography: str | None = None,
        client_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return list of policy violations (empty = pass).
        Each violation has: rule, detail, severity.
        """
        config = self._config_store.get_policy_config()
        violations: list[dict[str, Any]] = []

        # ── Certification gaps ───────────────────────────
        for cert in required_certs:
            if not held_certs.get(cert, False):
                severity = config.certification_gap_severity.get(cert, "medium")
                violations.append({
                    "rule": "certification_gap",
                    "detail": f"Required certification not held: {cert}",
                    "severity": severity,
                })

        # ── Geography restrictions ───────────────────────
        if geography:
            geo_upper = geography.upper()
            if config.blocked_regions:
                for blocked in config.blocked_regions:
                    if blocked.upper() in geo_upper:
                        violations.append({
                            "rule": "blocked_geography",
                            "detail": f"Geography '{geography}' is in blocked regions",
                            "severity": "critical",
                        })
            if config.allowed_regions:
                if not any(a.upper() in geo_upper for a in config.allowed_regions):
                    violations.append({
                        "rule": "geography_not_allowed",
                        "detail": f"Geography '{geography}' is not in allowed regions",
                        "severity": "high",
                    })

        # ── Contract value limits ────────────────────────
        if contract_value is not None:
            if contract_value < config.min_contract_value:
                violations.append({
                    "rule": "contract_too_small",
                    "detail": (
                        f"Contract value ${contract_value:,.2f} is below minimum "
                        f"${config.min_contract_value:,.2f}"
                    ),
                    "severity": "medium",
                })
            if contract_value > config.max_contract_value:
                violations.append({
                    "rule": "contract_too_large",
                    "detail": (
                        f"Contract value ${contract_value:,.2f} exceeds maximum "
                        f"${config.max_contract_value:,.2f}"
                    ),
                    "severity": "high",
                })

        # ── Conflict of interest ─────────────────────────
        if client_name and config.blocked_clients:
            for blocked in config.blocked_clients:
                if blocked.lower() in client_name.lower():
                    violations.append({
                        "rule": "conflict_of_interest",
                        "detail": f"Client '{client_name}' matches blocked client '{blocked}'",
                        "severity": "critical",
                    })

        return violations

```

## File: `rfp_automation\mcp\rules\rules_config.py`

```python
"""
Rules Config Store — loads/saves rule configurations from MongoDB.

Company-level setting: rules are configured once by admin and cached.
Falls back to sensible defaults if MongoDB is empty (first run).
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)


# ── Config models ────────────────────────────────────────

class PolicyConfig(BaseModel):
    """Policy rule configuration."""
    blocked_regions: list[str] = []
    allowed_regions: list[str] = []  # empty = all allowed
    min_contract_value: float = 10000.0
    max_contract_value: float = 10000000.0
    blocked_clients: list[str] = []
    required_certifications: list[str] = []
    certification_gap_severity: dict[str, str] = {
        "ISO 27001": "high",
        "SOC 2 Type II": "high",
        "FedRAMP Moderate": "critical",
        "HIPAA": "high",
        "PCI DSS": "high",
    }


class ValidationConfig(BaseModel):
    """Validation rule configuration."""
    max_uptime_sla: float = 99.999  # flag anything above this as unrealistic
    min_response_time_hours: float = 0.1  # flag anything below as unrealistic
    prohibited_phrases: list[str] = [
        "guaranteed 100% uptime",
        "zero defects",
        "unlimited support",
        "no additional cost ever",
        "perpetual license at no charge",
        "we will never fail",
        "absolute certainty",
        "risk-free implementation",
        "no downtime during migration",
        "instant resolution of all issues",
        "unlimited revisions",
        "we guarantee no bugs",
        "zero security vulnerabilities",
        "complete elimination of risk",
        "unconditional satisfaction",
    ]
    section_min_words: int = 50
    section_max_words: int = 5000


class CommercialConfig(BaseModel):
    """Commercial rule configuration."""
    minimum_margin_percent: float = 0.15
    maximum_discount_percent: float = 0.15
    max_contract_value: float = 5000000.0
    risky_payment_terms: list[str] = [
        "payment upon completion only",
        "net 120",
        "net 90",
        "payment after acceptance testing",
        "milestone-only with no advance",
    ]
    healthy_payment_terms: list[str] = [
        "net 30",
        "net 45",
        "net 60",
        "monthly invoicing",
        "time and materials",
        "50% advance, 50% on completion",
    ]


class LegalConfig(BaseModel):
    """Legal rule configuration."""
    auto_block_triggers: list[str] = [
        "unlimited liability",
        "irrevocable transfer of all intellectual property",
        "perpetual non-compete across all industries",
        "waiver of all warranties",
        "exclusive jurisdiction in foreign country",
    ]
    high_risk_keywords: list[str] = [
        "indemnify without limitation",
        "sole liability",
        "consequential damages with no cap",
        "perpetual confidentiality",
        "automatic renewal with no opt-out",
        "unilateral modification",
    ]
    max_liability_multiplier: float = 2.0  # max Nx contract value
    max_indemnity_percent: float = 1.0  # 100% of contract
    max_warranty_months: int = 12


# ── Store class ──────────────────────────────────────────

class RulesConfigStore:
    """
    Loads rule configs from MongoDB. Falls back to defaults on first run.
    Cached after first load for the lifetime of the process.
    """

    def __init__(self):
        self.settings = get_settings()
        self._db = None
        self._cache: dict[str, Any] = {}

    def _get_db(self):
        if self._db is not None:
            return self._db
        try:
            from pymongo import MongoClient
            client = MongoClient(self.settings.mongodb_uri)
            self._db = client[self.settings.mongodb_database]
        except Exception as e:
            logger.warning(f"MongoDB not available, using defaults: {e}")
            self._db = None
        return self._db

    def _load_config(self, rule_type: str, model_cls: type[BaseModel]) -> BaseModel:
        """Load from MongoDB or return defaults."""
        if rule_type in self._cache:
            return self._cache[rule_type]

        db = self._get_db()
        if db is not None:
            try:
                doc = db.rules_config.find_one({"rule_type": rule_type})
                if doc and "config" in doc:
                    config = model_cls(**doc["config"])
                    self._cache[rule_type] = config
                    return config
            except Exception as e:
                logger.warning(f"Failed loading {rule_type} from MongoDB: {e}")

        # Defaults
        config = model_cls()
        self._cache[rule_type] = config
        return config

    def get_policy_config(self) -> PolicyConfig:
        return self._load_config("policy", PolicyConfig)  # type: ignore[return-value]

    def get_validation_config(self) -> ValidationConfig:
        return self._load_config("validation", ValidationConfig)  # type: ignore[return-value]

    def get_commercial_config(self) -> CommercialConfig:
        return self._load_config("commercial", CommercialConfig)  # type: ignore[return-value]

    def get_legal_config(self) -> LegalConfig:
        return self._load_config("legal", LegalConfig)  # type: ignore[return-value]

    def update_config(self, rule_type: str, config_dict: dict[str, Any]) -> bool:
        """Admin: save/update a rule config in MongoDB."""
        db = self._get_db()
        if db is None:
            logger.error("Cannot update config — MongoDB not available")
            return False

        db.rules_config.update_one(
            {"rule_type": rule_type},
            {"$set": {"rule_type": rule_type, "config": config_dict}},
            upsert=True,
        )
        # Invalidate cache
        self._cache.pop(rule_type, None)
        logger.info(f"Updated {rule_type} config in MongoDB")
        return True

```

## File: `rfp_automation\mcp\rules\validation_rules.py`

```python
"""
Validation Rules — hard checks applied at the D1 Technical Validation gate.
Detects over-promised SLAs, prohibited language, unrealistic claims,
and inconsistencies.  Config loaded from MongoDB via RulesConfigStore.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from rfp_automation.mcp.rules.rules_config import RulesConfigStore

logger = logging.getLogger(__name__)


class ValidationRules:
    """D1 validation rules for proposal content checks."""

    def __init__(self):
        self._config_store = RulesConfigStore()

    def check_validation_rules(
        self,
        proposal_text: str,
        sections: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        """
        Apply hard validation checks.
        Returns list of violations: {rule, detail, severity}.
        """
        config = self._config_store.get_validation_config()
        violations: list[dict[str, str]] = []

        text_lower = proposal_text.lower()

        # ── Prohibited language ──────────────────────────
        for phrase in config.prohibited_phrases:
            if phrase.lower() in text_lower:
                violations.append({
                    "rule": "prohibited_language",
                    "detail": f"Prohibited phrase found: '{phrase}'",
                    "severity": "high",
                })

        # ── SLA realism checks ───────────────────────────
        # Detect uptime claims like "99.9999%" or "100%"
        uptime_matches = re.findall(r"(\d{2,3}(?:\.\d+)?)\s*%\s*uptime", text_lower)
        for match in uptime_matches:
            try:
                uptime_val = float(match)
                if uptime_val > config.max_uptime_sla:
                    violations.append({
                        "rule": "unrealistic_sla",
                        "detail": f"Uptime SLA {uptime_val}% exceeds realistic maximum {config.max_uptime_sla}%",
                        "severity": "high",
                    })
            except ValueError:
                pass

        # Detect response time claims like "0 minute" or "instant"
        instant_patterns = [
            r"response\s*time.*?(\d+)\s*(?:second|minute)",
            r"respond.*?within\s*(\d+)\s*(?:second|minute)",
        ]
        for pattern in instant_patterns:
            matches = re.findall(pattern, text_lower)
            for m in matches:
                try:
                    val = float(m)
                    # If the value is in seconds and < 1 minute, it's suspicious
                    if "second" in pattern and val < 60:
                        pass  # seconds can be okay depending on context
                except ValueError:
                    pass

        # ── Consistency checks ───────────────────────────
        # Check for conflicting statements
        contradiction_pairs = [
            ("no downtime", "scheduled maintenance"),
            ("unlimited", "subject to fair use"),
            ("guaranteed", "best effort"),
            ("24/7 support", "business hours only"),
        ]
        for phrase_a, phrase_b in contradiction_pairs:
            if phrase_a.lower() in text_lower and phrase_b.lower() in text_lower:
                violations.append({
                    "rule": "consistency_conflict",
                    "detail": f"Conflicting statements: '{phrase_a}' vs '{phrase_b}'",
                    "severity": "medium",
                })

        # ── Section length validation ────────────────────
        if sections:
            for section in sections:
                text = section.get("text", "")
                title = section.get("title", "Unknown Section")
                word_count = len(text.split())

                if word_count < config.section_min_words:
                    violations.append({
                        "rule": "section_too_short",
                        "detail": f"Section '{title}' has {word_count} words (min: {config.section_min_words})",
                        "severity": "low",
                    })
                if word_count > config.section_max_words:
                    violations.append({
                        "rule": "section_too_long",
                        "detail": f"Section '{title}' has {word_count} words (max: {config.section_max_words})",
                        "severity": "low",
                    })

        return violations

```

## File: `rfp_automation\mcp\rules\__init__.py`

```python

```

## File: `rfp_automation\mcp\schema\capability_schema.py`

```python
"""
Capability Schema — data structures for company capabilities stored in the knowledge base.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class Capability(BaseModel):
    """A company capability record in the knowledge store."""
    capability_id: str
    name: str
    description: str = ""
    evidence: str = ""
    category: str = ""  # "cloud", "security", "devops", etc.
    confidence_score: float = 0.0
    tags: list[str] = []  # multi-label search filtering
    last_updated: Optional[datetime] = None  # freshness tracking

```

## File: `rfp_automation\mcp\schema\pricing_schema.py`

```python
"""
Pricing Schema — data structures for commercial pricing logic in the MCP context.
"""

from __future__ import annotations

from pydantic import BaseModel


class PricingParameters(BaseModel):
    """Pricing formula parameters from the knowledge store."""
    base_cost: float = 0.0
    per_requirement_cost: float = 0.0
    complexity_tiers: dict[str, float] = {}  # "low" -> 1.0, "medium" -> 1.25, "high" -> 1.5
    risk_margin_percent: float = 0.10
    payment_terms: str = ""
    currency: str = "USD"
    discount_tiers: dict[str, float] = {}  # "preferred_client" -> 0.05, etc.
    minimum_contract_value: float = 25000.0
    maximum_contract_value: float = 5000000.0
    minimum_margin_percent: float = 0.15
    maximum_discount_percent: float = 0.15

```

## File: `rfp_automation\mcp\schema\requirement_schema.py`

```python
"""
Requirement Schema — data structures for extracted requirements in the MCP context.
"""

from __future__ import annotations

from pydantic import BaseModel


class ExtractedRequirement(BaseModel):
    """A requirement as stored/queried in the MCP vector store."""
    requirement_id: str
    text: str
    section_id: str = ""
    type: str = "MANDATORY"  # MANDATORY | OPTIONAL
    category: str = "TECHNICAL"
    impact: str = "MEDIUM"
    embedding_id: str = ""
    source_chunk_ids: list[str] = []  # trace back to vector store chunks
    compliance_mapping: str = ""  # regulatory cross-reference (e.g. "NIST 800-53 AC-2")

```

## File: `rfp_automation\mcp\schema\__init__.py`

```python

```

## File: `rfp_automation\mcp\vector_store\knowledge_store.py`

```python
"""
Knowledge Store — company-level knowledge base.

Vector data (capabilities, past proposals) lives in Pinecone under the
"knowledge" namespace.  Structured config (certifications, pricing rules,
legal templates) lives in MongoDB.

This is a GLOBAL store — not per-RFP.  An admin seeds it once and every
pipeline run reads from it.
"""

from __future__ import annotations

import logging
from typing import Any

from rfp_automation.config import get_settings
from rfp_automation.mcp.embeddings.embedding_model import EmbeddingModel

logger = logging.getLogger(__name__)

KNOWLEDGE_NAMESPACE = "company_knowledge"


class KnowledgeStore:
    """
    Company knowledge base: capabilities, certifications, pricing rules,
    legal templates, past proposals.
    """

    def __init__(self):
        self.settings = get_settings()
        self._embedder = EmbeddingModel()
        self._index = None
        self._mongo_db = None

    # ── Pinecone connection ──────────────────────────────

    def _get_index(self):
        """Lazy-init: connect to Pinecone index (shared with RFP store)."""
        if self._index is not None:
            return self._index

        from pinecone import Pinecone, ServerlessSpec

        pc = Pinecone(api_key=self.settings.pinecone_api_key)
        index_name = self.settings.pinecone_index_name

        existing = [idx.name for idx in pc.list_indexes()]
        if index_name not in existing:
            pc.create_index(
                name=index_name,
                dimension=self._embedder.dimension,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud=self.settings.pinecone_cloud,
                    region=self.settings.pinecone_region,
                ),
            )

        self._index = pc.Index(index_name)
        return self._index

    # ── MongoDB connection ───────────────────────────────

    def _get_db(self):
        """Lazy-init: connect to MongoDB for structured company data."""
        if self._mongo_db is not None:
            return self._mongo_db

        from pymongo import MongoClient

        client = MongoClient(self.settings.mongodb_uri)
        self._mongo_db = client[self.settings.mongodb_database]
        return self._mongo_db

    # ── Admin: ingest company documents ──────────────────

    def ingest_company_docs(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]] | None = None,
        doc_type: str = "capability",
    ) -> int:
        """
        Admin function: embed company documents and store in Pinecone
        knowledge namespace.  Returns number of vectors stored.
        """
        index = self._get_index()
        embeddings = self._embedder.embed(texts)
        metadatas = metadatas or [{} for _ in texts]

        vectors = []
        for i, (text, emb, meta) in enumerate(zip(texts, embeddings, metadatas)):
            vec_id = f"knowledge_{doc_type}_{meta.get('id', i)}"
            vec_metadata = {
                "text": text[:1000],
                "doc_type": doc_type,
                **meta,
            }
            vectors.append((vec_id, emb, vec_metadata))

        # Batch upsert
        batch_size = 100
        for start in range(0, len(vectors), batch_size):
            batch = vectors[start : start + batch_size]
            index.upsert(vectors=batch, namespace=KNOWLEDGE_NAMESPACE)

        logger.info(f"Ingested {len(texts)} {doc_type} docs into knowledge store")
        return len(texts)

    # ── Query: all types (no filter) ─────────────────────

    def query_all_types(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Semantic search over ALL knowledge documents (no doc_type filter)."""
        index = self._get_index()
        query_emb = self._embedder.embed_single(query)

        results = index.query(
            vector=query_emb,
            top_k=top_k,
            namespace=KNOWLEDGE_NAMESPACE,
            include_metadata=True,
        )

        return [
            {
                "id": m["id"],
                "score": m["score"],
                "text": m.get("metadata", {}).get("text", ""),
                "doc_type": m.get("metadata", {}).get("doc_type", ""),
                "metadata": m.get("metadata", {}),
            }
            for m in results.get("matches", [])
        ]

    # ── Query: by specific type ──────────────────────────

    def query_by_type(self, query: str, doc_type: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Semantic search filtered by a specific doc_type."""
        index = self._get_index()
        query_emb = self._embedder.embed_single(query)

        results = index.query(
            vector=query_emb,
            top_k=top_k,
            namespace=KNOWLEDGE_NAMESPACE,
            include_metadata=True,
            filter={"doc_type": doc_type},
        )

        return [
            {
                "id": m["id"],
                "score": m["score"],
                "text": m.get("metadata", {}).get("text", ""),
                "doc_type": doc_type,
                "metadata": m.get("metadata", {}),
            }
            for m in results.get("matches", [])
        ]

    # ── Query: capabilities (Pinecone) ───────────────────

    def query_capabilities(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Semantic search over company capabilities."""
        return self.query_by_type(query, "capability", top_k)

    # ── Query: past proposals (Pinecone) ─────────────────

    def query_past_proposals(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        """Semantic search over past winning proposals."""
        return self.query_by_type(query, "past_proposal", top_k)

    # ── Query: certifications (MongoDB) ──────────────────

    def query_certifications(self) -> dict[str, bool]:
        """Return map of certification name → whether we hold it."""
        db = self._get_db()
        doc = db.company_config.find_one({"config_type": "certifications"})
        if doc and "certifications" in doc:
            return doc["certifications"]
        # Default if MongoDB is empty
        return {}

    # ── Query: pricing rules (MongoDB) ───────────────────

    def query_pricing_rules(self) -> dict[str, Any]:
        """Return pricing formula parameters."""
        db = self._get_db()
        doc = db.company_config.find_one({"config_type": "pricing_rules"})
        if doc and "rules" in doc:
            return doc["rules"]
        # Default if MongoDB is empty
        return {
            "base_cost": 50000.0,
            "per_requirement_cost": 2000.0,
            "complexity_tiers": {"low": 1.0, "medium": 1.25, "high": 1.5},
            "risk_margin_percent": 0.10,
            "currency": "USD",
        }

    # ── Query: legal templates (MongoDB) ─────────────────

    def query_legal_templates(self) -> list[dict[str, str]]:
        """Return company legal templates for clause comparison."""
        db = self._get_db()
        doc = db.company_config.find_one({"config_type": "legal_templates"})
        if doc and "templates" in doc:
            return doc["templates"]
        # Default if MongoDB is empty
        return []

```

## File: `rfp_automation\mcp\vector_store\rfp_store.py`

```python
"""
RFP Vector Store — stores chunked + embedded incoming RFP documents in Pinecone.

Each RFP gets its own Pinecone namespace (rfp_id as namespace).
Agents query this store to retrieve relevant RFP context.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from rfp_automation.config import get_settings
from rfp_automation.mcp.embeddings.embedding_model import EmbeddingModel
from rfp_automation.services.parsing_service import ParsingService

logger = logging.getLogger(__name__)


class RFPVectorStore:
    """
    Pinecone-backed vector store for incoming RFP documents.
    Uses namespaces to isolate each RFP's vectors.
    """

    def __init__(self):
        self.settings = get_settings()
        self._embedder = EmbeddingModel()
        self._index = None

    def _get_index(self):
        """Lazy-init: connect to (or create) the Pinecone index."""
        if self._index is not None:
            return self._index

        from pinecone import Pinecone, ServerlessSpec

        pc = Pinecone(api_key=self.settings.pinecone_api_key)
        index_name = self.settings.pinecone_index_name

        # Create the index if it doesn't exist
        existing = [idx.name for idx in pc.list_indexes()]
        if index_name not in existing:
            logger.info(f"Creating Pinecone index: {index_name}")
            pc.create_index(
                name=index_name,
                dimension=self._embedder.dimension,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud=self.settings.pinecone_cloud,
                    region=self.settings.pinecone_region,
                ),
            )

        self._index = pc.Index(index_name)
        logger.info(f"Connected to Pinecone index: {index_name}")
        return self._index

    def embed_document(
        self,
        rfp_id: str,
        raw_text: str,
        metadata: dict[str, Any] | None = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> int:
        """
        Chunk raw text, embed, and upsert into Pinecone.
        Returns the number of chunks stored.
        """
        index = self._get_index()
        chunks = ParsingService.chunk_text(raw_text, chunk_size, chunk_overlap)

        if not chunks:
            logger.warning(f"[{rfp_id}] No chunks produced from text")
            return 0

        # Generate embeddings for all chunks
        embeddings = self._embedder.embed(chunks)

        # Build upsert vectors
        vectors = []
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            vec_id = f"{rfp_id}_chunk_{i:04d}"
            vec_metadata = {
                "rfp_id": rfp_id,
                "chunk_index": i,
                "text": chunk[:1000],  # Pinecone metadata limit
                **(metadata or {}),
            }
            vectors.append((vec_id, emb, vec_metadata))

        # Upsert in batches (Pinecone limit is 100 per request)
        batch_size = 100
        for batch_start in range(0, len(vectors), batch_size):
            batch = vectors[batch_start : batch_start + batch_size]
            index.upsert(vectors=batch, namespace=rfp_id)

        logger.info(f"[{rfp_id}] Embedded {len(chunks)} chunks into Pinecone")
        return len(chunks)

    def embed_chunks(
        self,
        rfp_id: str,
        chunks: list[dict[str, Any]],
        extra_metadata: dict[str, Any] | None = None,
    ) -> int:
        """
        Embed pre-structured chunks and upsert into Pinecone.

        Each chunk dict must have: chunk_id, content_type, section_hint,
        text, page_start, page_end  (from ParsingService.prepare_chunks).

        Returns the number of vectors stored.
        """
        index = self._get_index()

        # Filter out table_mock chunks (placeholder text, not useful for semantic search)
        embeddable = [c for c in chunks if c.get("content_type") != "table_mock"]
        if not embeddable:
            logger.warning(f"[{rfp_id}] No embeddable chunks after filtering")
            return 0

        # Extract text for batch embedding
        texts = [c["text"] for c in embeddable]
        embeddings = self._embedder.embed(texts)

        # Build upsert vectors with structured metadata
        vectors = []
        for i, (chunk, emb) in enumerate(zip(embeddable, embeddings)):
            vec_id = f"{rfp_id}_chunk_{i:04d}"
            vec_metadata = {
                "rfp_id": rfp_id,
                "chunk_index": i,
                "chunk_id": chunk.get("chunk_id", ""),
                "content_type": chunk.get("content_type", "text"),
                "section_hint": chunk.get("section_hint", ""),
                "page_start": chunk.get("page_start", 0),
                "page_end": chunk.get("page_end", 0),
                "text": chunk["text"][:1000],  # Pinecone metadata limit
                **(extra_metadata or {}),
            }
            vectors.append((vec_id, emb, vec_metadata))

        # Upsert in batches (Pinecone limit is 100 per request)
        batch_size = 100
        for batch_start in range(0, len(vectors), batch_size):
            batch = vectors[batch_start : batch_start + batch_size]
            index.upsert(vectors=batch, namespace=rfp_id)

        logger.info(
            f"[{rfp_id}] Embedded {len(vectors)} structured chunks into Pinecone "
            f"(skipped {len(chunks) - len(embeddable)} table_mock)"
        )
        return len(vectors)

    def query(
        self,
        query_text: str,
        rfp_id: str = "",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Embed the query and search Pinecone for matching chunks.
        Returns list of {text, score, chunk_index, metadata}.
        """
        index = self._get_index()
        query_embedding = self._embedder.embed_single(query_text)

        results = index.query(
            vector=query_embedding,
            top_k=top_k,
            namespace=rfp_id if rfp_id else None,
            include_metadata=True,
        )

        chunks = []
        for match in results.get("matches", []):
            chunks.append({
                "id": match["id"],
                "score": match["score"],
                "text": match.get("metadata", {}).get("text", ""),
                "chunk_index": match.get("metadata", {}).get("chunk_index", -1),
                "metadata": match.get("metadata", {}),
            })
        return chunks

    def query_all(
        self,
        rfp_id: str,
        top_k: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Retrieve all chunks for an RFP namespace (broad retrieval).
        Uses a generic query to pull as many chunks as possible.
        Results are sorted by chunk_index for document order.
        """
        index = self._get_index()
        # Use a generic query to get broad coverage of the namespace
        query_embedding = self._embedder.embed_single("document contents overview")

        results = index.query(
            vector=query_embedding,
            top_k=top_k,
            namespace=rfp_id,
            include_metadata=True,
        )

        chunks = []
        for match in results.get("matches", []):
            chunks.append({
                "id": match["id"],
                "score": match["score"],
                "text": match.get("metadata", {}).get("text", ""),
                "chunk_index": match.get("metadata", {}).get("chunk_index", -1),
                "metadata": match.get("metadata", {}),
            })

        # Sort by chunk_index to preserve document order
        chunks.sort(key=lambda c: c.get("chunk_index", -1))
        return chunks

    def delete_document(self, rfp_id: str) -> bool:
        """Delete all vectors for an RFP by deleting its namespace."""
        index = self._get_index()
        try:
            index.delete(delete_all=True, namespace=rfp_id)
            logger.info(f"[{rfp_id}] Deleted all vectors from Pinecone")
            return True
        except Exception as e:
            logger.error(f"[{rfp_id}] Failed to delete: {e}")
            return False

```

## File: `rfp_automation\mcp\vector_store\__init__.py`

```python

```

## File: `rfp_automation\models\enums.py`

```python
"""
Enumerations used across the pipeline.
Centralised here so agents, orchestration, and services share one truth.
"""

from enum import Enum


class PipelineStatus(str, Enum):
    """Overall pipeline status."""
    RECEIVED = "RECEIVED"
    INTAKE_COMPLETE = "INTAKE_COMPLETE"
    STRUCTURING = "STRUCTURING"
    GO_NO_GO = "GO_NO_GO"
    EXTRACTING_REQUIREMENTS = "EXTRACTING_REQUIREMENTS"
    VALIDATING_REQUIREMENTS = "VALIDATING_REQUIREMENTS"
    ARCHITECTURE_PLANNING = "ARCHITECTURE_PLANNING"
    WRITING_RESPONSES = "WRITING_RESPONSES"
    ASSEMBLING_NARRATIVE = "ASSEMBLING_NARRATIVE"
    TECHNICAL_VALIDATION = "TECHNICAL_VALIDATION"
    COMMERCIAL_LEGAL_REVIEW = "COMMERCIAL_LEGAL_REVIEW"
    FINAL_READINESS = "FINAL_READINESS"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    NO_GO = "NO_GO"
    LEGAL_BLOCK = "LEGAL_BLOCK"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


class GoNoGoDecision(str, Enum):
    GO = "GO"
    NO_GO = "NO_GO"


class ValidationDecision(str, Enum):
    PASS = "PASS"
    REJECT = "REJECT"


class LegalDecision(str, Enum):
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    BLOCKED = "BLOCKED"


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class CommercialLegalGateDecision(str, Enum):
    CLEAR = "CLEAR"
    BLOCK = "BLOCK"


class RequirementType(str, Enum):
    MANDATORY = "MANDATORY"
    OPTIONAL = "OPTIONAL"


class RequirementCategory(str, Enum):
    TECHNICAL = "TECHNICAL"
    FUNCTIONAL = "FUNCTIONAL"
    SECURITY = "SECURITY"
    COMPLIANCE = "COMPLIANCE"
    COMMERCIAL = "COMMERCIAL"
    OPERATIONAL = "OPERATIONAL"


class ImpactLevel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AgentName(str, Enum):
    """Identifies each agent in the pipeline."""
    A1_INTAKE = "A1_INTAKE"
    A2_STRUCTURING = "A2_STRUCTURING"
    A3_GO_NO_GO = "A3_GO_NO_GO"
    B1_REQUIREMENTS_EXTRACTION = "B1_REQUIREMENTS_EXTRACTION"
    B2_REQUIREMENTS_VALIDATION = "B2_REQUIREMENTS_VALIDATION"
    C1_ARCHITECTURE_PLANNING = "C1_ARCHITECTURE_PLANNING"
    C2_REQUIREMENT_WRITING = "C2_REQUIREMENT_WRITING"
    C3_NARRATIVE_ASSEMBLY = "C3_NARRATIVE_ASSEMBLY"
    D1_TECHNICAL_VALIDATION = "D1_TECHNICAL_VALIDATION"
    E1_COMMERCIAL = "E1_COMMERCIAL"
    E2_LEGAL = "E2_LEGAL"
    F1_FINAL_READINESS = "F1_FINAL_READINESS"
    F2_SUBMISSION = "F2_SUBMISSION"

```

## File: `rfp_automation\models\schemas.py`

```python
"""
Reusable data schemas for sub-structures embedded inside the graph state.
Each schema represents a clearly-bounded data object produced by one agent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from .enums import (
    RequirementType,
    RequirementCategory,
    ImpactLevel,
    RiskLevel,
    GoNoGoDecision,
    ValidationDecision,
    LegalDecision,
    ApprovalDecision,
    CommercialLegalGateDecision,
)


# ── A1 Intake ────────────────────────────────────────────


class RFPMetadata(BaseModel):
    """Basic metadata extracted by the Intake agent."""
    rfp_id: str = ""
    client_name: str = ""
    rfp_title: str = ""
    deadline: Optional[datetime] = None
    rfp_number: str = ""
    source_file_path: str = ""
    page_count: int = 0
    word_count: int = 0
    file_hash: str = ""
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    issue_date: Optional[str] = None
    deadline_text: Optional[str] = None
    received_at: datetime = Field(default_factory=datetime.utcnow)


# ── A2 Structuring ───────────────────────────────────────


class RFPSection(BaseModel):
    """A classified section of the RFP document."""
    section_id: str
    title: str
    category: str  # scope, technical, compliance, legal, submission, evaluation
    content_summary: str
    confidence: float = 0.0  # 0-1
    page_range: str = ""


class StructuringResult(BaseModel):
    sections: list[RFPSection] = []
    overall_confidence: float = 0.0
    retry_count: int = 0


# ── A3 Go / No-Go ────────────────────────────────────────


class RequirementMapping(BaseModel):
    """Maps a single RFP requirement to a company policy."""
    requirement_id: str = ""          # "RFP-REQ-001"
    requirement_text: str = ""        # verbatim from RFP
    source_section: str = ""          # RFP section
    mapping_status: str = "NO_MATCH"  # "ALIGNS" | "VIOLATES" | "RISK" | "NO_MATCH"
    matched_policy: str = ""          # policy text, "" if none
    matched_policy_id: str = ""       # policy_id, "" if none
    confidence: float = 0.0
    reasoning: str = ""


class GoNoGoResult(BaseModel):
    decision: GoNoGoDecision = GoNoGoDecision.GO
    strategic_fit_score: float = 0.0   # 1-10
    technical_feasibility_score: float = 0.0
    regulatory_risk_score: float = 0.0
    policy_violations: list[str] = []
    red_flags: list[str] = []
    justification: str = ""
    requirement_mappings: list[RequirementMapping] = []
    total_requirements: int = 0
    aligned_count: int = 0
    violated_count: int = 0
    risk_count: int = 0
    no_match_count: int = 0


# ── B1 Requirements Extraction ───────────────────────────


class Requirement(BaseModel):
    """A single requirement extracted from the RFP."""
    requirement_id: str
    text: str
    type: RequirementType = RequirementType.MANDATORY
    category: RequirementCategory = RequirementCategory.TECHNICAL
    impact: ImpactLevel = ImpactLevel.MEDIUM
    source_section: str = ""
    keywords: list[str] = []


# ── B2 Requirements Validation ───────────────────────────


class ValidationIssue(BaseModel):
    issue_type: str  # "duplicate" | "contradiction" | "ambiguity"
    requirement_ids: list[str]
    description: str
    severity: str = "warning"  # "warning" | "info"


class RequirementsValidationResult(BaseModel):
    validated_requirements: list[Requirement] = []
    issues: list[ValidationIssue] = []
    total_requirements: int = 0
    mandatory_count: int = 0
    optional_count: int = 0


# ── C1 Architecture Planning ─────────────────────────────


class ResponseSection(BaseModel):
    """A planned section of the proposal response."""
    section_id: str
    title: str
    requirement_ids: list[str] = []
    mapped_capabilities: list[str] = []
    priority: int = 0


class ArchitecturePlan(BaseModel):
    sections: list[ResponseSection] = []
    coverage_gaps: list[str] = []  # requirement IDs not yet mapped
    total_sections: int = 0


# ── C2 Requirement Writing ───────────────────────────────


class SectionResponse(BaseModel):
    """Generated prose for one response section."""
    section_id: str
    title: str
    content: str = ""
    requirements_addressed: list[str] = []
    word_count: int = 0


class CoverageEntry(BaseModel):
    requirement_id: str
    addressed_in_section: str
    coverage_quality: str = "full"  # "full" | "partial" | "missing"


class WritingResult(BaseModel):
    section_responses: list[SectionResponse] = []
    coverage_matrix: list[CoverageEntry] = []


# ── C3 Narrative Assembly ────────────────────────────────


class AssembledProposal(BaseModel):
    executive_summary: str = ""
    full_narrative: str = ""
    word_count: int = 0
    sections_included: int = 0
    has_placeholders: bool = False


# ── D1 Technical Validation ──────────────────────────────


class ValidationCheckResult(BaseModel):
    check_name: str  # "completeness" | "alignment" | "realism" | "consistency"
    passed: bool = True
    issues: list[str] = []


class TechnicalValidationResult(BaseModel):
    decision: ValidationDecision = ValidationDecision.PASS
    checks: list[ValidationCheckResult] = []
    critical_failures: int = 0
    warnings: int = 0
    feedback_for_revision: str = ""
    retry_count: int = 0


# ── E1 Commercial ────────────────────────────────────────


class PricingBreakdown(BaseModel):
    base_cost: float = 0.0
    per_requirement_cost: float = 0.0
    complexity_multiplier: float = 1.0
    risk_margin: float = 0.0
    total_price: float = 0.0
    payment_terms: str = ""
    assumptions: list[str] = []
    exclusions: list[str] = []


class CommercialResult(BaseModel):
    pricing: PricingBreakdown = Field(default_factory=PricingBreakdown)
    commercial_narrative: str = ""


# ── E2 Legal ──────────────────────────────────────────────


class ContractClauseRisk(BaseModel):
    clause_id: str
    clause_text: str
    risk_level: RiskLevel = RiskLevel.LOW
    concern: str = ""
    recommendation: str = ""


class LegalResult(BaseModel):
    decision: LegalDecision = LegalDecision.APPROVED
    clause_risks: list[ContractClauseRisk] = []
    compliance_status: dict[str, bool] = {}  # cert_name -> held?
    block_reasons: list[str] = []
    risk_register_summary: str = ""


# ── E1 + E2 Combined Gate ────────────────────────────────


class CommercialLegalGateResult(BaseModel):
    gate_decision: CommercialLegalGateDecision = CommercialLegalGateDecision.CLEAR
    commercial: CommercialResult = Field(default_factory=CommercialResult)
    legal: LegalResult = Field(default_factory=LegalResult)


# ── F1 Final Readiness ───────────────────────────────────


class ApprovalPackage(BaseModel):
    decision_brief: str = ""
    proposal_summary: str = ""
    pricing_summary: str = ""
    risk_summary: str = ""
    coverage_summary: str = ""
    approval_decision: Optional[ApprovalDecision] = None
    approver_notes: str = ""


# ── F2 Submission ────────────────────────────────────────


class SubmissionRecord(BaseModel):
    submitted_at: Optional[datetime] = None
    output_file_path: str = ""
    archive_path: str = ""
    file_hash: str = ""


# ── Audit Trail ──────────────────────────────────────────


class AuditEntry(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    agent: str
    action: str
    details: str = ""
    state_version: int = 0

```

## File: `rfp_automation\models\state.py`

```python
"""
LangGraph shared state — the single object that flows through every node.

Design rules:
  1. Each field is "owned" by one agent (see comments).
  2. Agents may READ any field but should only WRITE to their owned fields.
  3. The state is versioned for audit purposes.
"""

from __future__ import annotations

from typing import Annotated, Optional
from operator import add
from pydantic import BaseModel, Field

from .enums import PipelineStatus
from .schemas import (
    RFPMetadata,
    StructuringResult,
    GoNoGoResult,
    Requirement,
    RequirementsValidationResult,
    ArchitecturePlan,
    WritingResult,
    AssembledProposal,
    TechnicalValidationResult,
    CommercialResult,
    LegalResult,
    CommercialLegalGateResult,
    ApprovalPackage,
    SubmissionRecord,
    AuditEntry,
)


class RFPGraphState(BaseModel):
    """
    The shared graph state passed through every LangGraph node.

    LangGraph expects a TypedDict or Pydantic model.
    Using Pydantic gives us validation + serialization for free.
    """

    # ── Pipeline control ─────────────────────────────────
    status: PipelineStatus = PipelineStatus.RECEIVED
    current_agent: str = ""
    error_message: str = ""
    state_version: int = 0

    # ── Tracking (set by API route, used for WebSocket) ──
    tracking_rfp_id: str = ""

    # ── A1 Intake (owner: A1) ────────────────────────────
    rfp_metadata: RFPMetadata = Field(default_factory=RFPMetadata)
    uploaded_file_path: str = ""
    raw_text: str = ""  # kept temporarily; agents use MCP after embedding

    # ── A2 Structuring (owner: A2) ───────────────────────
    structuring_result: StructuringResult = Field(default_factory=StructuringResult)

    # ── A3 Go / No-Go (owner: A3) ────────────────────────
    go_no_go_result: GoNoGoResult = Field(default_factory=GoNoGoResult)

    # ── B1 Requirements Extraction (owner: B1) ───────────
    requirements: list[Requirement] = Field(default_factory=list)

    # ── B2 Requirements Validation (owner: B2) ───────────
    requirements_validation: RequirementsValidationResult = Field(
        default_factory=RequirementsValidationResult
    )

    # ── C1 Architecture Planning (owner: C1) ─────────────
    architecture_plan: ArchitecturePlan = Field(default_factory=ArchitecturePlan)

    # ── C2 Requirement Writing (owner: C2) ───────────────
    writing_result: WritingResult = Field(default_factory=WritingResult)

    # ── C3 Narrative Assembly (owner: C3) ─────────────────
    assembled_proposal: AssembledProposal = Field(default_factory=AssembledProposal)

    # ── D1 Technical Validation (owner: D1) ──────────────
    technical_validation: TechnicalValidationResult = Field(
        default_factory=TechnicalValidationResult
    )

    # ── E1 Commercial (owner: E1) ────────────────────────
    commercial_result: CommercialResult = Field(default_factory=CommercialResult)

    # ── E2 Legal (owner: E2) ─────────────────────────────
    legal_result: LegalResult = Field(default_factory=LegalResult)

    # ── E1+E2 Gate (owner: orchestration) ────────────────
    commercial_legal_gate: CommercialLegalGateResult = Field(
        default_factory=CommercialLegalGateResult
    )

    # ── F1 Final Readiness (owner: F1) ───────────────────
    approval_package: ApprovalPackage = Field(default_factory=ApprovalPackage)

    # ── F2 Submission (owner: F2) ────────────────────────
    submission_record: SubmissionRecord = Field(default_factory=SubmissionRecord)

    # ── Audit trail (append-only) ────────────────────────
    audit_trail: list[AuditEntry] = Field(default_factory=list)

    # ── Helper ───────────────────────────────────────────

    def add_audit(self, agent: str, action: str, details: str = "") -> None:
        self.state_version += 1
        self.audit_trail.append(
            AuditEntry(
                agent=agent,
                action=action,
                details=details,
                state_version=self.state_version,
            )
        )

```

## File: `rfp_automation\models\__init__.py`

```python
from .enums import *
from .state import RFPGraphState
from .schemas import *

```

## File: `rfp_automation\orchestration\graph.py`

```python
"""
LangGraph State Machine — 12-stage RFP response pipeline.

This module defines the full graph: nodes, edges, conditional routing,
and the parallel fan-out/fan-in for E1+E2.

All nodes delegate to agent.process(state), which returns an updated
state dict that LangGraph merges automatically.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import StateGraph, END

from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.enums import PipelineStatus, CommercialLegalGateDecision
from rfp_automation.agents import (
    IntakeAgent,
    StructuringAgent,
    GoNoGoAgent,
    RequirementsExtractionAgent,
    RequirementsValidationAgent,
    ArchitecturePlanningAgent,
    RequirementWritingAgent,
    NarrativeAssemblyAgent,
    TechnicalValidationAgent,
    CommercialAgent,
    LegalAgent,
    FinalReadinessAgent,
    SubmissionAgent,
)
from rfp_automation.orchestration.transitions import (
    route_after_structuring,
    route_after_go_no_go,
    route_after_validation,
    route_after_commercial_legal,
    route_after_approval,
)

logger = logging.getLogger(__name__)

# ── Instantiate agents (singletons for the graph) ────────

_a1 = IntakeAgent()
_a2 = StructuringAgent()
_a3 = GoNoGoAgent()
_b1 = RequirementsExtractionAgent()
_b2 = RequirementsValidationAgent()
_c1 = ArchitecturePlanningAgent()
_c2 = RequirementWritingAgent()
_c3 = NarrativeAssemblyAgent()
_d1 = TechnicalValidationAgent()
_e1 = CommercialAgent()
_e2 = LegalAgent()
_f1 = FinalReadinessAgent()
_f2 = SubmissionAgent()


# ── Terminal nodes (set final status and stop) ───────────

def end_no_go(state: dict[str, Any]) -> dict[str, Any]:
    """Pipeline terminated — A3 said NO_GO."""
    state["status"] = PipelineStatus.NO_GO.value
    logger.info("Pipeline terminated: NO_GO")
    return state


def end_legal_block(state: dict[str, Any]) -> dict[str, Any]:
    """Pipeline terminated — E2 Legal issued a BLOCK."""
    state["status"] = PipelineStatus.LEGAL_BLOCK.value
    logger.info("Pipeline terminated: LEGAL_BLOCK")
    return state


def end_rejected(state: dict[str, Any]) -> dict[str, Any]:
    """Pipeline terminated — human approval REJECTED."""
    state["status"] = PipelineStatus.REJECTED.value
    logger.info("Pipeline terminated: REJECTED")
    return state


def escalate_structuring(state: dict[str, Any]) -> dict[str, Any]:
    """A2 failed to reach acceptable confidence — needs human review."""
    state["status"] = PipelineStatus.ESCALATED.value
    state["error_message"] = "Structuring confidence too low after max retries"
    logger.warning("Escalated: Structuring confidence too low")
    return state


def escalate_validation(state: dict[str, Any]) -> dict[str, Any]:
    """D1 rejected too many times — needs human review."""
    state["status"] = PipelineStatus.ESCALATED.value
    state["error_message"] = "Technical validation failed after max retries"
    logger.warning("Escalated: Validation retries exhausted")
    return state


# ── Commercial + Legal parallel fan-out / fan-in ─────────

def commercial_legal_parallel(state: dict[str, Any]) -> dict[str, Any]:
    """
    Run E1 (Commercial) and E2 (Legal) and combine results.
    
    NOTE: True LangGraph fan-out requires specific graph patterns.
    For the mock scaffold we run them sequentially and combine.
    When moving to production, refactor using LangGraph's 
    Send() / fan-out API.
    """
    logger.info("Running E1 Commercial + E2 Legal (sequential mock of parallel)")

    state = _e1.process(state)
    state = _e2.process(state)

    # ── Fan-in gate: combine E1 + E2 ────────────────────
    legal_decision = state.get("legal_result", {}).get("decision", "APPROVED")
    legal_blocks = state.get("legal_result", {}).get("block_reasons", [])

    if legal_decision == "BLOCKED":
        gate_decision = CommercialLegalGateDecision.BLOCK.value
    else:
        gate_decision = CommercialLegalGateDecision.CLEAR.value

    state["commercial_legal_gate"] = {
        "gate_decision": gate_decision,
        "commercial": state.get("commercial_result", {}),
        "legal": state.get("legal_result", {}),
    }

    return state


# ── Build the graph ──────────────────────────────────────

def build_graph() -> StateGraph:
    """
    Construct and compile the 12-stage LangGraph state machine.
    Returns a compiled graph ready to invoke.
    """

    graph = StateGraph(dict)

    # ── Add nodes ────────────────────────────────────────
    graph.add_node("a1_intake", _a1.process)
    graph.add_node("a2_structuring", _a2.process)
    graph.add_node("a3_go_no_go", _a3.process)
    graph.add_node("b1_requirements_extraction", _b1.process)
    graph.add_node("b2_requirements_validation", _b2.process)
    graph.add_node("c1_architecture_planning", _c1.process)
    graph.add_node("c2_requirement_writing", _c2.process)
    graph.add_node("c3_narrative_assembly", _c3.process)
    graph.add_node("d1_technical_validation", _d1.process)
    graph.add_node("commercial_legal_parallel", commercial_legal_parallel)
    graph.add_node("f1_final_readiness", _f1.process)
    graph.add_node("f2_submission", _f2.process)

    # Terminal nodes
    graph.add_node("end_no_go", end_no_go)
    graph.add_node("end_legal_block", end_legal_block)
    graph.add_node("end_rejected", end_rejected)
    graph.add_node("escalate_structuring", escalate_structuring)
    graph.add_node("escalate_validation", escalate_validation)

    # ── Set entry point ──────────────────────────────────
    graph.set_entry_point("a1_intake")

    # ── Add edges ────────────────────────────────────────

    # A1 → A2 (always)
    graph.add_edge("a1_intake", "a2_structuring")

    # A2 → conditional (confidence check)
    graph.add_conditional_edges(
        "a2_structuring",
        route_after_structuring,
        {
            "a2_structuring": "a2_structuring",     # retry
            "a3_go_no_go": "a3_go_no_go",           # proceed
            "escalate_structuring": "escalate_structuring",
        },
    )

    # A3 → conditional (GO / NO_GO)
    graph.add_conditional_edges(
        "a3_go_no_go",
        route_after_go_no_go,
        {
            "b1_requirements_extraction": "b1_requirements_extraction",
            "end_no_go": "end_no_go",
        },
    )

    # B1 → B2 → C1 → C2 → C3 (linear)
    graph.add_edge("b1_requirements_extraction", "b2_requirements_validation")
    graph.add_edge("b2_requirements_validation", "c1_architecture_planning")
    graph.add_edge("c1_architecture_planning", "c2_requirement_writing")
    graph.add_edge("c2_requirement_writing", "c3_narrative_assembly")

    # C3 → D1 (always)
    graph.add_edge("c3_narrative_assembly", "d1_technical_validation")

    # D1 → conditional (PASS / REJECT / escalate)
    graph.add_conditional_edges(
        "d1_technical_validation",
        route_after_validation,
        {
            "c3_narrative_assembly": "c3_narrative_assembly",  # retry loop
            "commercial_legal_parallel": "commercial_legal_parallel",
            "escalate_validation": "escalate_validation",
        },
    )

    # E1+E2 combined → conditional (CLEAR / BLOCK)
    graph.add_conditional_edges(
        "commercial_legal_parallel",
        route_after_commercial_legal,
        {
            "f1_final_readiness": "f1_final_readiness",
            "end_legal_block": "end_legal_block",
        },
    )

    # F1 → conditional (APPROVE / REJECT)
    graph.add_conditional_edges(
        "f1_final_readiness",
        route_after_approval,
        {
            "f2_submission": "f2_submission",
            "end_rejected": "end_rejected",
        },
    )

    # Terminal edges → END
    graph.add_edge("f2_submission", END)
    graph.add_edge("end_no_go", END)
    graph.add_edge("end_legal_block", END)
    graph.add_edge("end_rejected", END)
    graph.add_edge("escalate_structuring", END)
    graph.add_edge("escalate_validation", END)

    return graph.compile()


# ── Convenience runner ───────────────────────────────────

def run_pipeline(
    uploaded_file_path: str = "",
    initial_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build the graph and run it end-to-end.
    Returns the final state dict.
    """
    compiled = build_graph()

    state = initial_state or {}
    state.setdefault("uploaded_file_path", uploaded_file_path)
    state.setdefault("status", PipelineStatus.RECEIVED.value)

    logger.info("═" * 60)
    logger.info("  RFP PIPELINE STARTING")
    logger.info("═" * 60)

    final_state = compiled.invoke(state)

    logger.info("═" * 60)
    logger.info(f"  PIPELINE FINISHED — status: {final_state.get('status')}")
    logger.info("═" * 60)

    return final_state

```

## File: `rfp_automation\orchestration\transitions.py`

```python
"""
Routing functions for LangGraph conditional edges.

Each function inspects the current state dict and returns the name
of the next node to execute.  These are the governance checkpoints
described in the project spec.
"""

from __future__ import annotations

from typing import Any

from rfp_automation.config import get_settings


# ── After A2 Structuring ─────────────────────────────────

def route_after_structuring(state: dict[str, Any]) -> str:
    """
    If structuring confidence is too low after max retries → escalate.
    Otherwise → proceed to A3 Go/No-Go.
    """
    settings = get_settings()
    result = state.get("structuring_result", {})
    confidence = result.get("overall_confidence", 0)
    retries = result.get("retry_count", 0)

    if confidence < 0.6 and retries >= settings.max_structuring_retries:
        return "escalate_structuring"
    elif confidence < 0.6:
        return "a2_structuring"  # retry
    return "a3_go_no_go"


# ── After A3 Go / No-Go ──────────────────────────────────

def route_after_go_no_go(state: dict[str, Any]) -> str:
    """
    NO_GO → end.
    GO   → proceed to B1 Requirements Extraction.
    """
    result = state.get("go_no_go_result", {})
    decision = result.get("decision", "GO")

    if decision == "NO_GO":
        return "end_no_go"
    return "b1_requirements_extraction"


# ── After D1 Technical Validation ─────────────────────────

def route_after_validation(state: dict[str, Any]) -> str:
    """
    REJECT and retries < max → loop back to C3 Narrative Assembly.
    REJECT and retries >= max → escalate to human review.
    PASS → proceed to E1+E2 (commercial+legal parallel).
    """
    settings = get_settings()
    result = state.get("technical_validation", {})
    decision = result.get("decision", "PASS")
    retries = result.get("retry_count", 0)

    if decision == "REJECT":
        if retries >= settings.max_validation_retries:
            return "escalate_validation"
        return "c3_narrative_assembly"  # loop back
    return "commercial_legal_parallel"


# ── After E1+E2 Commercial & Legal Gate ───────────────────

def route_after_commercial_legal(state: dict[str, Any]) -> str:
    """
    BLOCK from E2 → end (legal veto).
    CLEAR → proceed to F1 Final Readiness.
    """
    gate = state.get("commercial_legal_gate", {})
    decision = gate.get("gate_decision", "CLEAR")

    if decision == "BLOCK":
        return "end_legal_block"
    return "f1_final_readiness"


# ── After F1 Human Approval ──────────────────────────────

def route_after_approval(state: dict[str, Any]) -> str:
    """
    APPROVE → F2 Submission.
    REJECT  → end.
    REQUEST_CHANGES → (could loop, for now end).
    """
    package = state.get("approval_package", {})
    decision = package.get("approval_decision", None)

    if decision == "APPROVE":
        return "f2_submission"
    return "end_rejected"

```

## File: `rfp_automation\orchestration\__init__.py`

```python
from .graph import build_graph, run_pipeline

__all__ = ["build_graph", "run_pipeline"]

```

## File: `rfp_automation\persistence\mongo_client.py`

```python
"""
Mongo Client — raw database connection management.
"""

from __future__ import annotations

import logging
from typing import Any

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)


class MongoClient:
    """
    Thin wrapper around pymongo for MongoDB connections.
    """

    def __init__(self):
        self.settings = get_settings()
        self._client: Any = None
        self._db: Any = None

    def connect(self) -> None:
        """Establish the MongoDB connection."""
        try:
            from pymongo import MongoClient as PyMongoClient

            self._client = PyMongoClient(self.settings.mongodb_uri)
            self._db = self._client[self.settings.mongodb_database]
            logger.info(f"Connected to MongoDB: {self.settings.mongodb_database}")
        except ImportError:
            logger.error("pymongo not installed")
            raise

    def get_database(self) -> Any:
        """Return the database handle."""
        if self._db is None:
            self.connect()
        return self._db

    def close(self) -> None:
        """Close the connection."""
        if self._client:
            self._client.close()
            logger.info("MongoDB connection closed")

```

## File: `rfp_automation\persistence\state_repository.py`

```python
"""
State Repository — persistence layer for graph state.
Handles save, load, versioning, and audit trail.
Uses in-memory dict for now; will be wired to MongoDB.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

logger = logging.getLogger(__name__)


class StateRepository:
    """
    Save/load RFPGraphState to persistent storage.
    Currently uses in-memory dict. TODO: wire to MongoDB.
    """

    def __init__(self):
        self._memory_store: dict[str, list[dict[str, Any]]] = {}

    def save_state(self, rfp_id: str, state_dict: dict[str, Any]) -> int:
        """
        Save a state snapshot and return the version number.
        Each save creates a new version (append-only for audit).
        """
        if rfp_id not in self._memory_store:
            self._memory_store[rfp_id] = []
        version = len(self._memory_store[rfp_id]) + 1
        snapshot = deepcopy(state_dict)
        snapshot["_version"] = version
        self._memory_store[rfp_id].append(snapshot)
        logger.info(f"Saved state v{version} for {rfp_id}")
        return version

    def load_state(self, rfp_id: str, version: int | None = None) -> dict[str, Any] | None:
        """
        Load the latest (or specific version) of state for an RFP.
        Returns None if not found.
        """
        snapshots = self._memory_store.get(rfp_id, [])
        if not snapshots:
            return None
        if version is not None:
            matches = [s for s in snapshots if s.get("_version") == version]
            return deepcopy(matches[0]) if matches else None
        return deepcopy(snapshots[-1])

    def list_rfps(self) -> list[str]:
        """List all RFP IDs in the store."""
        return list(self._memory_store.keys())

    def get_version_count(self, rfp_id: str) -> int:
        """Return number of saved versions for an RFP."""
        return len(self._memory_store.get(rfp_id, []))

```

## File: `rfp_automation\persistence\__init__.py`

```python
"""Persistence — MongoClient, StateRepository."""

from rfp_automation.persistence.mongo_client import MongoClient
from rfp_automation.persistence.state_repository import StateRepository

__all__ = ["MongoClient", "StateRepository"]

```

## File: `rfp_automation\prompts\architecture_prompt.txt`

```text
You are an enterprise solution architect. Given the extracted requirements and company capabilities, design the response architecture.

Requirements:
{requirements}

Capabilities:
{capabilities}

For each requirement cluster, define:
- section_id
- section_title
- assigned_requirements: list of requirement IDs
- approach: high-level solution approach
- key_technologies: relevant technologies/products

Return valid JSON with the architecture plan.

```

## File: `rfp_automation\prompts\extraction_prompt.txt`

```text
You are extracting requirements from an RFP section.

Section Title: {section_title}
Section Content:
{section_content}

For each requirement found:
- requirement_id: assign sequential ID starting from {start_id}
- text: the exact requirement text
- type: MANDATORY (must/shall) or OPTIONAL (should/prefer)
- category: TECHNICAL, FUNCTIONAL, SECURITY, COMPLIANCE, COMMERCIAL, OPERATIONAL
- impact: CRITICAL, HIGH, MEDIUM, LOW
- keywords: list of key terms

Return valid JSON array of requirements.

```

## File: `rfp_automation\prompts\go_no_go_prompt.txt`

```text
You are a strategic bid analyst performing a Go/No-Go assessment.

You will receive:
1. RFP sections (requirements extracted from the RFP document)
2. Company policies (pre-extracted rules, certifications, constraints)
3. Company capabilities (technical and business competencies)

YOUR TASK (Two Phases):

## PHASE 1: Extract Requirements
Read each RFP section and extract individual requirements. Each requirement should be a specific, actionable demand from the RFP (e.g., "Must have ISO 27001 certification", "24/7 support required", "Data must reside within US borders").

## PHASE 2: Map Requirements to Policies
For each extracted requirement, compare it against the provided company policies and capabilities. Classify each mapping as:
- ALIGNS: Company policy/capability directly satisfies this requirement
- VIOLATES: Company policy explicitly contradicts or prohibits this requirement
- RISK: Partial match or uncertain — the company may or may not meet this
- NO_MATCH: No relevant company policy or capability found for this requirement

## SCORING
After mapping all requirements, score these dimensions (1-10):
- strategic_fit_score: How well this RFP aligns with the company's business direction
- technical_feasibility_score: Can the company technically deliver what's asked?
- regulatory_risk_score: Level of compliance/regulatory risk (10 = very risky)

## DECISION RULES
- If ANY requirement has mapping_status = "VIOLATES" with a critical company policy → NO_GO
- If regulatory_risk_score > 7 → NO_GO
- If strategic_fit_score < 3 AND technical_feasibility_score < 3 → NO_GO
- Otherwise → GO

---

RFP SECTIONS:
{rfp_sections}

COMPANY POLICIES:
{company_policies}

COMPANY CAPABILITIES:
{capabilities}

---

Return ONLY valid JSON (no markdown fencing). Use this exact structure:
{
  "strategic_fit_score": 7.5,
  "technical_feasibility_score": 8.0,
  "regulatory_risk_score": 3.0,
  "decision": "GO",
  "justification": "Brief overall justification",
  "red_flags": ["Any red flags identified"],
  "policy_violations": ["List of violated policy texts"],
  "requirement_mappings": [
    {
      "requirement_id": "RFP-REQ-001",
      "requirement_text": "The exact requirement from the RFP",
      "source_section": "Section title where this was found",
      "mapping_status": "ALIGNS",
      "matched_policy": "The matching policy text or empty string",
      "matched_policy_id": "POL-XXX or empty string",
      "confidence": 0.95,
      "reasoning": "Why this mapping was chosen"
    }
  ]
}

```

## File: `rfp_automation\prompts\legal_prompt.txt`

```text
You are a legal analyst reviewing contract clauses.

Contract Clauses from RFP:
{clauses}

Our Standard Terms:
{legal_templates}

For each clause:
- clause_id
- clause_text
- risk_level: LOW, MEDIUM, HIGH, CRITICAL
- concern: what's the risk?
- recommendation: accept / negotiate / reject

Decision:
- APPROVED: No HIGH or CRITICAL risks
- CONDITIONAL: HIGH risks that can be negotiated
- BLOCKED: Any CRITICAL risk (unlimited liability, missing required cert, etc.)

Return valid JSON.

```

## File: `rfp_automation\prompts\policy_extraction_prompt.txt`

```text
You are an expert policy analyst. Extract every rule, policy, certification, constraint, prohibition, and capability statement from the following company document text.

DOCUMENT TEXT:
{document_text}

DOCUMENT TYPE: {doc_type}
SOURCE FILENAME: {filename}

INSTRUCTIONS:
1. Read the entire document text carefully.
2. Identify every individual rule, policy, certification, constraint, prohibition, threshold, standard, or capability statement.
3. Each item must be a standalone, self-contained statement.
4. Assign a unique policy_id in the format "POL-001", "POL-002", etc., starting from {start_id}.
5. Classify each item into exactly one category and one rule_type.
6. Assign a severity level based on how critical the policy is to business operations and compliance.

CATEGORIES (pick one):
- certification: Certifications held or required (ISO, SOC, HIPAA, etc.)
- legal: Legal obligations, contract terms, NDA requirements
- compliance: Regulatory and compliance requirements (GDPR, data protection, etc.)
- operational: Operational policies, SLAs, uptime requirements, staffing
- commercial: Pricing rules, margin thresholds, payment terms
- governance: Internal governance, approval workflows, decision authority
- capability: Technical or business capabilities the company possesses

RULE TYPES (pick one):
- constraint: A limitation or boundary that must not be exceeded
- requirement: Something that must be fulfilled or maintained
- capability: A skill, service, or competency the company has
- prohibition: Something explicitly forbidden
- threshold: A numeric limit or minimum/maximum value
- standard: A standard or framework that is followed

SEVERITY LEVELS (pick one):
- critical: Violation would cause legal liability, contract breach, or regulatory penalty
- high: Violation would significantly impact operations or client relationships
- medium: Important but not immediately damaging if temporarily unmet
- low: Best practice or nice-to-have

Return ONLY a valid JSON array. No markdown fencing, no explanation. Each element must have:
{
  "policy_id": "POL-XXX",
  "policy_text": "The exact policy or rule statement",
  "category": "one of the categories above",
  "rule_type": "one of the rule types above",
  "severity": "critical|high|medium|low",
  "source_section": "The section or heading this was found under"
}

```

## File: `rfp_automation\prompts\structuring_prompt.txt`

```text
You are an expert RFP document analyst. Your task is to classify the following document chunks into logical sections of an RFP.

Each section must be assigned one of these categories:
- scope: Project scope, objectives, background, overview
- technical: Technical requirements, specifications, architecture
- compliance: Regulatory, certification, standards requirements
- legal: Contract terms, liability, IP, indemnification clauses
- submission: Submission instructions, deadlines, format requirements
- evaluation: Evaluation criteria, scoring methodology, selection process

For each section, provide:
- section_id: Unique ID (e.g., SEC-01, SEC-02)
- title: Descriptive section title
- category: One of the 6 categories above
- content_summary: 2-3 sentence summary of the section content
- confidence: Your confidence in this classification (0.0 to 1.0). Use 0.9+ only if the section is unambiguous. Use 0.5-0.7 for sections that could fit multiple categories.
- page_range: Estimated page range (e.g., "1-3") or empty string if unknown

{retry_hint}

Document chunks:
{chunks}

Return a valid JSON array of section objects. Example format:
[
  {{
    "section_id": "SEC-01",
    "title": "Project Overview and Scope",
    "category": "scope",
    "content_summary": "Describes the project background, objectives, and expected deliverables.",
    "confidence": 0.92,
    "page_range": "1-3"
  }}
]

IMPORTANT:
- Every chunk must be assigned to exactly one section.
- Merge related chunks into the same section where appropriate.
- Return ONLY the JSON array, no other text.

```

## File: `rfp_automation\prompts\validation_prompt.txt`

```text
You are validating a proposal against original requirements.

Original Requirements:
{requirements}

Proposal Text:
{proposal}

Check:
1. Completeness — Are all mandatory requirements addressed?
2. Alignment — Do responses genuinely answer requirements (not just keywords)?
3. Realism — Are claims supportable (no overpromising)?
4. Consistency — No contradictions between sections?

Return JSON with:
- decision: PASS or REJECT
- checks: array of {check_name, passed, issues}
- critical_failures: count
- warnings: count
- feedback_for_revision: string (if REJECT)

```

## File: `rfp_automation\prompts\writing_prompt.txt`

```text
You are writing a proposal response section.

Section: {section_title}
Requirements to address:
{requirements}

Company capabilities:
{capabilities}

Write a professional response (150-200 words per requirement) that:
1. Confirms understanding of requirements
2. Explains our solution approach
3. Provides specific details (no vague claims)
4. References actual products/services/certifications
5. Highlights benefits and differentiators

Tone: Professional, confident, specific.

```

## File: `rfp_automation\services\audit_service.py`

```python
"""
Audit Service — dedicated service for recording and querying audit trails.
Records to MongoDB via the persistence layer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class AuditService:
    """
    Records agent actions, pipeline decisions, and gate results.
    Uses in-memory list for now. Will be wired to MongoDB.
    """

    def __init__(self):
        self._entries: list[dict[str, Any]] = []

    def record(
        self,
        rfp_id: str,
        agent: str,
        action: str,
        details: str = "",
        state_version: int = 0,
    ) -> dict[str, Any]:
        """Record an audit entry and return it."""
        entry = {
            "rfp_id": rfp_id,
            "agent": agent,
            "action": action,
            "details": details,
            "state_version": state_version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # TODO: Write to MongoDB audit collection once wired
        self._entries.append(entry)
        logger.debug(f"[AUDIT] {agent} → {action}: {details}")

        return entry

    def get_trail(self, rfp_id: str) -> list[dict[str, Any]]:
        """Return all audit entries for an RFP."""
        return [e for e in self._entries if e["rfp_id"] == rfp_id]

    def get_all(self) -> list[dict[str, Any]]:
        """Return all audit entries (for debugging)."""
        return list(self._entries)

```

## File: `rfp_automation\services\file_service.py`

```python
"""
File Service — abstraction over local filesystem and S3.
Handles upload, download, and archival of RFP files and outputs.
"""

from __future__ import annotations

import logging
from pathlib import Path

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)


class FileService:
    """Swappable file storage — local for dev, S3 for prod."""

    def __init__(self):
        self.settings = get_settings()
        self.backend = self.settings.storage_backend

        if self.backend == "local":
            self.base_path = Path(self.settings.local_storage_path)
            self.base_path.mkdir(parents=True, exist_ok=True)

    def save_file(self, file_bytes: bytes, destination: str) -> str:
        """Save a file and return the stored path/key."""
        if self.backend == "local":
            path = self.base_path / destination
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(file_bytes)
            logger.info(f"Saved file to {path}")
            return str(path)

        # TODO: S3 upload with boto3
        raise NotImplementedError(f"Backend '{self.backend}' not implemented")

    def load_file(self, path: str) -> bytes:
        """Load a file's content."""
        if self.backend == "local":
            return Path(path).read_bytes()
        raise NotImplementedError

    def archive(self, rfp_id: str, files: dict[str, bytes]) -> str:
        """Archive all deliverables for an RFP."""
        archive_dir = f"archive/{rfp_id}"
        for name, content in files.items():
            self.save_file(content, f"{archive_dir}/{name}")
        logger.info(f"Archived {len(files)} files for {rfp_id}")
        return archive_dir

    def list_files(self, prefix: str = "") -> list[str]:
        """List files under a prefix."""
        if self.backend == "local":
            base = self.base_path / prefix
            if base.exists():
                return [
                    str(p.relative_to(self.base_path))
                    for p in base.rglob("*")
                    if p.is_file()
                ]
            return []
        raise NotImplementedError

```

## File: `rfp_automation\services\llm_service.py`

```python
"""
LLM Service — centralized Groq Cloud LLM client.

All agents use this module to make LLM calls. Provides:
  - get_llm()         → returns configured Groq ChatModel
  - llm_json_call()   → structured output (parsed into Pydantic model)
  - llm_text_call()   → raw text response
"""

from __future__ import annotations

import logging
from typing import Type, TypeVar

from pydantic import BaseModel

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_llm_instance = None


def get_llm():
    """
    Return a configured Groq LLM client (singleton).
    Uses langchain-groq's ChatGroq.
    """
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance

    settings = get_settings()

    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY is not set in environment / .env file")

    from langchain_groq import ChatGroq

    _llm_instance = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )
    logger.info(f"Initialized Groq LLM: {settings.llm_model}")
    return _llm_instance


def llm_json_call(prompt: str, output_model: Type[T]) -> T:
    """
    Call the LLM and parse the response into a Pydantic model.
    Uses LangChain's with_structured_output() for reliable JSON parsing.
    """
    import time

    logger.debug(
        f"[LLM-JSON] Prompt length: {len(prompt)} chars | "
        f"Target model: {output_model.__name__}"
    )
    logger.debug(f"[LLM-JSON] Prompt preview:\n{prompt[:500]}{'…' if len(prompt) > 500 else ''}")

    llm = get_llm()
    structured_llm = llm.with_structured_output(output_model)

    t0 = time.perf_counter()
    result = structured_llm.invoke(prompt)
    elapsed = time.perf_counter() - t0

    logger.info(f"[LLM-JSON] Response received in {elapsed:.2f}s | Model: {output_model.__name__}")
    logger.debug(f"[LLM-JSON] Parsed result: {result}")
    return result


def llm_text_call(prompt: str, max_retries: int = 0) -> str:
    """
    Call the LLM and return the raw text response.
    Retries up to *max_retries* times on empty responses.
    """
    import time

    logger.debug(
        f"[LLM-TEXT] Prompt length: {len(prompt)} chars"
    )
    logger.debug(f"[LLM-TEXT] Prompt preview:\n{prompt[:500]}{'…' if len(prompt) > 500 else ''}")

    llm = get_llm()
    attempts = max_retries + 1

    for attempt in range(1, attempts + 1):
        t0 = time.perf_counter()
        response = llm.invoke(prompt)
        elapsed = time.perf_counter() - t0
        content = response.content or ""

        # Log response metadata (finish_reason, token usage)
        meta = getattr(response, "response_metadata", {}) or {}
        finish_reason = meta.get("finish_reason", "unknown")
        usage = meta.get("token_usage") or meta.get("usage", {})
        logger.info(
            f"[LLM-TEXT] Response received in {elapsed:.2f}s | "
            f"Response length: {len(content)} chars | "
            f"finish_reason={finish_reason} | "
            f"tokens={usage}"
        )
        logger.debug(f"[LLM-TEXT] Full response:\n{content}")

        if content.strip():
            return content

        # Empty response — warn and retry if allowed
        logger.warning(
            f"[LLM-TEXT] Empty response on attempt {attempt}/{attempts} "
            f"(finish_reason={finish_reason}). "
            f"{'Retrying…' if attempt < attempts else 'No retries left.'}"
        )

    return content  # return whatever we got (empty string)

```

## File: `rfp_automation\services\parsing_service.py`

```python
"""
Parsing Service — structured block extraction from PDF documents.

Extracts text preserving:
  • Headings (detected via font-size / bold)
  • Paragraphs, bullet lists, numbered sections
  • Line breaks, number formatting, units (Mbps, %, INR, ms, etc.)
  • Page numbers per block

Does NOT:
  • Summarize or interpret content
  • Parse table cells (returns mock placeholder)
  • Merge content across headings
  • Deduplicate blocks
  • Call any LLM
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Regex patterns for metadata extraction ───────────────

_RFP_NUMBER_RE = re.compile(
    r"(?:RFP\s*(?:Number|No\.?|#|Ref(?:erence)?)?[\s:]*)(RFP[-\s]?\S+)",
    re.IGNORECASE,
)
_ORGANIZATION_RE = re.compile(
    r"(?:Issuing\s+Organization|Issued\s+by|Company|Organisation)[\s:]+(.+)",
    re.IGNORECASE,
)
_ISSUE_DATE_RE = re.compile(
    r"(?:Issue\s+Date|Date\s+of\s+Issue|Published|Release\s+Date)[\s:]+(.+)",
    re.IGNORECASE,
)
_DEADLINE_RE = re.compile(
    r"(?:Submission\s+Deadline|Due\s+Date|Closing\s+Date|Deadline)[\s:]+(.+)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(
    r"(?:Phone|Tel|Contact)[\s:]*([+\d][\d \t\-().]{7,})", re.IGNORECASE
)


class ParsingService:
    """
    Extract structured blocks from PDF documents.

    Primary interface for Stage 1 (Intake):
        blocks   = ParsingService.parse_pdf_blocks(path)
        metadata = ParsingService.extract_metadata(blocks)
        chunks   = ParsingService.prepare_chunks(blocks)
    """

    # ── Block extraction ─────────────────────────────────

    @staticmethod
    def parse_pdf_blocks(file_path: str) -> list[dict[str, Any]]:
        """
        Extract structured blocks from a PDF using PyMuPDF dict mode.

        Each block: {block_id, type, text, page_number}
        Types: "heading" | "paragraph" | "list" | "table_mock"
        """
        import fitz  # PyMuPDF

        doc = fitz.open(file_path)

        # ── First pass: determine body font size (most common) ──
        font_sizes: list[float] = []
        for page in doc:
            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:  # text blocks only
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if span.get("text", "").strip():
                            font_sizes.append(round(span.get("size", 0), 1))

        body_font_size = 0.0
        if font_sizes:
            body_font_size = Counter(font_sizes).most_common(1)[0][0]

        # ── Second pass: extract and classify blocks ─────
        blocks: list[dict[str, Any]] = []
        blk_counter = 0
        tbl_counter = 0

        for page_idx, page in enumerate(doc):
            page_number = page_idx + 1
            page_dict = page.get_text("dict")

            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:  # skip image blocks
                    continue

                # Gather text and font info from all spans
                line_texts: list[str] = []
                span_positions: list[list[float]] = []  # x-positions per line
                max_font_size = 0.0
                has_bold = False

                for line in block.get("lines", []):
                    parts: list[str] = []
                    x_positions: list[float] = []
                    for span in line.get("spans", []):
                        text = span.get("text", "")
                        if text.strip():
                            parts.append(text)
                            x_positions.append(round(span["bbox"][0], 1))
                            size = span.get("size", 0)
                            if size > max_font_size:
                                max_font_size = size
                            # Bit 4 (value 16) = bold in PyMuPDF flags
                            if span.get("flags", 0) & 16:
                                has_bold = True
                    if parts:
                        line_texts.append("".join(parts))
                        span_positions.append(x_positions)

                if not line_texts:
                    continue

                full_text = "\n".join(line_texts)

                # ── Table detection ──────────────────────
                if _is_tabular(span_positions, line_texts):
                    tbl_counter += 1
                    blocks.append({
                        "block_id": f"tbl-{tbl_counter:03d}",
                        "type": "table_mock",
                        "text": "[TABLE DETECTED — STRUCTURE TO BE IMPLEMENTED LATER]",
                        "page_number": page_number,
                    })
                    continue

                # ── Block classification ─────────────────
                block_type = _classify_block(
                    full_text, max_font_size, has_bold, body_font_size
                )

                blk_counter += 1
                blocks.append({
                    "block_id": f"blk-{blk_counter:03d}",
                    "type": block_type,
                    "text": full_text,
                    "page_number": page_number,
                })

        doc.close()
        logger.info(
            f"Extracted {len(blocks)} blocks from {Path(file_path).name} "
            f"({blk_counter} text, {tbl_counter} table mocks)"
        )
        return blocks

    # ── Metadata extraction ──────────────────────────────

    @staticmethod
    def extract_metadata(blocks: list[dict[str, Any]]) -> dict[str, str | None]:
        """
        Extract RFP metadata from blocks using regex.

        Returns dict with keys:
          rfp_number, organization, issue_date, deadline,
          contact_email, contact_phone

        Values are None when not found.
        """
        # Concatenate text blocks (skip table mocks)
        full_text = "\n".join(
            b["text"] for b in blocks if b["type"] != "table_mock"
        )

        metadata: dict[str, str | None] = {
            "rfp_number": None,
            "organization": None,
            "issue_date": None,
            "deadline": None,
            "contact_email": None,
            "contact_phone": None,
        }

        m = _RFP_NUMBER_RE.search(full_text)
        if m:
            metadata["rfp_number"] = m.group(1).strip()

        m = _ORGANIZATION_RE.search(full_text)
        if m:
            metadata["organization"] = m.group(1).strip()

        m = _ISSUE_DATE_RE.search(full_text)
        if m:
            metadata["issue_date"] = m.group(1).strip()

        m = _DEADLINE_RE.search(full_text)
        if m:
            metadata["deadline"] = m.group(1).strip()

        m = _EMAIL_RE.search(full_text)
        if m:
            metadata["contact_email"] = m.group(0).strip()

        m = _PHONE_RE.search(full_text)
        if m:
            metadata["contact_phone"] = m.group(1).strip()

        return metadata

    # ── Chunk preparation ────────────────────────────────

    @staticmethod
    def prepare_chunks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Convert parsed blocks into structured chunk objects.

        Each chunk:
          {chunk_id, content_type, section_hint, text, page_start, page_end}

        section_hint tracks the last detected heading.
        """
        chunks: list[dict[str, Any]] = []
        last_heading = "Untitled Section"

        for block in blocks:
            if block["type"] == "heading":
                last_heading = block["text"].strip()

            content_type = (
                "table_mock" if block["type"] == "table_mock" else "text"
            )
            text = (
                "[TABLE DETECTED]"
                if block["type"] == "table_mock"
                else block["text"]
            )

            chunks.append({
                "chunk_id": block["block_id"],
                "content_type": content_type,
                "section_hint": last_heading,
                "text": text,
                "page_start": block["page_number"],
                "page_end": block["page_number"],
            })

        return chunks

    # ── Legacy interface (backward compatibility) ────────

    @staticmethod
    def parse(file_path: str) -> str:
        """
        Parse a document and return raw concatenated text.
        Kept for backward compatibility with RFPVectorStore.
        """
        ext = Path(file_path).suffix.lower()
        if ext == ".pdf":
            blocks = ParsingService.parse_pdf_blocks(file_path)
            return "\n".join(b["text"] for b in blocks)
        elif ext == ".docx":
            return ParsingService._parse_docx(file_path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")

    @staticmethod
    def _parse_docx(file_path: str) -> str:
        """Extract text from DOCX using python-docx."""
        try:
            from docx import Document

            doc = Document(file_path)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            logger.warning("python-docx not installed — returning mock text")
            return f"[Mock DOCX text extracted from {file_path}]"

    @staticmethod
    def chunk_text(
        text: str,
        chunk_size: int = 1000,
        overlap: int = 200,
    ) -> list[str]:
        """
        Split text into overlapping chunks for embedding/retrieval.
        Kept for backward compatibility (used by RFPVectorStore).
        """
        if not text:
            return []

        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk.strip())
            start += chunk_size - overlap
        return chunks


# ── Private helpers ──────────────────────────────────────


def _classify_block(
    text: str,
    max_font_size: float,
    has_bold: bool,
    body_font_size: float,
) -> str:
    """Classify a text block as heading, list, or paragraph."""
    stripped = text.strip()
    lines = stripped.split("\n")

    # List detection: bullet or numbered pattern
    list_pattern = re.compile(
        r"^\s*(?:[•●○◦▪▸\-\*]|\d+[\.\):]|[a-z][\.\)]|[ivxlc]+[\.\)])\s",
        re.IGNORECASE | re.MULTILINE,
    )
    list_line_count = sum(1 for ln in lines if list_pattern.match(ln))
    if list_line_count > 0 and list_line_count >= len(lines) * 0.5:
        return "list"

    # Heading detection: larger font or bold AND short text
    is_larger = body_font_size > 0 and max_font_size >= body_font_size + 1.5
    is_short = len(stripped) < 200 and len(lines) <= 3

    if is_short and (is_larger or has_bold):
        return "heading"

    # Numbered section heading: "1. Title" or "1.2.3 Title" — short line
    if is_short and re.match(r"^\d+(\.\d+)*\.?\s+\S", stripped):
        return "heading"

    return "paragraph"


def _is_tabular(
    span_positions: list[list[float]], line_texts: list[str]
) -> bool:
    """
    Heuristic: detect if a block looks like a table.

    Checks:
      - At least 3 lines
      - Most lines have 3+ spans at distinct x-positions
      - OR lines have multi-space separated column patterns
    """
    if len(line_texts) < 3:
        return False

    # Method 1: multiple distinct x-offsets per line
    multi_col_lines = 0
    for positions in span_positions:
        if len(positions) >= 3:
            distinct = _count_distinct(positions, tolerance=5.0)
            if distinct >= 3:
                multi_col_lines += 1

    if multi_col_lines >= len(line_texts) * 0.6:
        return True

    # Method 2: multi-space separated columns in text
    col_pattern = re.compile(r"\S+\s{3,}\S+\s{3,}\S+")
    col_lines = sum(1 for t in line_texts if col_pattern.search(t))
    if col_lines >= len(line_texts) * 0.6 and col_lines >= 3:
        return True

    return False


def _count_distinct(values: list[float], tolerance: float) -> int:
    """Count distinct values within a tolerance."""
    if not values:
        return 0
    sorted_vals = sorted(values)
    distinct = 1
    last = sorted_vals[0]
    for v in sorted_vals[1:]:
        if v - last > tolerance:
            distinct += 1
            last = v
    return distinct

```

## File: `rfp_automation\services\policy_extraction_service.py`

```python
"""
Policy Extraction Service — extract rules, policies, certifications from
company documents using the LLM at upload time.

Persists results to extracted_policies.json as the single source of truth.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rfp_automation.services.llm_service import llm_text_call

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "policy_extraction_prompt.txt"
_POLICIES_PATH = Path(__file__).resolve().parent.parent / "mcp" / "knowledge_data" / "extracted_policies.json"


class PolicyExtractionService:
    """Extract and persist company policies from uploaded documents."""

    # ── Public API ───────────────────────────────────

    def extract_and_persist(
        self,
        doc_id: str,
        doc_type: str,
        texts: list[str],
        filename: str,
    ) -> list[dict[str, Any]]:
        """
        Extract policies from document text via LLM and append to the
        persisted JSON file.  Returns list of newly extracted policies.
        """
        # Determine next POL-ID
        existing = self._load_policies()
        start_id = self._next_policy_number(existing)

        # Build prompt
        combined_text = "\n".join(texts[:50])  # first 50 blocks
        prompt = self._build_prompt(combined_text, doc_type, filename, start_id)

        # Call LLM with retries on empty responses
        logger.info(f"[PolicyExtraction] Extracting policies from {filename} ({len(texts)} blocks)…")
        raw_response = llm_text_call(prompt, max_retries=2)

        if not raw_response.strip():
            logger.error(
                f"[PolicyExtraction] LLM returned empty response after all retries "
                f"for {filename} — no policies extracted"
            )
            return []

        # Parse
        new_policies = self._parse_response(raw_response)
        if not new_policies:
            logger.warning(f"[PolicyExtraction] No policies extracted from {filename}")
            return []

        # Enrich with metadata
        now = datetime.now(timezone.utc).isoformat()
        for pol in new_policies:
            pol["source_doc_id"] = doc_id
            pol["source_filename"] = filename
            pol["created_at"] = now
            pol["is_manually_added"] = False

        # Persist
        all_policies = existing + new_policies
        self._save_policies(all_policies)

        logger.info(f"[PolicyExtraction] Extracted {len(new_policies)} policies from {filename}")
        return new_policies

    # ── CRUD helpers (used by API routes) ────────────

    @staticmethod
    def get_all_policies() -> list[dict[str, Any]]:
        """Return all persisted policies."""
        return PolicyExtractionService._load_policies_static()

    @staticmethod
    def add_policy(policy: dict[str, Any]) -> dict[str, Any]:
        """Add a manually created policy."""
        policies = PolicyExtractionService._load_policies_static()

        # Generate next ID
        start = PolicyExtractionService._next_policy_number_static(policies)
        policy["policy_id"] = f"POL-{start:03d}"
        policy["created_at"] = datetime.now(timezone.utc).isoformat()
        policy["is_manually_added"] = True
        policy.setdefault("source_doc_id", "")
        policy.setdefault("source_filename", "manual")

        policies.append(policy)
        PolicyExtractionService._save_policies_static(policies)
        return policy

    @staticmethod
    def update_policy(policy_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Update an existing policy by ID.  Returns updated policy or None."""
        policies = PolicyExtractionService._load_policies_static()
        for pol in policies:
            if pol.get("policy_id") == policy_id:
                allowed = {"policy_text", "category", "rule_type", "severity", "source_section"}
                for key in allowed:
                    if key in updates:
                        pol[key] = updates[key]
                pol["updated_at"] = datetime.now(timezone.utc).isoformat()
                PolicyExtractionService._save_policies_static(policies)
                return pol
        return None

    @staticmethod
    def delete_policy(policy_id: str) -> bool:
        """Delete a policy by ID.  Returns True if found and deleted."""
        policies = PolicyExtractionService._load_policies_static()
        original_len = len(policies)
        policies = [p for p in policies if p.get("policy_id") != policy_id]
        if len(policies) == original_len:
            return False
        PolicyExtractionService._save_policies_static(policies)
        return True

    # ── Internal helpers ─────────────────────────────

    def _build_prompt(
        self, document_text: str, doc_type: str, filename: str, start_id: int
    ) -> str:
        template = _PROMPT_PATH.read_text(encoding="utf-8")
        return template.replace("{document_text}", document_text[:15_000]).replace(
            "{doc_type}", doc_type
        ).replace("{filename}", filename).replace("{start_id}", str(start_id))

    def _parse_response(self, raw: str) -> list[dict[str, Any]]:
        """Parse LLM response into list of policy dicts."""
        # Strip markdown fencing if present
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        # Try to find JSON array
        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                return [self._validate_policy(p) for p in data if isinstance(p, dict)]
        except json.JSONDecodeError:
            pass

        # Fallback: find first [ ... ] in the response
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, list):
                    return [self._validate_policy(p) for p in data if isinstance(p, dict)]
            except json.JSONDecodeError:
                pass

        logger.error("[PolicyExtraction] Failed to parse LLM response as JSON array")
        return []

    @staticmethod
    def _validate_policy(p: dict) -> dict:
        """Ensure required fields exist with defaults."""
        VALID_CATEGORIES = {"certification", "legal", "compliance", "operational",
                            "commercial", "governance", "capability"}
        VALID_RULE_TYPES = {"constraint", "requirement", "capability", "prohibition",
                            "threshold", "standard"}
        VALID_SEVERITIES = {"critical", "high", "medium", "low"}

        p.setdefault("policy_id", "POL-000")
        p.setdefault("policy_text", "")
        cat = p.get("category", "").lower()
        p["category"] = cat if cat in VALID_CATEGORIES else "capability"
        rt = p.get("rule_type", "").lower()
        p["rule_type"] = rt if rt in VALID_RULE_TYPES else "requirement"
        sev = p.get("severity", "").lower()
        p["severity"] = sev if sev in VALID_SEVERITIES else "medium"
        p.setdefault("source_section", "")
        return p

    def _load_policies(self) -> list[dict[str, Any]]:
        return self._load_policies_static()

    def _save_policies(self, policies: list[dict[str, Any]]) -> None:
        self._save_policies_static(policies)

    def _next_policy_number(self, policies: list[dict]) -> int:
        return self._next_policy_number_static(policies)

    @staticmethod
    def _load_policies_static() -> list[dict[str, Any]]:
        if not _POLICIES_PATH.exists():
            return []
        try:
            data = json.loads(_POLICIES_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    @staticmethod
    def _save_policies_static(policies: list[dict[str, Any]]) -> None:
        os.makedirs(_POLICIES_PATH.parent, exist_ok=True)
        _POLICIES_PATH.write_text(
            json.dumps(policies, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _next_policy_number_static(policies: list[dict]) -> int:
        max_num = 0
        for p in policies:
            pid = p.get("policy_id", "")
            match = re.search(r"POL-(\d+)", pid)
            if match:
                max_num = max(max_num, int(match.group(1)))
        return max_num + 1

```

## File: `rfp_automation\services\storage_service.py`

```python
"""
Storage Service — high-level facade for file + state persistence.
Coordinates FileService and StateRepository for common operations.
"""

from __future__ import annotations

import logging
from typing import Any

from rfp_automation.services.file_service import FileService
from rfp_automation.persistence.state_repository import StateRepository

logger = logging.getLogger(__name__)


class StorageService:
    """Orchestrates file + state persistence."""

    def __init__(self):
        self.files = FileService()
        self.state_repo = StateRepository()

    def save_rfp_upload(self, rfp_id: str, file_bytes: bytes, filename: str) -> str:
        """Save an uploaded RFP file and return the path."""
        dest = f"uploads/{rfp_id}_{filename}"
        return self.files.save_file(file_bytes, dest)

    def save_pipeline_state(self, rfp_id: str, state_dict: dict[str, Any]) -> int:
        """Save a pipeline state snapshot and return version."""
        return self.state_repo.save_state(rfp_id, state_dict)

    def load_pipeline_state(self, rfp_id: str) -> dict[str, Any] | None:
        """Load the latest pipeline state for an RFP."""
        return self.state_repo.load_state(rfp_id)

    def list_all_rfps(self) -> list[str]:
        """List all known RFP IDs."""
        return self.state_repo.list_rfps()

```

## File: `rfp_automation\services\__init__.py`

```python
"""Services — FileService, ParsingService, StorageService, AuditService."""

from rfp_automation.services.file_service import FileService
from rfp_automation.services.parsing_service import ParsingService
from rfp_automation.services.storage_service import StorageService
from rfp_automation.services.audit_service import AuditService

__all__ = ["FileService", "ParsingService", "StorageService", "AuditService"]

```

## File: `rfp_automation\tests\test_agents.py`

```python
"""
Tests: Individual agent behaviour.

A1 Intake is now implemented — it should raise FileNotFoundError for
a non-existent file.  All other agents still raise NotImplementedError.

Run with:
    pytest rfp_automation/tests/test_agents.py -v
"""

import json
import pytest
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.enums import PipelineStatus


def _empty_state() -> dict:
    return RFPGraphState(
        uploaded_file_path="/test/rfp.pdf",
        status=PipelineStatus.RECEIVED,
    ).model_dump()


class TestIntakeAgent:
    def test_raises_file_not_found_for_missing_file(self):
        """A1 is implemented — it validates the file exists."""
        from rfp_automation.agents import IntakeAgent

        agent = IntakeAgent()
        with pytest.raises(FileNotFoundError):
            agent.process(_empty_state())

    def test_raises_value_error_for_no_path(self):
        """A1 is implemented — it rejects empty file path."""
        from rfp_automation.agents import IntakeAgent

        agent = IntakeAgent()
        state = RFPGraphState(status=PipelineStatus.RECEIVED).model_dump()
        with pytest.raises(ValueError, match="No file path"):
            agent.process(state)


class TestStructuringAgent:
    """Tests for A2 Structuring Agent."""

    def _structuring_state(self, rfp_id="RFP-TEST1234") -> dict:
        """State with rfp_id set (A1 has already run)."""
        from rfp_automation.models.schemas import RFPMetadata

        return RFPGraphState(
            uploaded_file_path="/test/rfp.pdf",
            status=PipelineStatus.STRUCTURING,
            rfp_metadata=RFPMetadata(rfp_id=rfp_id),
            raw_text="This is test RFP content for structuring.",
        ).model_dump()

    def test_structuring_success(self, monkeypatch):
        """High-confidence LLM response → sections populated, status = GO_NO_GO."""
        from rfp_automation.agents import StructuringAgent

        mock_chunks = [
            {"id": "chunk_0", "score": 0.9, "text": "Project scope...", "chunk_index": 0, "metadata": {}},
            {"id": "chunk_1", "score": 0.9, "text": "Technical specs...", "chunk_index": 1, "metadata": {}},
        ]
        llm_response = json.dumps([
            {
                "section_id": "SEC-01",
                "title": "Project Scope",
                "category": "scope",
                "content_summary": "Describes the project scope.",
                "confidence": 0.92,
                "page_range": "1-3",
            },
            {
                "section_id": "SEC-02",
                "title": "Technical Requirements",
                "category": "technical",
                "content_summary": "Lists technical specs.",
                "confidence": 0.88,
                "page_range": "4-8",
            },
        ])

        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.MCPService",
            lambda: type("MockMCP", (), {"query_rfp_all_chunks": lambda self, rfp_id, top_k=100: mock_chunks})(),
        )
        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.llm_text_call",
            lambda prompt: llm_response,
        )

        agent = StructuringAgent()
        result = agent.process(self._structuring_state())

        assert result["structuring_result"]["overall_confidence"] >= 0.6
        assert len(result["structuring_result"]["sections"]) == 2
        assert result["status"] == PipelineStatus.GO_NO_GO.value

    def test_structuring_low_confidence_increments_retry(self, monkeypatch):
        """Low-confidence LLM response → retry_count incremented, status stays STRUCTURING."""
        from rfp_automation.agents import StructuringAgent

        mock_chunks = [
            {"id": "chunk_0", "score": 0.5, "text": "Ambiguous content...", "chunk_index": 0, "metadata": {}},
        ]
        llm_response = json.dumps([
            {
                "section_id": "SEC-01",
                "title": "Unclear Section",
                "category": "scope",
                "content_summary": "Hard to classify.",
                "confidence": 0.3,
                "page_range": "",
            },
        ])

        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.MCPService",
            lambda: type("MockMCP", (), {"query_rfp_all_chunks": lambda self, rfp_id, top_k=100: mock_chunks})(),
        )
        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.llm_text_call",
            lambda prompt: llm_response,
        )

        agent = StructuringAgent()
        result = agent.process(self._structuring_state())

        assert result["structuring_result"]["overall_confidence"] < 0.6
        assert result["structuring_result"]["retry_count"] == 1
        assert result["status"] == PipelineStatus.STRUCTURING.value

    def test_structuring_invalid_json_triggers_retry(self, monkeypatch):
        """Malformed LLM response → 0 sections, confidence = 0, retry incremented."""
        from rfp_automation.agents import StructuringAgent

        mock_chunks = [
            {"id": "chunk_0", "score": 0.9, "text": "Some content...", "chunk_index": 0, "metadata": {}},
        ]

        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.MCPService",
            lambda: type("MockMCP", (), {"query_rfp_all_chunks": lambda self, rfp_id, top_k=100: mock_chunks})(),
        )
        monkeypatch.setattr(
            "rfp_automation.agents.structuring_agent.llm_text_call",
            lambda prompt: "This is not valid JSON at all",
        )

        agent = StructuringAgent()
        result = agent.process(self._structuring_state())

        assert result["structuring_result"]["overall_confidence"] == 0.0
        assert result["structuring_result"]["retry_count"] == 1
        assert len(result["structuring_result"]["sections"]) == 0

    def test_structuring_no_rfp_id_raises(self):
        """Missing rfp_id → ValueError."""
        from rfp_automation.agents import StructuringAgent

        agent = StructuringAgent()
        state = RFPGraphState(
            status=PipelineStatus.STRUCTURING,
        ).model_dump()
        with pytest.raises(ValueError, match="No rfp_id"):
            agent.process(state)


class TestGoNoGoAgent:

    @staticmethod
    def _go_no_go_state():
        """State with rfp_id and sections ready for A3."""
        from rfp_automation.models.schemas import RFPMetadata, StructuringResult, RFPSection
        return RFPGraphState(
            status=PipelineStatus.GO_NO_GO,
            rfp_metadata=RFPMetadata(rfp_id="RFP-TEST-001", title="Test RFP"),
            structuring_result=StructuringResult(
                sections=[
                    RFPSection(
                        section_id="SEC-01",
                        title="Security Requirements",
                        category="compliance",
                        content_summary="Must have ISO 27001. Data at rest encryption required.",
                        confidence=0.9,
                    ),
                ],
                overall_confidence=0.9,
            ),
        ).model_dump()

    def test_go_decision_aligned(self, monkeypatch):
        """All requirements align → GO decision, correct counts."""
        from rfp_automation.agents import GoNoGoAgent

        llm_response = json.dumps({
            "strategic_fit_score": 8.0,
            "technical_feasibility_score": 9.0,
            "regulatory_risk_score": 2.0,
            "decision": "GO",
            "justification": "All requirements satisfied",
            "red_flags": [],
            "policy_violations": [],
            "requirement_mappings": [
                {
                    "requirement_id": "RFP-REQ-001",
                    "requirement_text": "Must have ISO 27001",
                    "source_section": "Security Requirements",
                    "mapping_status": "ALIGNS",
                    "matched_policy": "ISO 27001 certified",
                    "matched_policy_id": "POL-001",
                    "confidence": 0.95,
                    "reasoning": "Direct certification match",
                },
                {
                    "requirement_id": "RFP-REQ-002",
                    "requirement_text": "Data at rest encryption",
                    "source_section": "Security Requirements",
                    "mapping_status": "ALIGNS",
                    "matched_policy": "AES-256 encryption at rest",
                    "matched_policy_id": "POL-002",
                    "confidence": 0.90,
                    "reasoning": "Policy covers this",
                },
            ],
        })

        mock_mcp = type("MockMCP", (), {
            "query_rfp_all_chunks": lambda self, rfp_id, top_k=50: [],
            "get_extracted_policies": lambda self: [{"policy_text": "ISO 27001 certified", "policy_id": "POL-001"}],
            "query_knowledge": lambda self, q, top_k=10: [],
        })()

        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.MCPService", lambda: mock_mcp)
        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.llm_text_call", lambda prompt: llm_response)

        agent = GoNoGoAgent()
        result = agent.process(self._go_no_go_state())

        assert result["go_no_go_result"]["decision"] == "GO"
        assert result["go_no_go_result"]["aligned_count"] == 2
        assert result["go_no_go_result"]["violated_count"] == 0
        assert result["go_no_go_result"]["total_requirements"] == 2
        assert result["status"] == PipelineStatus.EXTRACTING_REQUIREMENTS.value

    def test_no_go_decision_violations(self, monkeypatch):
        """VIOLATES entries → NO_GO decision."""
        from rfp_automation.agents import GoNoGoAgent

        llm_response = json.dumps({
            "strategic_fit_score": 4.0,
            "technical_feasibility_score": 3.0,
            "regulatory_risk_score": 8.0,
            "decision": "NO_GO",
            "justification": "Critical policy violation",
            "red_flags": ["Cannot meet encryption requirement"],
            "policy_violations": ["Data must not leave premises"],
            "requirement_mappings": [
                {
                    "requirement_id": "RFP-REQ-001",
                    "requirement_text": "Cloud hosting required",
                    "source_section": "Infrastructure",
                    "mapping_status": "VIOLATES",
                    "matched_policy": "No cloud hosting allowed",
                    "matched_policy_id": "POL-010",
                    "confidence": 0.99,
                    "reasoning": "Direct contradiction",
                },
            ],
        })

        mock_mcp = type("MockMCP", (), {
            "query_rfp_all_chunks": lambda self, rfp_id, top_k=50: [],
            "get_extracted_policies": lambda self: [],
            "query_knowledge": lambda self, q, top_k=10: [],
        })()

        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.MCPService", lambda: mock_mcp)
        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.llm_text_call", lambda prompt: llm_response)

        agent = GoNoGoAgent()
        result = agent.process(self._go_no_go_state())

        assert result["go_no_go_result"]["decision"] == "NO_GO"
        assert result["go_no_go_result"]["violated_count"] == 1
        assert result["status"] == PipelineStatus.NO_GO.value

    def test_mixed_mapping_counts(self, monkeypatch):
        """Mixed ALIGNS/RISK/NO_MATCH → verify correct count breakdown."""
        from rfp_automation.agents import GoNoGoAgent

        llm_response = json.dumps({
            "strategic_fit_score": 7.0,
            "technical_feasibility_score": 6.0,
            "regulatory_risk_score": 4.0,
            "decision": "GO",
            "justification": "Mostly aligned",
            "red_flags": [],
            "policy_violations": [],
            "requirement_mappings": [
                {"requirement_id": "R1", "requirement_text": "A", "source_section": "S",
                 "mapping_status": "ALIGNS", "matched_policy": "P1", "matched_policy_id": "POL-001",
                 "confidence": 0.9, "reasoning": "match"},
                {"requirement_id": "R2", "requirement_text": "B", "source_section": "S",
                 "mapping_status": "RISK", "matched_policy": "P2", "matched_policy_id": "POL-002",
                 "confidence": 0.5, "reasoning": "partial"},
                {"requirement_id": "R3", "requirement_text": "C", "source_section": "S",
                 "mapping_status": "NO_MATCH", "matched_policy": "", "matched_policy_id": "",
                 "confidence": 0.0, "reasoning": "none found"},
                {"requirement_id": "R4", "requirement_text": "D", "source_section": "S",
                 "mapping_status": "ALIGNS", "matched_policy": "P3", "matched_policy_id": "POL-003",
                 "confidence": 0.85, "reasoning": "match"},
            ],
        })

        mock_mcp = type("MockMCP", (), {
            "query_rfp_all_chunks": lambda self, rfp_id, top_k=50: [],
            "get_extracted_policies": lambda self: [],
            "query_knowledge": lambda self, q, top_k=10: [],
        })()

        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.MCPService", lambda: mock_mcp)
        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.llm_text_call", lambda prompt: llm_response)

        agent = GoNoGoAgent()
        result = agent.process(self._go_no_go_state())

        r = result["go_no_go_result"]
        assert r["total_requirements"] == 4
        assert r["aligned_count"] == 2
        assert r["risk_count"] == 1
        assert r["no_match_count"] == 1
        assert r["violated_count"] == 0

    def test_mappings_fully_populated(self, monkeypatch):
        """Verify all RequirementMapping fields are present and typed correctly."""
        from rfp_automation.agents import GoNoGoAgent

        llm_response = json.dumps({
            "strategic_fit_score": 7.0,
            "technical_feasibility_score": 7.0,
            "regulatory_risk_score": 3.0,
            "decision": "GO",
            "justification": "OK",
            "red_flags": [],
            "policy_violations": [],
            "requirement_mappings": [
                {
                    "requirement_id": "RFP-REQ-001",
                    "requirement_text": "Need SOC 2 Type II",
                    "source_section": "Compliance",
                    "mapping_status": "ALIGNS",
                    "matched_policy": "SOC 2 Type II certified",
                    "matched_policy_id": "POL-005",
                    "confidence": 0.98,
                    "reasoning": "Direct cert match",
                },
            ],
        })

        mock_mcp = type("MockMCP", (), {
            "query_rfp_all_chunks": lambda self, rfp_id, top_k=50: [],
            "get_extracted_policies": lambda self: [],
            "query_knowledge": lambda self, q, top_k=10: [],
        })()

        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.MCPService", lambda: mock_mcp)
        monkeypatch.setattr("rfp_automation.agents.go_no_go_agent.llm_text_call", lambda prompt: llm_response)

        agent = GoNoGoAgent()
        result = agent.process(self._go_no_go_state())

        mapping = result["go_no_go_result"]["requirement_mappings"][0]
        assert mapping["requirement_id"] == "RFP-REQ-001"
        assert mapping["requirement_text"] == "Need SOC 2 Type II"
        assert mapping["mapping_status"] == "ALIGNS"
        assert mapping["matched_policy_id"] == "POL-005"
        assert isinstance(mapping["confidence"], float)
        assert mapping["confidence"] > 0.0

    def test_missing_rfp_id_raises(self):
        """No rfp_id in state → ValueError."""
        from rfp_automation.agents import GoNoGoAgent

        agent = GoNoGoAgent()
        state = RFPGraphState(
            status=PipelineStatus.GO_NO_GO,
        ).model_dump()
        with pytest.raises(ValueError, match="No rfp_id"):
            agent.process(state)


```

## File: `rfp_automation\tests\test_pipeline.py`

```python
"""
Tests: Full pipeline flow.

Pipeline should halt at A1 (FileNotFoundError for test path)
since we don't have a real file.
When a real Pinecone+file is available, A1 will pass and halt at A2 (not yet implemented).

Run with:
    pytest rfp_automation/tests/test_pipeline.py -v
"""

import pytest
from rfp_automation.orchestration.graph import run_pipeline


class TestPipelineHaltsAtUnimplemented:
    """Pipeline should halt at A1 (file not found) in test environment."""

    def test_pipeline_halts_at_a1_missing_file(self):
        with pytest.raises(Exception):
            run_pipeline(uploaded_file_path="/test/sample.pdf")

```

## File: `rfp_automation\tests\test_rules.py`

```python
"""
Tests: MCP Rule engines.

Run with:
    pytest rfp_automation/tests/test_rules.py -v
"""

import pytest
from rfp_automation.mcp.rules.policy_rules import PolicyRules
from rfp_automation.mcp.rules.validation_rules import ValidationRules
from rfp_automation.mcp.rules.commercial_rules import CommercialRules
from rfp_automation.mcp.rules.legal_rules import LegalRules


class TestPolicyRules:
    def test_all_certs_held(self):
        pr = PolicyRules()
        violations = pr.check_policy_rules(
            required_certs=["ISO 27001", "SOC 2"],
            held_certs={"ISO 27001": True, "SOC 2": True, "FedRAMP": True},
        )
        assert len(violations) == 0

    def test_missing_cert(self):
        pr = PolicyRules()
        violations = pr.check_policy_rules(
            required_certs=["ISO 27001", "FedRAMP"],
            held_certs={"ISO 27001": True},
        )
        assert len(violations) == 1
        assert violations[0]["rule"] == "certification_gap"
        assert "FedRAMP" in violations[0]["detail"]

    def test_contract_too_large(self):
        pr = PolicyRules()
        violations = pr.check_policy_rules(
            required_certs=[],
            held_certs={},
            contract_value=20_000_000,
        )
        # Should flag because default max is 10M
        contract_violations = [v for v in violations if v["rule"] == "contract_too_large"]
        assert len(contract_violations) == 1


class TestValidationRules:
    def test_clean_text_passes(self):
        vr = ValidationRules()
        violations = vr.check_validation_rules("We will deliver the solution on time.")
        assert len(violations) == 0

    def test_prohibited_phrase_flagged(self):
        vr = ValidationRules()
        violations = vr.check_validation_rules("We guarantee 100% uptime forever.")
        assert len(violations) > 0
        rules = [v["rule"] for v in violations]
        assert "prohibited_language" in rules

    def test_contradiction_detected(self):
        vr = ValidationRules()
        violations = vr.check_validation_rules(
            "We offer 24/7 support. Support is available during business hours only."
        )
        contradiction_violations = [v for v in violations if v["rule"] == "consistency_conflict"]
        assert len(contradiction_violations) > 0


class TestCommercialRules:
    def test_valid_pricing(self):
        cr = CommercialRules()
        violations = cr.validate_pricing(total_price=500_000)
        assert len(violations) == 0

    def test_exceeds_max_contract(self):
        cr = CommercialRules()
        violations = cr.validate_pricing(total_price=10_000_000)
        # Default max is 5M
        assert any(v["rule"] == "contract_value_exceeded" for v in violations)

    def test_margin_too_low(self):
        cr = CommercialRules()
        violations = cr.validate_pricing(total_price=100_000, total_cost=95_000)
        # 5% margin < 15% minimum
        assert any(v["rule"] == "margin_too_low" for v in violations)

    def test_healthy_margin(self):
        cr = CommercialRules()
        violations = cr.validate_pricing(total_price=100_000, total_cost=70_000)
        # 30% margin > 15% minimum
        margin_violations = [v for v in violations if v["rule"] == "margin_too_low"]
        assert len(margin_violations) == 0


class TestLegalRules:
    def test_clear_gate(self):
        lr = LegalRules()
        result = lr.evaluate_commercial_legal_gate(
            legal_decision="CONDITIONAL",
            legal_block_reasons=[],
            pricing_total=500_000,
        )
        assert result["gate_decision"] == "CLEAR"

    def test_blocked_gate(self):
        lr = LegalRules()
        result = lr.evaluate_commercial_legal_gate(
            legal_decision="BLOCKED",
            legal_block_reasons=["Unlimited liability clause"],
            pricing_total=500_000,
        )
        assert result["gate_decision"] == "BLOCK"

    def test_clause_scoring_auto_block(self):
        lr = LegalRules()
        result = lr.score_clause(
            "The contractor accepts unlimited liability for all damages."
        )
        assert result["blocked"] is True
        assert result["risk_level"] == "critical"

    def test_clause_scoring_clean(self):
        lr = LegalRules()
        result = lr.score_clause(
            "Standard limitation of liability applies per contract terms."
        )
        assert result["blocked"] is False
        assert result["risk_level"] == "low"

```

## File: `rfp_automation\tests\__init__.py`

```python

```

## File: `rfp_automation\utils\hashing.py`

```python
"""
Hashing utilities for document integrity and auditability.
"""

from __future__ import annotations

import hashlib


def sha256_hash(content: str | bytes) -> str:
    """Return the SHA-256 hex digest of the given content."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()

```

## File: `rfp_automation\utils\logger.py`

```python
"""Centralized logging configuration.
Call setup_logging() once at application startup.
"""

from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "DEBUG") -> None:
    """Configure structured logging for the pipeline with full debug output."""
    root = logging.getLogger()
    # Avoid duplicate handlers on repeated calls
    if root.handlers:
        return

    root.setLevel(getattr(logging, level))

    # Use a stream wrapper that can handle Unicode on Windows consoles
    import io
    stream = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    handler = logging.StreamHandler(stream)
    handler.setLevel(getattr(logging, level))

    formatter = logging.Formatter(
        fmt=(
            "\n%(asctime)s │ %(levelname)-8s │ %(name)s │ %(funcName)s:%(lineno)d\n"
            "  %(message)s"
        ),
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Quiet noisy libraries but keep our code at DEBUG
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("hpack").setLevel(logging.WARNING)
    logging.getLogger("langchain").setLevel(logging.INFO)
    logging.getLogger("langchain_core").setLevel(logging.INFO)
    logging.getLogger("langchain_groq").setLevel(logging.INFO)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("pinecone").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("transformers").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("fastapi").setLevel(logging.INFO)

```

## File: `rfp_automation\utils\__init__.py`

```python
from .logger import setup_logging
from .hashing import sha256_hash

__all__ = ["setup_logging", "sha256_hash"]

```

## File: `scripts\verify_output.txt`

> Error reading file: 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte

## File: `scripts\verify_pinecone.py`

```python
"""
Pinecone Verification Script
=============================
Inspects the Pinecone index to verify that vectors are stored correctly.

Usage:
    python scripts/verify_pinecone.py                  # full inspection
    python scripts/verify_pinecone.py --query "security requirements"
    python scripts/verify_pinecone.py --namespace RFP-ABC12345
    python scripts/verify_pinecone.py --query "cloud migration" --namespace RFP-ABC12345

Run from the project root.
"""

from __future__ import annotations

import argparse
import sys
import os
import inspect

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rfp_automation.config import get_settings

HR = "-" * 60
HR2 = "=" * 60


def _trunc(text: str, n: int = 120) -> str:
    return (text[:n] + "...") if len(text) > n else text


def _attr(obj, key, default=None):
    """Get attribute from either dict or object."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def verify_index(args: argparse.Namespace) -> None:
    settings = get_settings()

    print()
    print(HR2)
    print("  PINECONE VERIFICATION")
    print(HR2)
    print(f"  Index name  : {settings.pinecone_index_name}")
    print(f"  Cloud/Region: {settings.pinecone_cloud} / {settings.pinecone_region}")
    if len(settings.pinecone_api_key) > 4:
        print(f"  API key     : ****...{settings.pinecone_api_key[-4:]}")
    else:
        print("  API key     : (not set)")
    print(HR2)

    # 1. Connect
    try:
        from pinecone import Pinecone
        pc = Pinecone(api_key=settings.pinecone_api_key)
    except Exception as e:
        print(f"\n[ERROR] Failed to connect to Pinecone: {e}")
        return

    # 2. List indexes
    indexes = [idx.name for idx in pc.list_indexes()]
    print(f"\nAvailable indexes: {indexes}")

    if settings.pinecone_index_name not in indexes:
        print(f"\n[WARN] Index '{settings.pinecone_index_name}' does NOT exist yet.")
        print("  This is expected if no documents have been ingested.")
        return

    index = pc.Index(settings.pinecone_index_name)

    # 3. Index statistics
    print(f"\n{HR}")
    print("  INDEX STATISTICS")
    print(HR)

    stats = index.describe_index_stats()
    total = _attr(stats, "total_vector_count", 0)
    dimension = _attr(stats, "dimension", "?")
    namespaces_raw = _attr(stats, "namespaces", {})

    # Normalize namespaces to dict[str, dict]
    namespaces: dict = {}
    if isinstance(namespaces_raw, dict):
        for k, v in namespaces_raw.items():
            if isinstance(v, dict):
                namespaces[k] = v
            else:
                namespaces[k] = {"vector_count": _attr(v, "vector_count", 0)}
    elif hasattr(namespaces_raw, "__iter__"):
        for item in namespaces_raw:
            name = _attr(item, "name", str(item))
            namespaces[name] = {"vector_count": _attr(item, "vector_count", 0)}

    print(f"  Total vectors : {total:,}")
    print(f"  Dimension     : {dimension}")
    print(f"  Namespaces    : {len(namespaces)}")

    if namespaces:
        print()
        print(f"  {'Namespace':<40} {'Vectors':>8}")
        print(f"  {'-'*40} {'-'*8}")
        for ns_name in sorted(namespaces.keys()):
            ns_info = namespaces[ns_name]
            count = ns_info.get("vector_count", 0) if isinstance(ns_info, dict) else _attr(ns_info, "vector_count", 0)
            print(f"  {ns_name:<40} {count:>8,}")
    else:
        print("\n  (no namespaces -- index is empty)")

    if total == 0:
        print("\n[WARN] No vectors stored. Run the Intake Agent or knowledge loader first.")
        _check_data_flow()
        return

    # 4. Pick namespace
    target_ns = args.namespace
    if not target_ns and namespaces:
        target_ns = next(
            (ns for ns in sorted(namespaces.keys())),
            None,
        )

    # 5. Fetch sample vectors
    if target_ns:
        print(f"\n{HR}")
        print(f"  SAMPLE VECTORS  (namespace: {target_ns})")
        print(HR)

        try:
            listed = index.list(namespace=target_ns)
            vector_ids = []

            # Pinecone v5 list() yields pages — each page is a list of IDs.
            # Flatten all pages into a single list, then take the first 5.
            if hasattr(listed, "vectors"):
                vector_ids = [_attr(v, "id", str(v)) for v in listed.vectors]
            elif isinstance(listed, dict) and "vectors" in listed:
                vector_ids = [v["id"] for v in listed["vectors"]]
            elif hasattr(listed, "__iter__"):
                for item in listed:
                    if isinstance(item, str):
                        vector_ids.append(item)
                    elif isinstance(item, list):
                        # Page of IDs — flatten
                        vector_ids.extend(item)
                    elif hasattr(item, "id"):
                        vector_ids.append(item.id)
                    elif hasattr(item, "__iter__") and not isinstance(item, (str, bytes)):
                        # Iterable page (e.g. tuple)
                        vector_ids.extend(str(x) for x in item)
                    else:
                        vector_ids.append(str(item))
            vector_ids = vector_ids[:5]

            if vector_ids:
                print(f"  Sample IDs: {vector_ids}")
                fetched = index.fetch(ids=vector_ids, namespace=target_ns)
                vecs = _attr(fetched, "vectors", {})

                for vid in vector_ids:
                    vdata = vecs.get(vid) if isinstance(vecs, dict) else _attr(vecs, vid, None)
                    if vdata is None:
                        print(f"\n  [{vid}] -- not found in fetch")
                        continue

                    values = _attr(vdata, "values", [])
                    meta = _attr(vdata, "metadata", {})

                    print(f"\n  Vector: {vid}")
                    print(f"    dims={len(values)}  first_5={values[:5]}")

                    if meta:
                        meta_dict = meta if isinstance(meta, dict) else vars(meta)
                        for k, v in meta_dict.items():
                            val = _trunc(str(v), 100) if k == "text" else _trunc(str(v), 80)
                            print(f"    {k}: {val}")
            else:
                print("  (no vector IDs returned from list -- will verify via query)")
        except Exception as e:
            print(f"  [WARN] Could not list/fetch: {e}")
            print("  Will try query instead.")

    # 6. Query test
    query_text = args.query or "project requirements and deliverables"
    print(f"\n{HR}")
    print(f"  QUERY TEST")
    print(f"  Query: \"{query_text}\"")
    if target_ns:
        print(f"  Namespace: {target_ns}")
    print(HR)

    try:
        from rfp_automation.mcp.embeddings.embedding_model import EmbeddingModel
        embedder = EmbeddingModel()
        query_emb = embedder.embed_single(query_text)

        results = index.query(
            vector=query_emb,
            top_k=args.top_k,
            namespace=target_ns or "",
            include_metadata=True,
        )

        matches = _attr(results, "matches", [])
        if not matches:
            print("\n  [WARN] No matches returned.")
        else:
            print(f"\n  {len(matches)} results:\n")
            for i, m in enumerate(matches, 1):
                mid = _attr(m, "id", "?")
                score = _attr(m, "score", 0.0)
                meta = _attr(m, "metadata", {})
                meta_dict = meta if isinstance(meta, dict) else (vars(meta) if meta else {})
                text = meta_dict.get("text", "")

                print(f"  {i}. [{score:.4f}] {mid}")
                if text:
                    print(f"     text: {_trunc(text, 150)}")
                for k, v in meta_dict.items():
                    if k != "text":
                        print(f"     {k}: {_trunc(str(v), 80)}")
                print()
    except Exception as e:
        print(f"\n  [ERROR] Query failed: {e}")
        import traceback
        traceback.print_exc()

    # 7. Data flow check
    _check_data_flow()

    print(f"\n{HR2}")
    print("  VERIFICATION COMPLETE")
    print(f"{HR2}\n")


def _check_data_flow():
    """Check if store_rfp_chunks is implemented or still a stub."""
    print(f"\n{HR}")
    print("  DATA FLOW CHECK")
    print(HR)

    try:
        from rfp_automation.mcp.mcp_server import MCPService
        source = inspect.getsource(MCPService.store_rfp_chunks)
        if "TODO" in source:
            print("  [WARN] MCPService.store_rfp_chunks() is still a TODO stub.")
            print("    Structured chunks from the Intake Agent are logged but NOT")
            print("    persisted to Pinecone or MongoDB.")
            print()
            print("  Options to actually store data:")
            print("    1. Use store_rfp_document(rfp_id, raw_text) to embed raw text")
            print("    2. Implement store_rfp_chunks() to persist structured chunks")
        else:
            print("  [OK] MCPService.store_rfp_chunks() is implemented.")
    except Exception as e:
        print(f"  [ERROR] Could not inspect store_rfp_chunks: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify Pinecone storage")
    parser.add_argument("--query", "-q", default="", help="Test query text")
    parser.add_argument("--namespace", "-n", default="", help="Target namespace")
    parser.add_argument("--top-k", "-k", type=int, default=5, help="Query results (default: 5)")
    args = parser.parse_args()
    verify_index(args)

```

