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
| RFP Vector Store | `mcp/vector_store/rfp_store.py` | A2, A3, B1, C1, C2, D1, E2 |
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
| Orchestration | LangGraph (state machine) |
| LLM | OpenAI or Anthropic API (configurable via `llm_provider` setting) |
| Database | MongoDB (state persistence, audit trail) |
| File Storage | Local filesystem (default) or AWS S3 (configurable) |
| MCP Server | In-process module — vector stores + rule layers + schemas |
| Vector Embeddings | Sentence Transformers (`all-MiniLM-L6-v2`) |
| Vector Database | ChromaDB (within MCP server) |
| State Models | Pydantic v2 (type safety + validation) |
| Configuration | pydantic-settings (`.env` file support) |
| Frontend | Next.js, TypeScript, Tailwind CSS, WebSocket (planned — not yet started) |
| File Parsing | PyMuPDF (PDF), python-docx (DOCX) |

---

## Project Structure

```
rfp_automation/
├── __init__.py                      # Package marker
├── __main__.py                      # CLI entry: python -m rfp_automation
├── config.py                        # Centralised settings (pydantic-settings + .env)
├── main.py                          # run() and serve() entry points
│
├── agents/                          # One file per agent (13 agents + base)
│   ├── base_agent.py                # BaseAgent — mock/real switching, audit
│   ├── intake_agent.py              # A1 — file intake + metadata extraction
│   ├── structuring_agent.py         # A2 — RFP section classification
│   ├── go_no_go_agent.py            # A3 — bid/no-bid decision
│   ├── requirement_extraction_agent.py  # B1 — extract requirements
│   ├── requirement_validation_agent.py  # B2 — validate requirements
│   ├── architecture_agent.py        # C1 — response architecture planning
│   ├── writing_agent.py             # C2 — section-level response writing
│   ├── narrative_agent.py           # C3 — narrative assembly
│   ├── technical_validation_agent.py    # D1 — technical validation
│   ├── commercial_agent.py          # E1 — commercial pricing
│   ├── legal_agent.py               # E2 — legal review
│   ├── final_readiness_agent.py     # F1 — final readiness + approval gate
│   └── submission_agent.py          # F2 — submission + archival
│
├── orchestration/                   # LangGraph state machine
│   ├── graph.py                     # StateGraph builder + run_pipeline()
│   └── transitions.py              # Conditional routing functions (5 decision points)
│
├── mcp/                             # MCP server — in-process module
│   ├── mcp_server.py                # MCPService facade — single entry point for agents
│   ├── vector_store/
│   │   ├── rfp_store.py             # RFP Vector Store (embed / query)
│   │   └── knowledge_store.py       # Company KB (capabilities, certs, pricing)
│   ├── rules/
│   │   ├── policy_rules.py          # Hard disqualification rules (A3)
│   │   ├── validation_rules.py      # Over-promise / prohibited language checks (D1)
│   │   ├── commercial_rules.py      # Pricing validation (E1)
│   │   └── legal_rules.py           # Commercial+Legal gate logic (E1+E2)
│   ├── schema/
│   │   ├── capability_schema.py     # Capability model
│   │   ├── pricing_schema.py        # PricingParameters model
│   │   └── requirement_schema.py    # ExtractedRequirement model
│   └── embeddings/
│       └── embedding_model.py       # Sentence Transformers wrapper (mock: random vectors)
│
├── models/                          # Pydantic data models
│   ├── enums.py                     # All enum values (PipelineStatus, decisions, categories)
│   ├── state.py                     # RFPGraphState — the shared LangGraph state
│   └── schemas.py                   # 20+ sub-models (RFPMetadata, Requirement, etc.)
│
├── services/                        # Business services
│   ├── file_service.py              # Local / S3 file operations
│   ├── parsing_service.py           # PDF / DOCX text extraction + chunking
│   ├── storage_service.py           # Coordinates file + state persistence
│   └── audit_service.py             # Audit trail recording
│
├── persistence/                     # Data persistence layer
│   ├── mongo_client.py              # MongoDB connection wrapper
│   └── state_repository.py          # State persistence (in-memory / MongoDB)
│
├── api/                             # HTTP layer (FastAPI)
│   ├── __init__.py                  # create_app() factory + app instance
│   ├── routes.py                    # REST endpoints (upload, status, approve, list)
│   └── websocket.py                 # PipelineCallbacks (logging, future WebSocket)
│
├── prompts/                         # LLM prompt templates (.txt files)
│   ├── extraction_prompt.txt        # B1 requirement extraction
│   ├── architecture_prompt.txt      # C1 architecture planning
│   ├── go_no_go_prompt.txt          # A3 go/no-go analysis
│   ├── structuring_prompt.txt       # A2 section classification
│   ├── legal_prompt.txt             # E2 legal review
│   ├── writing_prompt.txt           # C2 response writing
│   └── validation_prompt.txt        # D1 technical validation
│
├── utils/                           # Shared utilities
│   ├── logger.py                    # Logging setup
│   └── hashing.py                   # SHA-256 hashing
│
└── tests/                           # Test suite
    ├── test_agents.py               # Per-agent unit tests (9 agents)
    ├── test_pipeline.py             # End-to-end pipeline tests
    └── test_rules.py                # MCP rule layer tests
```

---

## Pipeline: 12-Stage Flow

