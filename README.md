# RFP Response Automation System

A multi-agent AI system that automates end-to-end RFP (Request for Proposal) responses using a LangGraph state machine with built-in governance controls.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        BACKEND (FastAPI)                         │
│                                                                 │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────────────┐    │
│  │ FastAPI   │──▶│ Orchestration│──▶│      13 Agents       │    │
│  │ (API)     │   │ (LangGraph)  │   │ (A1→A2→A3→...→F2)   │    │
│  └──────────┘   └──────────────┘   └─────────┬────────────┘    │
│       │                                       │                 │
│       │              ┌────────────────────────┘                 │
│       │              ▼                                          │
│       │    ┌──────────────────┐                                 │
│       │    │   MCP Server     │  ← in-process module            │
│       │    │   (MCPService)   │                                 │
│       │    │  ┌─────────────┐ │                                 │
│       │    │  │ RFP Store   │ │  ← Pinecone vectors            │
│       │    │  │ KB Store    │ │  ← Pinecone + MongoDB           │
│       │    │  │ Rules       │ │  ← Policy/validation/legal      │
│       │    │  │ Embeddings  │ │  ← all-MiniLM-L6-v2             │
│       │    │  └─────────────┘ │                                 │
│       │    └──────────────────┘                                 │
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
│  FRONTEND (served at /)         │
│  Vanilla JS single-page app    │
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
| LLM | Groq Cloud (`llama-4-maverick-17b-128e-instruct`) via `langchain-groq` |
| VLM | HuggingFace Inference API (`Qwen/Qwen3-VL-8B-Instruct`) |
| Orchestration | LangGraph state machine (17 nodes, 5 conditional edges) |
| Vector DB | Pinecone Serverless (AWS us-east-1, cosine similarity) |
| Embeddings | Sentence Transformers (`all-MiniLM-L6-v2`, 384 dims) |
| Structured DB | MongoDB (company config, certs, pricing, legal) |
| API | FastAPI + uvicorn |
| Real-time | WebSocket via `PipelineProgress` singleton |
| Parsing | PyMuPDF (PDF), python-docx (DOCX) |
| Config | pydantic-settings (secrets in `.env`, params in `config.py`) |

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
# Edit .env — required keys: GROQ_API_KEY, HUGGINGFACE_API_KEY, PINECONE_API_KEY, MONGODB_URI

# 4. Start the API server
uvicorn rfp_automation.api:app --reload    # → http://localhost:8000

# 5. Or run the pipeline directly on a file
python -m rfp_automation "example_docs/Telecom RFP Document.pdf"

# 6. Run tests
pytest rfp_automation/tests/ -v
```

### Environment Variables (`.env`)

Only secrets go in `.env` — all model names, thresholds, and behavior params are hardcoded in `config.py`.

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | Groq Cloud API key (LLM) |
| `HUGGINGFACE_API_KEY` | Yes | HuggingFace API key (VLM table extraction) |
| `PINECONE_API_KEY` | Yes | Pinecone API key |
| `MONGODB_URI` | No (default: `mongodb://localhost:27017`) | MongoDB connection string |

## API Endpoints

### RFP Pipeline (`/api/rfp`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/rfp/upload` | Upload RFP → start pipeline → return `rfp_id` |
| GET | `/api/rfp/{rfp_id}/status` | Poll pipeline status + agent outputs |
| POST | `/api/rfp/{rfp_id}/approve` | Human approval gate (APPROVE / REJECT) |
| GET | `/api/rfp/list` | List all pipeline runs (in-memory + checkpointed) |
| GET | `/api/rfp/{rfp_id}/checkpoints` | List available agent checkpoints |
| DELETE | `/api/rfp/{rfp_id}/checkpoints` | Clear checkpoints for full re-run |
| POST | `/api/rfp/{rfp_id}/rerun?start_from=agent` | Re-run from a specific agent |
| GET | `/api/rfp/{rfp_id}/requirements` | Get extracted requirements + validation |
| GET | `/api/rfp/{rfp_id}/mappings` | Get A3 requirement-to-policy mappings |
| GET | `/api/rfp/{rfp_id}/debug` | Debug view of pipeline result keys |
| WS | `/api/rfp/ws/{rfp_id}` | Real-time progress events |
| GET | `/health` | Health check |

### Knowledge Base (`/api/knowledge`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/knowledge/upload` | Upload company doc → auto-classify → embed + extract policies |
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
| A1 IntakeAgent | ✅ | PDF parsing, HuggingFace VLM table extraction, Pinecone embedding |
| A2 StructuringAgent | ✅ | LLM section classification (6 categories) with retry loop |
| A3 GoNoGoAgent | ✅ | Policy rules + LLM risk scoring + requirement mapping |
| B1 RequirementsExtractionAgent | ✅ | Two-layer extraction (rule-based + LLM) + 3-tier dedup |
| B2 RequirementsValidationAgent | ✅ | Grounded refinement with hallucination guards |
| C1 ArchitecturePlanningAgent | ✅ | Programmatic gap-fill + auto-split overloaded sections (≤20 reqs) |
| C2 RequirementWritingAgent | ✅ | Token budgeting + RFP metadata injection + 3-tier coverage matrix |
| C3 NarrativeAssemblyAgent | ✅ | LLM exec summary + transitions, split-section reassembly, coverage appendix |
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
| `test_agents.py` | Per-agent unit tests |
| `test_pipeline.py` | End-to-end pipeline tests |
| `test_rules.py` | MCP rule layer tests (policy, validation, commercial, legal) |
| `test_api.py` | API endpoint tests |
| `test_extraction_overhaul.py` | B1 extraction overhaul validation |
| `test_obligation_detector.py` | Obligation detection pattern tests |
| `test_quality_fixes.py` | C2 quality fix verification |
| `test_stage4.py` | Stage 4 integration tests |

## Documentation

- **[Documentation/project-description.md](Documentation/project-description.md)** — Full system spec with agent descriptions, state schema, configuration reference
- **[Documentation/implementation-plan.md](Documentation/implementation-plan.md)** — Current status, C3 design, remaining agent plans
