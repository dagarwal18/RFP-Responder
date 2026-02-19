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
│       │    │  │ _internal/  │ │  ← embedding, chunking, vecDB  │
│       │    │  └─────────────┘ │                                 │
│       │    └──────────────────┘                                 │
│       │                                                         │
│       ▼                                                         │
│  ┌──────────┐  ┌───────────┐  ┌───────────┐                    │
│  │ Storage  │  │  MongoDB  │  │   Redis   │                    │
│  │ (S3)     │  │  (state)  │  │  (queue)  │                    │
│  └──────────┘  └───────────┘  └───────────┘                    │
└─────────────────────────────────────────────────────────────────┘
        ▲  REST + WebSocket
        │
        ▼
┌─────────────────────────────────┐
│  FRONTEND (Vercel)              │
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

## Project Structure

```
RFP-Responder/
├── Documentation/
│   ├── project-description.md           # Full system spec
│   └── implementation-plan.md           # 13-week phased plan
│
├── src/                                 # ═══ BACKEND (all in one Docker) ═══
│   ├── main.py                          # CLI pipeline runner + API server launcher
│   │
│   ├── api/                             # ── HTTP Layer (frontend talks to this) ──
│   │   ├── app.py                       # FastAPI application factory
│   │   └── routes.py                    # REST endpoints (upload, status, approve)
│   │
│   ├── config/
│   │   └── settings.py                  # Centralised config (env vars / .env)
│   │
│   ├── models/                          # ── Data Layer ──
│   │   ├── enums.py                     # Status codes, decision types, categories
│   │   ├── state.py                     # RFPGraphState — the shared LangGraph state
│   │   └── schemas.py                   # Pydantic models for each agent's output
│   │
│   ├── agents/                          # ── Agent Layer (imports MCPService only) ──
│   │   ├── base.py                      # BaseAgent — mock/real switching, audit
│   │   ├── a1_intake.py → f2_submission.py  # 13 agents
│   │   └── ...
│   │
│   ├── mcp_server/                      # ── MCP Server (in-process module) ──
│   │   ├── server.py                    # MCPService facade — single entry point
│   │   ├── rfp_store.py                 # RFP Vector Store (embed / query)
│   │   ├── knowledge_base.py            # Company KB (capabilities, certs, pricing)
│   │   ├── rules_engine.py              # Policy / validation / legal rules
│   │   └── _internal/                   # Implementation details (agents NEVER import)
│   │       ├── embedding.py             # Sentence Transformers wrapper
│   │       ├── chunker.py              # Text splitting for vector embedding
│   │       └── vector_db.py            # Chroma / Pinecone client abstraction
│   │
│   ├── storage/                         # ── Persistence (orchestration only) ──
│   │   ├── file_storage.py              # Local / S3 file ops
│   │   └── state_repository.py          # State persistence (in-memory / MongoDB)
│   │
│   ├── document/                        # ── One-time parsing (A1 Intake only) ──
│   │   └── parser.py                    # PDF / DOCX text extraction
│   │
│   ├── orchestration/                   # ── LangGraph Pipeline ──
│   │   ├── graph.py                     # State machine (nodes + edges)
│   │   ├── routing.py                   # Conditional routing
│   │   └── callbacks.py                 # Lifecycle hooks
│   │
│   ├── prompts/
│   │   └── templates.py                 # All LLM prompt templates
│   │
│   └── tests/
│       ├── test_graph_flow.py           # End-to-end pipeline tests
│       ├── test_agents.py               # Per-agent unit tests
│       └── fixtures/
│           └── mock_data.py
│
├── frontend/                            # ═══ FRONTEND (Vercel — Phase 4) ═══
│   └── README.md                        # Planned stack + pages (not started)
│
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

# 3. Copy environment file
copy .env.example .env

# 4. Run the pipeline directly (mock mode — no LLM keys needed)
python -m src.main

# 5. Or start the API server (for frontend integration)
python -m src.main --serve      # → http://localhost:8000/docs

# 6. Run tests
pytest src/tests/ -v
```

## Pipeline Flow

```
A1 Intake → A2 Structuring → A3 Go/No-Go ──→ END (NO_GO)
                                    │ GO
                                    ▼
B1 Req Extraction → B2 Req Validation → C1 Architecture → C2 Writing → C3 Assembly
                                                                            │
                                                                            ▼
                                                                    D1 Validation
                                                                    │ REJECT (≤3x)
                                                                    ├──→ C3 (retry)
                                                                    │ PASS
                                                                    ▼
                                                            E1 Commercial ┐
                                                            E2 Legal      ┤ parallel
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

## Design: Mock → Real Agent Graduation

Every agent inherits from `BaseAgent` which provides:

1. **`mock_mode` toggle** — reads from `Settings.mock_mode` (default: `True`)
2. **`_mock_process(state)`** — returns hardcoded data (already implemented)
3. **`_real_process(state)`** — override this to connect LLM + MCP

**To graduate an agent from mock to real:**

```python
# In any agent file, e.g. agents/b1_requirements_extraction.py:
from src.mcp_server import MCPService

class RequirementsExtractionAgent(BaseAgent):
    name = AgentName.B1_REQUIREMENTS_EXTRACTION

    def _mock_process(self, state):
        ...  # existing mock (keep for testing)

    def _real_process(self, state):
        # 1. Query MCP RFP store for document sections
        mcp = MCPService()
        chunks = mcp.rfp_store.query("requirements", rfp_id=state.rfp_metadata.rfp_id)

        # 2. Call LLM with prompt template
        from src.prompts.templates import B1_REQUIREMENTS_PROMPT
        # ... LangChain chain here ...

        # 3. Parse structured output, write to state
        state.requirements = parsed_requirements
        return state
```

Then set `MOCK_MODE=false` in `.env` (or per-agent via constructor).

## Service Responsibilities

| Service | What it does | Mock behaviour |
|---|---|---|
| `MCPService` | Facade over all MCP layers | Routes to mock sub-services |
| `RFPVectorStore` | Embed + query incoming RFP chunks | Returns canned chunks |
| `KnowledgeBase` | Company capabilities, certs, pricing, legal templates | Returns hardcoded dictionaries |
| `RulesEngine` | Policy gate (A3), validation rules (D1), legal gate (E1+E2) | Simple rule checks |
| `FileStorageService` | Save/load files (local or S3) | Writes to `./storage/` |
| `StateRepository` | Persist graph state with versioning | In-memory dict |
| `DocumentParser` | PDF/DOCX → text | Returns placeholder text |
| `TextChunker` | Split text into overlapping chunks | Works normally |
| `EmbeddingService` | Text → vector embeddings | Random vectors |

## Governance Checkpoints

| Point | Agent | Condition | Outcome |
|---|---|---|---|
| Structuring confidence | A2 | confidence < 0.6 after 3 retries | Escalate to human |
| Go / No-Go | A3 | Policy violation or low scores | Pipeline END |
| Technical validation | D1 | REJECT | Loop to C3 (max 3x) |
| Legal veto | E2 | BLOCK (critical risk) | Pipeline END |
| Human approval | F1 | REJECT | Pipeline END |
