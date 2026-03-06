# RFP Response Automation System

A multi-agent AI system that automates end-to-end RFP (Request for Proposal) responses using a LangGraph state machine with built-in governance controls.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        BACKEND (FastAPI)                        │
│                                                                 │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────────────┐     │
│  │ FastAPI  │──▶│ Orchestration│──▶│      13 Agents      │     │
│  │ (API)    │   │ (LangGraph)  │   │ (A1→A2→A3→...→F2)    │     │
│  └──────────┘   └──────────────┘   └─────────┬────────────┘     │
│       │                                      │                  │
│       │              ┌───────────────────────┘                  │
│       │              ▼                                          │
│       │    ┌──────────────────┐                                 │
│       │    │   MCP Server     │  ← in-process module            │
│       │    │   (MCPService)   │                                 │
│       │    │  ┌─────────────┐ │                                 │
│       │    │  │ RFP Store   │ │  ← Pinecone vectors             │
│       │    │  │ KB Store    │ │  ← Pinecone + MongoDB           │
│       │    │  │ Rules       │ │  ← Policy/validation/legal      │
│       │    │  │ Embeddings  │ │  ← all-MiniLM-L6-v2             │
│       │    │  └─────────────┘ │                                 │
│       │    └──────────────────┘                                 │
│       ▼                                                         │
│  ┌──────────┐  ┌───────────┐  ┌───────────┐                     │
│  │ Storage  │  │  MongoDB  │  │ Pinecone  │                     │
│  │ (local)  │  │  (config) │  │ (vectors) │                     │
│  └──────────┘  └───────────┘  └───────────┘                     │
└─────────────────────────────────────────────────────────────────┘
        ▲  REST + WebSocket
        │
        ▼
┌─────────────────────────────────┐
│  FRONTEND (served at /)         │
│  Vanilla JS single-page app     │
│                                 │
│  • Upload    — drag & drop      │
│  • Dashboard — list all RFPs    │
│  • Status    — live progress    │
│  • KB Mgmt   — knowledge base   │
└─────────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Groq Cloud (`llama-3.3-70b-versatile`) via `langchain-groq` |
| Vision/Tables | Groq VLM (`llama-4-scout-17b-16e-instruct`) |
| Orchestration | LangGraph state machine (17 nodes, 5 conditional edges) |
| Vector DB | Pinecone Serverless (AWS us-east-1, cosine similarity) |
| Embeddings | Sentence Transformers (`all-MiniLM-L6-v2`, 384 dims) |
| Structured DB | MongoDB (company config, certs, pricing, legal) |
| API | FastAPI + uvicorn |
| Real-time | WebSocket via `PipelineProgress` singleton |
| Parsing | PyMuPDF (PDF), python-docx (DOCX) |
| Config | pydantic-settings (`.env`) |

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
# Edit .env — required keys: GROQ_API_KEY, PINECONE_API_KEY, MONGODB_URI

# 4. Start the API server
uvicorn rfp_automation.api:app --reload    # → http://localhost:8000

# 5. Or run the pipeline directly on a file
python -m rfp_automation "example_docs/Telecom RFP Document.pdf"

# 6. Run tests
pytest rfp_automation/tests/ -v
```

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | Yes | — | Groq Cloud API key |
| `PINECONE_API_KEY` | Yes | — | Pinecone API key |
| `MONGODB_URI` | Yes | `mongodb://localhost:27017` | MongoDB connection string |
| `LLM_MODEL` | No | `llama-3.3-70b-versatile` | Groq model name |
| `PINECONE_INDEX_NAME` | No | `rfp-automation` | Pinecone index name |
| `EMBEDDING_MODEL` | No | `all-MiniLM-L6-v2` | Sentence Transformers model |
| `LOG_LEVEL` | No | `INFO` | Python logging level |

## API Endpoints

### RFP Pipeline (`/api/rfp`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/rfp/upload` | Upload RFP → start pipeline → return `rfp_id` |
| GET | `/api/rfp/{rfp_id}/status` | Poll pipeline status + agent outputs |
| POST | `/api/rfp/{rfp_id}/approve` | Human approval gate (APPROVE / REJECT) |
| GET | `/api/rfp/list` | List all pipeline runs |
| WS | `/api/rfp/ws/{rfp_id}` | Real-time progress events |
| GET | `/health` | Health check |

### Knowledge Base (`/api/knowledge`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/knowledge/upload` | Upload company doc → classify → embed |
| GET | `/api/knowledge/status` | Pinecone + MongoDB stats |
| POST | `/api/knowledge/query` | Semantic query with `doc_type` filter |
| POST | `/api/knowledge/seed` | Seed KB from JSON files |
| GET | `/api/knowledge/files` | List uploaded KB documents |
| GET | `/api/knowledge/policies` | List company policies |

Swagger UI at `/docs`. Dashboard at `/`.

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
                            E1 Commercial ┐
                            E2 Legal      ┤ (parallel)
                                          │
                                    BLOCK → END
                                    CLEAR ↓
                                    F1 Readiness
                                        │
                                Human Approval Gate
                                    REJECT → END
                                    APPROVE ↓
                                    F2 Submission → END
```

## Agent Status

| Agent | Status | Key Feature |
|---|---|---|
| A1 IntakeAgent | ✅ | PDF parsing, VLM tables, Pinecone embedding |
| A2 StructuringAgent | ✅ | LLM section classification with retry loop |
| A3 GoNoGoAgent | ✅ | Policy rules + LLM risk scoring |
| B1 RequirementsExtractionAgent | ✅ | Two-layer extraction + 3-tier dedup |
| B2 RequirementsValidationAgent | ✅ | Grounded refinement with hallucination guards |
| C1 ArchitecturePlanningAgent | ✅ | Auto-split overloaded sections (max 20 reqs) |
| C2 RequirementWritingAgent | ✅ | Token budgeting + 3-tier coverage matrix |
| C3 NarrativeAssemblyAgent | 🔜 | Next to implement |
| D1 TechnicalValidationAgent | ⬜ | Stub |
| E1 CommercialAgent | ⬜ | Stub |
| E2 LegalAgent | ⬜ | Stub |
| F1 FinalReadinessAgent | ⬜ | Stub |
| F2 SubmissionAgent | ⬜ | Stub |

## Governance Checkpoints

| Point | Agent | Condition | Outcome |
|---|---|---|---|
| Structuring confidence | A2 | confidence < 0.6 after 3 retries | Escalate → END |
| Go / No-Go | A3 | Policy violation or low scores | NO_GO → END |
| Technical validation | D1 | REJECT | Loop to C3 (max 3x) → escalate |
| Legal veto | E2 | BLOCK (critical risk) | LEGAL_BLOCK → END |
| Human approval | F1 | REJECT | REJECTED → END |

## Tests

```bash
pytest rfp_automation/tests/ -v
```

| Test File | Coverage |
|---|---|
| `test_agents.py` | A1 validation, stub agent behavior |
| `test_pipeline.py` | Pipeline halts on missing input |
| `test_rules.py` | All 4 MCP rule layers (11 tests) |

## Documentation

- **[Documentation/project-description.md](Documentation/project-description.md)** — Full system specification with agent descriptions
- **[Documentation/implementation-plan.md](Documentation/implementation-plan.md)** — Current status, next steps, remaining agent plans
