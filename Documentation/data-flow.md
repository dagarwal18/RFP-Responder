# Data Flow & Pipeline Walkthrough

A complete trace of how data moves through the backend — file by file, function by function — from the moment a user uploads an RFP to the final SUBMITTED status.

---

## Table of Contents

1. [Entry Points — How a Pipeline Starts](#1-entry-points--how-a-pipeline-starts)
2. [The State Object — What Flows Through the Pipeline](#2-the-state-object--what-flows-through-the-pipeline)
3. [How a Single Agent Executes](#3-how-a-single-agent-executes)
4. [Full Pipeline Walkthrough (File by File)](#4-full-pipeline-walkthrough-file-by-file)
5. [Governance & Branching in Detail](#5-governance--branching-in-detail)
6. [Where Each File Comes Into Play](#6-where-each-file-comes-into-play)
7. [State Snapshot at Each Stage](#7-state-snapshot-at-each-stage)

---

## 1. Entry Points — How a Pipeline Starts

There are two ways a pipeline run begins. Both converge on the same function.

### Path A: CLI (Direct Run)

```
User runs: python -m src.main
```

| Step | File | What Happens |
|---|---|---|
| 1 | `src/main.py` → `run()` | Sets up logging, calls `run_pipeline()` |
| 2 | `src/orchestration/graph.py` → `run_pipeline()` | Builds the LangGraph, creates initial state dict, calls `compiled.invoke(state)` |

### Path B: API Server (Frontend)

```
Frontend sends: POST /api/rfp/upload  (with file attached)
```

| Step | File | What Happens |
|---|---|---|
| 1 | `src/api/app.py` → `create_app()` | FastAPI app is already running (started via `python -m src.main --serve`) |
| 2 | `src/api/routes.py` → `upload_rfp()` | Receives the file, saves to `./storage/uploads/`, generates an RFP ID |
| 3 | `src/api/routes.py` → `upload_rfp()` | Calls `run_pipeline(uploaded_file_path=local_path)` — **same function as CLI** |
| 4 | `src/orchestration/graph.py` → `run_pipeline()` | Builds the LangGraph, creates initial state dict, calls `compiled.invoke(state)` |

**Both paths converge here:**

```python
# src/orchestration/graph.py — run_pipeline()
compiled = build_graph()         # ← builds the LangGraph state machine
state = {"uploaded_file_path": "path/to/file", "status": "RECEIVED"}
final_state = compiled.invoke(state)   # ← executes the entire pipeline
```

---

## 2. The State Object — What Flows Through the Pipeline

LangGraph passes a **single dict** through every node. This dict is defined by:

- `src/models/state.py` → `RFPGraphState` (Pydantic model with all fields)
- `src/models/schemas.py` → sub-models (`RFPMetadata`, `Requirement`, `GoNoGoResult`, etc.)
- `src/models/enums.py` → all enum values (`PipelineStatus`, `GoNoGoDecision`, etc.)

**The state starts nearly empty:**

```python
{
    "uploaded_file_path": "/path/to/rfp.pdf",
    "status": "RECEIVED",
    # everything else is default/empty
}
```

**Each agent reads the dict, adds its owned fields, and returns the dict.**
LangGraph merges the returned dict back into the shared state automatically.

### Ownership Rules

Every field in the state is "owned" by exactly one agent. Agents can READ any field but should only WRITE to their owned fields:

| State Field | Owner | Type |
|---|---|---|
| `status` | Every agent updates this | `PipelineStatus` enum |
| `current_agent` | Set by `BaseAgent.process()` | `str` |
| `rfp_metadata` | A1 Intake | `RFPMetadata` |
| `uploaded_file_path` | Initial input | `str` |
| `raw_text` | A1 Intake | `str` |
| `structuring_result` | A2 Structuring | `StructuringResult` |
| `go_no_go_result` | A3 Go/No-Go | `GoNoGoResult` |
| `requirements` | B1 Extraction | `list[Requirement]` |
| `requirements_validation` | B2 Validation | `RequirementsValidationResult` |
| `architecture_plan` | C1 Architecture | `ArchitecturePlan` |
| `writing_result` | C2 Writing | `WritingResult` |
| `assembled_proposal` | C3 Assembly | `AssembledProposal` |
| `technical_validation` | D1 Validation | `TechnicalValidationResult` |
| `commercial_result` | E1 Commercial | `CommercialResult` |
| `legal_result` | E2 Legal | `LegalResult` |
| `commercial_legal_gate` | Orchestration (fan-in) | `CommercialLegalGateResult` |
| `approval_package` | F1 Readiness | `ApprovalPackage` |
| `submission_record` | F2 Submission | `SubmissionRecord` |
| `audit_trail` | Every agent appends | `list[AuditEntry]` |

---

## 3. How a Single Agent Executes

Every agent call follows the same pattern. Understanding this once explains all 13 agents.

```
LangGraph calls:  agent.process(state_dict)
                        │
                        ▼
              ┌─ src/agents/base.py ── BaseAgent.process() ─┐
              │                                              │
              │  1. Hydrate: RFPGraphState(**state_dict)     │
              │  2. Set: state.current_agent = self.name     │
              │  3. Branch on mock_mode:                     │
              │       True  → self._mock_process(state)      │
              │       False → self._real_process(state)      │
              │  4. Append audit entry                       │
              │  5. Return: state.model_dump()  → dict       │
              │                                              │
              └──────────────────────────────────────────────┘
                        │
                        ▼
              LangGraph merges returned dict into shared state
```

### File involvement for a single agent call:

| File | Role |
|---|---|
| `src/agents/base.py` | `process()` — the entry point LangGraph calls |
| `src/agents/<agent>.py` | `_mock_process()` or `_real_process()` — the actual logic |
| `src/models/state.py` | `RFPGraphState` — hydrates dict → Pydantic, dumps back to dict |
| `src/models/schemas.py` | The sub-model the agent writes (e.g., `GoNoGoResult`) |
| `src/models/enums.py` | Enum values the agent sets (e.g., `GoNoGoDecision.GO`) |
| `src/config/settings.py` | `get_settings()` — provides `mock_mode` flag |

**When real mode is enabled**, agents will also use:

| File | Role |
|---|---|
| `src/mcp_server/server.py` | `MCPService` — the facade agents import |
| `src/mcp_server/rfp_store.py` | Query/embed RFP chunks |
| `src/mcp_server/knowledge_base.py` | Query company capabilities |
| `src/mcp_server/rules_engine.py` | Apply hard business rules |
| `src/prompts/templates.py` | LLM prompt for this agent |

---

## 4. Process Flow — File to File

How Python files call each other from server startup to pipeline completion.

### 4.1 Server Startup

```
python -m src.main --serve
│
▼
src/main.py                         ← entry point
│  reads --serve flag
│  calls serve()
│
▼
src/api/app.py                      ← creates the FastAPI app
│  create_app()
│  imports routes from src/api/routes.py
│  imports settings from src/config/settings.py
│  registers /health, /api/rfp/* route groups
│  returns FastAPI instance
│
▼
uvicorn starts listening on :8000
   routes defined in src/api/routes.py are now live
```

### 4.2 CLI Direct Run (no server)

```
python -m src.main
│
▼
src/main.py                         ← entry point
│  run()
│  calls run_pipeline() directly
│  ──────────────────────────────── jumps straight to 4.4
```

### 4.3 User Uploads a File (API path)

```
Frontend sends POST /api/rfp/upload with file
│
▼
src/api/routes.py                   ← upload_rfp()
│  1. generates RFP ID
│  2. saves file to ./storage/uploads/
│  3. calls run_pipeline(uploaded_file_path=...)
│
▼ ─── both CLI and API converge here ───
```

### 4.4 Pipeline Execution (the core)

```
src/orchestration/graph.py          ← run_pipeline()
│  build_graph():
│      instantiates 13 agents      ← src/agents/__init__.py  (imports all agent classes)
│      each agent __init__          ← src/config/settings.py  (reads mock_mode)
│      creates LangGraph StateGraph
│      wires edges + conditional    ← src/orchestration/routing.py  (5 routing functions)
│      compiles graph
│
│  compiled.invoke(state_dict)      ← LangGraph takes control, runs nodes in order
│
▼
For EACH agent node, LangGraph calls agent.process(state_dict):
│
│  src/agents/base.py               ← BaseAgent.process()
│  │  hydrates dict → RFPGraphState ← src/models/state.py
│  │  checks mock_mode              ← src/config/settings.py
│  │
│  ├─ if mock_mode=True:
│  │     src/agents/<agent>.py      ← _mock_process()  (hardcoded data)
│  │
│  ├─ if mock_mode=False:
│  │     src/agents/<agent>.py      ← _real_process()
│  │     │  queries MCP             ← src/mcp_server/server.py → rfp_store.py / knowledge_base.py / rules_engine.py
│  │     │  calls LLM with prompt   ← src/prompts/templates.py
│  │     │  (A1 only) parses file   ← src/document/parser.py
│  │
│  │  creates typed output          ← src/models/schemas.py  (RFPMetadata, GoNoGoResult, etc.)
│  │  uses enum values              ← src/models/enums.py    (PipelineStatus, GoNoGoDecision, etc.)
│  │  appends audit entry           ← src/models/state.py    (RFPGraphState.add_audit())
│  │  dumps state → dict            ← state.model_dump()
│  │
│  ▼
│  LangGraph merges returned dict back into shared state
│
│  At governance checkpoints, LangGraph calls a routing function:
│      src/orchestration/routing.py  ← decides next node (proceed / retry / terminate)
│          reads settings            ← src/config/settings.py (max retries)
│
│  ... repeats for each agent node ...
│
▼
compiled.invoke() returns final state dict
```

### 4.5 Result Returned

```
src/orchestration/graph.py          ← returns final_state dict
│
├─ CLI path:
│  src/main.py                      ← _print_summary(final_state)
│                                      prints to terminal and exits
│
├─ API path:
│  src/api/routes.py                ← stores final_state in _runs[rfp_id]
│                                      returns JSON {rfp_id, status, message} to frontend
│
│  Frontend can then:
│      GET /api/rfp/{id}/status     ← src/api/routes.py → get_rfp_status()
│      POST /api/rfp/{id}/approve   ← src/api/routes.py → approve_rfp()
│      GET /api/rfp/list            ← src/api/routes.py → list_rfps()
```

### 4.6 Agent Execution Order (happy path)

```
src/orchestration/graph.py executes these nodes in this order:
│
├── a1_intake.py ──────────────────── always ────────── a2_structuring.py
├── a2_structuring.py ── routing.py ── confidence ok? ── a3_go_no_go.py
├── a3_go_no_go.py ──── routing.py ── GO? ───────────── b1_requirements_extraction.py
├── b1_requirements_extraction.py ─── always ────────── b2_requirements_validation.py
├── b2_requirements_validation.py ─── always ────────── c1_architecture_planning.py
├── c1_architecture_planning.py ───── always ────────── c2_requirement_writing.py
├── c2_requirement_writing.py ─────── always ────────── c3_narrative_assembly.py
├── c3_narrative_assembly.py ──────── always ────────── d1_technical_validation.py
├── d1_technical_validation.py ── routing.py ── PASS? ── graph.py: commercial_legal_parallel()
│                                                           ├── e1_commercial.py
│                                                           ├── e2_legal.py
│                                                           └── fan-in gate
├── commercial_legal_parallel ── routing.py ── CLEAR? ── f1_final_readiness.py
├── f1_final_readiness.py ────── routing.py ── APPROVE? ── f2_submission.py
└── f2_submission.py ──────────────── END
```

---

## 5. Governance & Branching in Detail

All branching happens in `src/orchestration/routing.py`. The orchestration graph in `src/orchestration/graph.py` wires these routing functions as conditional edges.

```
                                  ┌── retry (confidence < 0.6, retries < max)
                         A2 ─────┤── escalate (confidence < 0.6, retries >= max) ──→ END
                                  └── proceed (confidence >= 0.6) ──→ A3

                                  ┌── NO_GO ──→ END
                         A3 ─────┤
                                  └── GO ──→ B1

                                  ┌── REJECT, retries < 3 ──→ C3 (loop)
                         D1 ─────┤── REJECT, retries >= 3 ──→ ESCALATE ──→ END
                                  └── PASS ──→ E1+E2

                                  ┌── BLOCK (E2 veto) ──→ END
                     E1+E2 ──────┤
                                  └── CLEAR ──→ F1

                                  ┌── REJECT ──→ END
                         F1 ─────┤
                                  └── APPROVE ──→ F2 ──→ END (SUBMITTED)
```

Each terminal node (`end_no_go`, `end_legal_block`, `end_rejected`, `escalate_*`) sets the final `status` and routes to `END`.

---

## 6. Where Each File Comes Into Play

A complete reference of when each source file is first activated during a pipeline run.

### Always Active (every run)

| File | Role | When |
|---|---|---|
| `src/config/settings.py` | Config singleton | First import — before anything runs |
| `src/models/enums.py` | Enum values | Every agent reads these |
| `src/models/state.py` | `RFPGraphState` | Every `BaseAgent.process()` call hydrates this |
| `src/models/schemas.py` | Data sub-models | Every agent creates one or more schema objects |
| `src/agents/base.py` | `BaseAgent.process()` | Every agent call goes through this |
| `src/orchestration/graph.py` | Graph builder + runner | Runs the entire pipeline |

### Triggered Sequentially

| File | When Activated | What It Produces |
|---|---|---|
| `src/agents/a1_intake.py` | Step 2 | `rfp_metadata`, `raw_text` |
| `src/agents/a2_structuring.py` | Step 3 | `structuring_result` (sections + confidence) |
| `src/orchestration/routing.py` | After A2 | Decides: retry / escalate / proceed |
| `src/agents/a3_go_no_go.py` | Step 4 | `go_no_go_result` (GO/NO_GO) |
| `src/orchestration/routing.py` | After A3 | Decides: end / proceed |
| `src/agents/b1_requirements_extraction.py` | Step 5 | `requirements` (list) |
| `src/agents/b2_requirements_validation.py` | Step 6 | `requirements_validation` (issues) |
| `src/agents/c1_architecture_planning.py` | Step 7 | `architecture_plan` (response sections) |
| `src/agents/c2_requirement_writing.py` | Step 8 | `writing_result` (prose + coverage) |
| `src/agents/c3_narrative_assembly.py` | Step 9 | `assembled_proposal` (full doc) |
| `src/agents/d1_technical_validation.py` | Step 10 | `technical_validation` (PASS/REJECT) |
| `src/orchestration/routing.py` | After D1 | Decides: retry loop / escalate / proceed |
| `src/agents/e1_commercial.py` | Step 11a | `commercial_result` (pricing) |
| `src/agents/e2_legal.py` | Step 11b | `legal_result` (risk assessment) |
| `src/orchestration/routing.py` | After E1+E2 | Decides: block / proceed |
| `src/agents/f1_final_readiness.py` | Step 12 | `approval_package` (decision brief) |
| `src/orchestration/routing.py` | After F1 | Decides: reject / proceed |
| `src/agents/f2_submission.py` | Step 13 | `submission_record` (hash, archive) |

### Only in Real Mode (not yet active)

| File | When Used | By Whom |
|---|---|---|
| `src/mcp_server/server.py` | Real agent processes | `MCPService` — agents import this |
| `src/mcp_server/rfp_store.py` | A1 embeds, A2-D1 query | RFP Vector Store |
| `src/mcp_server/knowledge_base.py` | A3, C1, C2, E1, E2 query | Company KB |
| `src/mcp_server/rules_engine.py` | A3, D1, E1+E2 gates | Hard business rules |
| `src/mcp_server/_internal/embedding.py` | RFP Store embeds text | Sentence Transformers |
| `src/mcp_server/_internal/chunker.py` | RFP Store chunks text | Text splitter |
| `src/mcp_server/_internal/vector_db.py` | RFP Store read/write | Chroma/Pinecone client |
| `src/document/parser.py` | A1 Intake only | PDF/DOCX → raw text |
| `src/prompts/templates.py` | All real agents | LLM prompt strings |

### Only via API Server

| File | When Active | Purpose |
|---|---|---|
| `src/api/app.py` | `--serve` mode | FastAPI application factory |
| `src/api/routes.py` | HTTP requests | Upload, status polling, approval, listing |

### Support / Persistence (not yet wired in pipeline)

| File | Purpose | Will Be Used By |
|---|---|---|
| `src/storage/file_storage.py` | Save/load files to local or S3 | A1, F2 |
| `src/storage/state_repository.py` | Persist state to MongoDB | Orchestration layer |
| `src/orchestration/callbacks.py` | Pipeline lifecycle hooks | Graph.py (WebSocket events for frontend) |

---

## 7. State Snapshot at Each Stage

A timeline showing how the state dict grows as it passes through each agent:

```
  Stage        Status              Fields Added            Audit Version
  ─────        ──────              ────────────            ─────────────
  START        RECEIVED            uploaded_file_path         —

  A1           RECEIVED            rfp_metadata               v1
                                   raw_text

  A2           STRUCTURING         structuring_result         v2

  A3           GO_NO_GO            go_no_go_result            v3

  B1           EXTRACTING_REQ      requirements               v4

  B2           VALIDATING_REQ      requirements_validation    v5

  C1           ARCH_PLANNING       architecture_plan          v6

  C2           WRITING_RESPONSES   writing_result             v7

  C3           ASSEMBLING          assembled_proposal         v8

  D1           TECH_VALIDATION     technical_validation       v9

  E1           COMM_LEGAL_REVIEW   commercial_result          v10

  E2           COMM_LEGAL_REVIEW   legal_result               v11
                                   commercial_legal_gate

  F1           AWAITING_APPROVAL   approval_package           v12

  F2           SUBMITTED           submission_record          v13
```

By the time the pipeline finishes, the state dict contains the complete history of every decision, every requirement, every piece of prose, and a 13-entry audit trail — all from a single uploaded file.