### Stage 1 — Intake (A1)
The uploaded RFP file is validated, text is extracted, and the document is immediately chunked and embedded into the MCP server's RFP vector store. Basic metadata (client, deadline, RFP number) is written to state. From this point forward, no agent reads the raw file — all RFP retrieval goes through MCP.

### Stage 2 — RFP Structuring (A2)
Queries the MCP RFP store to retrieve and classify document sections (scope, technical requirements, compliance, legal terms, submission instructions, evaluation criteria). Assigns a confidence score to the structure. If confidence is too low (< 0.6), it re-queries with a different chunking strategy and retries up to 3 times before escalating for human review.

### Stage 3 — Go / No-Go Analysis (A3)
Retrieves the scope and compliance sections from the MCP RFP store. Queries the MCP knowledge store for company capabilities, certifications held, and contract history. Runs an LLM assessment scoring strategic fit, technical feasibility, and regulatory risk. The MCP policy rules layer then applies hard disqualification checks (certifications not held, geography restrictions, contract value limits). A violation at either layer produces **NO_GO → END**.

### Stage 4 — Requirements Extraction (B1)
Queries the MCP RFP store section by section to extract every requirement. Each requirement is classified by type (mandatory / optional), category (technical, functional, security, compliance, commercial, operational), and impact level (critical, high, medium, low). Results are written to state as a structured list with unique IDs (REQ-001, REQ-002, etc.).

### Stage 5 — Requirements Validation (B2)
Cross-checks the extracted requirements list for completeness, duplicate detection, and contradictions. Ambiguous mandatory requirements are flagged. Issues do not block the pipeline but are passed forward as context to downstream agents.

### Stage 6 — Architecture Planning (C1)
Queries both MCP stores simultaneously — the RFP store for requirement groupings and the knowledge store for relevant company solutions. Groups requirements into 5–8 logical response sections and maps each section to specific company capabilities. Validates that every mandatory requirement appears in the plan before proceeding.

### Stage 7 — Requirement Writing (C2)
For each response section, retrieves the relevant requirements from the MCP RFP store and matching capability evidence from the MCP knowledge store. Generates a full prose response per section, referencing real products, certifications, and past work. Builds a requirement coverage matrix tracking which requirements are addressed and where.

### Stage 8 — Narrative Assembly (C3)
Combines all section responses into a cohesive proposal document. Adds an executive summary, section transitions, and a requirement coverage appendix. Validates that no placeholder text remains and that the document is within submission length limits.

### Stage 9 — Technical Validation (D1)
Retrieves original requirements from the MCP RFP store and checks the assembled proposal against them. Runs four checks: coverage completeness, alignment, realism, and consistency. The MCP validation rules layer applies hard checks for over-promised SLAs and prohibited language (e.g., "guarantee 100% uptime", "unlimited", "zero risk"). **REJECT** loops back to C3 Narrative Assembly with specific feedback. After 3 rejections the pipeline escalates to human review.

### Stage 10 — Commercial + Legal Review (E1 + E2)
Both agents run in the `commercial_legal_parallel` node (sequential execution currently; true parallel via LangGraph `Send()` planned for production).

- **E1 Commercial** queries the MCP knowledge store for pricing rules and applies the formula (base cost + per-requirement cost × complexity multiplier + risk margin). Generates the commercial response section with a `PricingBreakdown`.
- **E2 Legal** queries the MCP RFP store for contract clauses and the MCP knowledge store for the company's legal templates and certifications. Classifies each clause by risk level (LOW / MEDIUM / HIGH / CRITICAL). Any CRITICAL risk produces a **BLOCK**.

The MCP legal rules layer combines both outputs via `evaluate_commercial_legal_gate()`. A BLOCK from E2 always terminates the pipeline regardless of E1's output — **END – Legal Block**.

### Stage 11 — Final Readiness (F1)
Compiles the full approval package: proposal document, pricing breakdown, legal risk register, requirement coverage matrix, and a one-page decision brief for leadership. Triggers the **Human Approval Gate** — in mock mode, this auto-approves. **REJECT** at this gate ends the pipeline.

### Stage 12 — Submission & Archive (F2)
Applies final formatting, packages all deliverables, and submits. Archives everything with SHA-256 file hashes logged for auditability. Final state is written as **SUBMITTED**.

---

## Data Flow Diagram

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
C2 Requirement Writing ◄─────────── MCP: RFP Store + Knowledge Store
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

The shared graph state object (`RFPGraphState` in `rfp_automation/models/state.py`) contains:

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

All settings are managed via `rfp_automation/config.py` using `pydantic-settings`. Configuration can be set via environment variables or a `.env` file.

| Setting | Default | Description |
|---|---|---|
| `mock_mode` | `True` | Toggle mock/real agent execution |
| `llm_provider` | `openai` | LLM provider (openai / anthropic) |
| `llm_model` | `gpt-4o` | Model name |
| `llm_temperature` | `0.2` | Generation temperature |
| `llm_max_tokens` | `4096` | Max tokens per call |
| `storage_backend` | `local` | File storage backend (local / s3) |
| `local_storage_path` | `./storage` | Local file storage directory |
| `vector_db_backend` | `chroma` | Vector database backend |
| `embedding_model` | `all-MiniLM-L6-v2` | Sentence transformer model |
| `max_validation_retries` | `3` | D1 validation retry limit |
| `max_structuring_retries` | `3` | A2 structuring retry limit |
| `approval_timeout_hours` | `48` | Human approval timeout |
