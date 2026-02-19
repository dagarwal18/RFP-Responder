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
│  ┌──────────┐  ┌───────────┐                                    │
│  │ Storage  │  │  MongoDB  │                                    │
│  │ (local)  │  │  (state)  │                                    │
│  └──────────┘  └───────────┘                                    │
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
│   │   ├── __init__.py                  # FastAPI app factory (create_app + app instance)
│   │   ├── routes.py                    # REST endpoints (upload, status, approve, list)
│   │   └── websocket.py                 # PipelineCallbacks (logging, future WebSocket)
│   │
│   ├── models/                          # ── Data Layer ──
│   │   ├── enums.py                     # Status codes, decision types, categories
│   │   ├── state.py                     # RFPGraphState — the shared LangGraph state
│   │   └── schemas.py                   # 20+ Pydantic models for each agent's output
│   │
│   ├── agents/                          # ── Agent Layer (imports MCPService only) ──
│   │   ├── base_agent.py                # BaseAgent — mock/real switching, audit
│   │   ├── intake_agent.py              # A1 — IntakeAgent
│   │   ├── structuring_agent.py         # A2 — StructuringAgent
│   │   ├── go_no_go_agent.py            # A3 — GoNoGoAgent
│   │   ├── requirement_extraction_agent.py  # B1 — RequirementsExtractionAgent
│   │   ├── requirement_validation_agent.py  # B2 — RequirementsValidationAgent
│   │   ├── architecture_agent.py        # C1 — ArchitecturePlanningAgent
│   │   ├── writing_agent.py             # C2 — RequirementWritingAgent
│   │   ├── narrative_agent.py           # C3 — NarrativeAssemblyAgent
│   │   ├── technical_validation_agent.py    # D1 — TechnicalValidationAgent
│   │   ├── commercial_agent.py          # E1 — CommercialAgent
│   │   ├── legal_agent.py               # E2 — LegalAgent
│   │   ├── final_readiness_agent.py     # F1 — FinalReadinessAgent
│   │   └── submission_agent.py          # F2 — SubmissionAgent
│   │
│   ├── mcp/                             # ── MCP Server (in-process module) ──
│   │   ├── mcp_server.py                # MCPService facade — single entry point
│   │   ├── vector_store/
│   │   │   ├── rfp_store.py             # RFP Vector Store (embed / query)
│   │   │   └── knowledge_store.py       # Company KB (capabilities, certs, pricing)
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
│   │       └── embedding_model.py       # Sentence Transformers wrapper
│   │
│   ├── services/                        # ── Business Services ──
│   │   ├── file_service.py              # Local / S3 file operations
│   │   ├── parsing_service.py           # PDF / DOCX text extraction + chunking
│   │   ├── storage_service.py           # Coordinates file + state persistence
│   │   └── audit_service.py             # Audit trail recording
│   │
│   ├── persistence/                     # ── Data Persistence ──
│   │   ├── mongo_client.py              # MongoDB connection wrapper
│   │   └── state_repository.py          # State persistence (in-memory / MongoDB)
│   │
│   ├── orchestration/                   # ── LangGraph Pipeline ──
│   │   ├── graph.py                     # State machine (nodes + edges + run_pipeline)
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
│       ├── test_agents.py               # Per-agent unit tests
│       ├── test_pipeline.py             # End-to-end pipeline tests
│       └── test_rules.py                # MCP rule layer tests
│
├── frontend/                            # ═══ FRONTEND (Vercel — not started) ═══
│   └── README.md                        # Planned stack + pages
│
├── storage/                             # Local file storage directory
├── requirements.txt
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

# 3. Copy environment file (optional — defaults work in mock mode)
copy .env.example .env

# 4. Run the pipeline directly (mock mode — no LLM keys needed)
python -m rfp_automation

# 5. Or start the API server (for frontend integration)
python -m rfp_automation --serve      # → http://localhost:8000/docs

# 6. Run tests
pytest rfp_automation/tests/ -v
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check (status, mock_mode, timestamp) |
| POST | `/api/rfp/upload` | Upload RFP file + run pipeline |
| GET | `/api/rfp/{rfp_id}/status` | Get pipeline status for an RFP |
| POST | `/api/rfp/{rfp_id}/approve` | Human approval gate action |
| GET | `/api/rfp/list` | List all pipeline runs |

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

## Design: Mock → Real Agent Graduation

Every agent inherits from `BaseAgent` which provides:

1. **`mock_mode` toggle** — reads from `get_settings()` in `rfp_automation/config.py` (default: `True`)
2. **`_mock_process(state)`** — returns hardcoded data (already implemented for all agents)
3. **`_real_process(state)`** — override this to connect LLM + MCP

**To graduate an agent from mock to real:**

```python
# In any agent file, e.g. rfp_automation/agents/requirement_extraction_agent.py:
from rfp_automation.mcp import MCPService

class RequirementsExtractionAgent(BaseAgent):
    name = AgentName.B1_REQUIREMENTS_EXTRACTION

    def _mock_process(self, state):
        ...  # existing mock (keep for testing)

    def _real_process(self, state):
        # 1. Query MCP RFP store for document sections
        mcp = MCPService()
        chunks = mcp.rfp_store.query("requirements", rfp_id=state.rfp_metadata.rfp_id)

        # 2. Load prompt template
        prompt_path = Path(__file__).parent.parent / "prompts" / "extraction_prompt.txt"
        prompt_template = prompt_path.read_text()

        # 3. Call LLM with prompt
        # ... LangChain chain here ...

        # 4. Parse structured output, write to state
        state.requirements = parsed_requirements
        return state
```

Then set `MOCK_MODE=false` in `.env` (or per-agent via constructor).

## Service Responsibilities

| Service | What it does | Mock behaviour |
|---|---|---|
| `MCPService` | Facade over all MCP layers | Routes to mock sub-services |
| `RFPVectorStore` | Embed + query incoming RFP chunks | Returns canned chunks |
| `KnowledgeStore` | Company capabilities, certs, pricing, legal templates | Returns hardcoded dictionaries |
| `PolicyRules` | Hard disqualification rules (A3 gate) | Simple rule checks |
| `ValidationRules` | Prohibited language + SLA checks (D1 gate) | Pattern matching |
| `CommercialRules` | Pricing margin validation | Threshold checks |
| `LegalRules` | Combined E1+E2 gate decision | Decision evaluation |
| `FileService` | Save/load files (local or S3) | Writes to `./storage/` |
| `ParsingService` | PDF/DOCX → text + chunking | Static methods |
| `StorageService` | Coordinate file + state persistence | Via FileService + StateRepository |
| `AuditService` | Record audit trail entries | In-memory list |
| `StateRepository` | Persist graph state with versioning | In-memory dict |
| `EmbeddingModel` | Text → vector embeddings | Random 384-dim vectors |

## Governance Checkpoints

| Point | Agent | Condition | Outcome |
|---|---|---|---|
| Structuring confidence | A2 | confidence < 0.6 after 3 retries | Escalate to human |
| Go / No-Go | A3 | Policy violation or low scores | Pipeline END |
| Technical validation | D1 | REJECT | Loop to C3 (max 3x) |
| Legal veto | E2 | BLOCK (critical risk) | Pipeline END |
| Human approval | F1 | REJECT | Pipeline END |
