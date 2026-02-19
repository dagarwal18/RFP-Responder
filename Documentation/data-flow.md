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
User runs: python -m rfp_automation
```

| Step | File | What Happens |
|---|---|---|
| 1 | `rfp_automation/__main__.py` | Parses args: optional `--serve` flag, optional file path |
| 2 | `rfp_automation/main.py` → `run()` | Sets up logging, calls `run_pipeline()` |
| 3 | `rfp_automation/orchestration/graph.py` → `run_pipeline()` | Builds the LangGraph, creates initial state dict, calls `compiled.invoke(state)` |

### Path B: API Server (Frontend)

```
Frontend sends: POST /api/rfp/upload  (with file attached)
```

| Step | File | What Happens |
|---|---|---|
| 1 | `rfp_automation/api/__init__.py` → `create_app()` | FastAPI app is already running (started via `python -m rfp_automation --serve`) |
| 2 | `rfp_automation/api/routes.py` → `upload_rfp()` | Receives the file, saves to `./storage/uploads/`, generates an RFP ID |
| 3 | `rfp_automation/api/routes.py` → `upload_rfp()` | Calls `run_pipeline(uploaded_file_path=local_path)` — **same function as CLI** |
| 4 | `rfp_automation/orchestration/graph.py` → `run_pipeline()` | Builds the LangGraph, creates initial state dict, calls `compiled.invoke(state)` |

**Both paths converge here:**

```python
# rfp_automation/orchestration/graph.py — run_pipeline()
compiled = build_graph()         # ← builds the LangGraph state machine
state = {"uploaded_file_path": "path/to/file", "status": "RECEIVED"}
final_state = compiled.invoke(state)   # ← executes the entire pipeline
```

---

## 2. The State Object — What Flows Through the Pipeline

LangGraph passes a **single dict** through every node. This dict is defined by:

- `rfp_automation/models/state.py` → `RFPGraphState` (Pydantic model with all fields)
- `rfp_automation/models/schemas.py` → sub-models (`RFPMetadata`, `Requirement`, `GoNoGoResult`, etc.)
- `rfp_automation/models/enums.py` → all enum values (`PipelineStatus`, `GoNoGoDecision`, etc.)

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
| `error_message` | Any agent on failure | `str` |
| `state_version` | Auto-incremented by `add_audit()` | `int` |
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
         ┌─ rfp_automation/agents/base_agent.py ── BaseAgent.process() ─┐
         │                                                               │
         │  1. Hydrate: RFPGraphState(**state_dict)                      │
         │  2. Set: state.current_agent = self.name                      │
         │  3. Branch on mock_mode:                                      │
         │       True  → self._mock_process(state)                       │
         │       False → self._real_process(state)                       │
         │  4. Append audit entry via state.add_audit()                  │
         │  5. Return: state.model_dump()  → dict                        │
         │                                                               │
         └───────────────────────────────────────────────────────────────┘
                        │
                        ▼
              LangGraph merges returned dict into shared state
```

### File involvement for a single agent call:

| File | Role |
|---|---|
| `rfp_automation/agents/base_agent.py` | `process()` — the entry point LangGraph calls |
| `rfp_automation/agents/<agent>.py` | `_mock_process()` or `_real_process()` — the actual logic |
| `rfp_automation/models/state.py` | `RFPGraphState` — hydrates dict → Pydantic, dumps back to dict |
| `rfp_automation/models/schemas.py` | The sub-model the agent writes (e.g., `GoNoGoResult`) |
| `rfp_automation/models/enums.py` | Enum values the agent sets (e.g., `GoNoGoDecision.GO`) |
| `rfp_automation/config.py` | `get_settings()` — provides `mock_mode` flag |

**When real mode is enabled**, agents will also use:

| File | Role |
|---|---|
| `rfp_automation/mcp/mcp_server.py` | `MCPService` — the facade agents import |
| `rfp_automation/mcp/vector_store/rfp_store.py` | Query/embed RFP chunks |
| `rfp_automation/mcp/vector_store/knowledge_store.py` | Query company capabilities |
| `rfp_automation/mcp/rules/*.py` | Apply hard business rules |
| `rfp_automation/prompts/*.txt` | LLM prompt templates for this agent |

---

## 4. Process Flow — File to File

How Python files call each other from server startup to pipeline completion.

### 4.1 Server Startup

```
python -m rfp_automation --serve
│
▼
rfp_automation/__main__.py           ← entry point (parses --serve flag)
│  calls serve()
│
▼
rfp_automation/main.py               ← serve(host, port)
│  starts uvicorn with "rfp_automation.api:app"
│
▼
rfp_automation/api/__init__.py       ← create_app()
│  creates the FastAPI app
│  imports routes from rfp_automation/api/routes.py
│  imports settings from rfp_automation/config.py
│  registers /health and /api/rfp/* route groups
│  CORS configured for http://localhost:3000
│  returns FastAPI instance
│
▼
uvicorn starts listening on :8000
   routes defined in rfp_automation/api/routes.py are now live
```

### 4.2 CLI Direct Run (no server)

```
python -m rfp_automation
│
▼
rfp_automation/__main__.py           ← entry point
│  calls run()
│
▼
rfp_automation/main.py               ← run(file_path)
│  sets up logging
│  calls run_pipeline() directly
│  ──────────────────────────────── jumps straight to 4.4
```

### 4.3 User Uploads a File (API path)

```
Frontend sends POST /api/rfp/upload with file
│
▼
rfp_automation/api/routes.py         ← upload_rfp()
│  1. generates RFP ID
│  2. saves file to ./storage/uploads/
│  3. calls run_pipeline(uploaded_file_path=...)
│  4. stores result in in-memory _runs dict
│
▼ ─── both CLI and API converge here ───
```

### 4.4 Pipeline Execution (the core)

```
rfp_automation/orchestration/graph.py    ← run_pipeline()
│  build_graph():
│      instantiates 13 agents           ← rfp_automation/agents/__init__.py (imports all agent classes)
│      each agent __init__              ← rfp_automation/config.py (reads mock_mode)
│      creates LangGraph StateGraph(dict)
│      wires edges + conditional        ← rfp_automation/orchestration/transitions.py (5 routing functions)
│      compiles graph
│
│  compiled.invoke(state_dict)          ← LangGraph takes control, runs nodes in order
│
▼
For EACH agent node, LangGraph calls agent.process(state_dict):
│
│  rfp_automation/agents/base_agent.py  ← BaseAgent.process()
│  │  hydrates dict → RFPGraphState     ← rfp_automation/models/state.py
│  │  checks mock_mode                  ← rfp_automation/config.py
│  │
│  ├─ if mock_mode=True:
│  │     rfp_automation/agents/<agent>.py  ← _mock_process() (hardcoded data)
│  │
│  ├─ if mock_mode=False:
│  │     rfp_automation/agents/<agent>.py  ← _real_process()
│  │     │  queries MCP                    ← rfp_automation/mcp/mcp_server.py → vector_store/ + rules/
│  │     │  calls LLM with prompt          ← rfp_automation/prompts/*.txt
│  │     │  (A1 only) parses file          ← rfp_automation/services/parsing_service.py
│  │
│  │  creates typed output              ← rfp_automation/models/schemas.py
│  │  uses enum values                  ← rfp_automation/models/enums.py
│  │  appends audit entry               ← state.add_audit() in rfp_automation/models/state.py
│  │  dumps state → dict                ← state.model_dump()
│  │
│  ▼
│  LangGraph merges returned dict back into shared state
│
│  At governance checkpoints, LangGraph calls a routing function:
│      rfp_automation/orchestration/transitions.py  ← decides next node
│
│  ... repeats for each agent node ...
│
▼
compiled.invoke() returns final state dict
```

### 4.5 Result Returned

```
rfp_automation/orchestration/graph.py    ← returns final_state dict
│
├─ CLI path:
│  rfp_automation/main.py               ← _print_summary(final_state)
│                                          prints to terminal and exits
│
├─ API path:
│  rfp_automation/api/routes.py          ← stores final_state in _runs[rfp_id]
│                                          returns JSON {rfp_id, status, message} to frontend
│
│  Frontend can then:
│      GET /api/rfp/{id}/status          ← get_rfp_status()
│      POST /api/rfp/{id}/approve        ← approve_rfp()
│      GET /api/rfp/list                 ← list_rfps()
```

### 4.6 Agent Execution Order (happy path)

```
rfp_automation/orchestration/graph.py executes these nodes in this order:
│
├── intake_agent.py ──────────────────── always ──────── structuring_agent.py
├── structuring_agent.py ── transitions.py ── confidence ok? ──── go_no_go_agent.py
├── go_no_go_agent.py ──── transitions.py ── GO? ──────── requirement_extraction_agent.py
├── requirement_extraction_agent.py ──── always ──────── requirement_validation_agent.py
├── requirement_validation_agent.py ──── always ──────── architecture_agent.py
├── architecture_agent.py ──────────── always ──────── writing_agent.py
├── writing_agent.py ──────────────── always ──────── narrative_agent.py
├── narrative_agent.py ────────────── always ──────── technical_validation_agent.py
├── technical_validation_agent.py ── transitions.py ── PASS? ── graph.py: commercial_legal_parallel()
│                                                                   ├── commercial_agent.py (E1)
│                                                                   ├── legal_agent.py (E2)
│                                                                   └── fan-in gate evaluation
├── commercial_legal_parallel ── transitions.py ── CLEAR? ── final_readiness_agent.py
├── final_readiness_agent.py ── transitions.py ── APPROVE? ── submission_agent.py
└── submission_agent.py ──────────── END
```

---

## 5. Governance & Branching in Detail

All branching happens in `rfp_automation/orchestration/transitions.py`. The orchestration graph in `rfp_automation/orchestration/graph.py` wires these routing functions as conditional edges.

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

### Routing Functions

| Function | File | Decision Logic |
|---|---|---|
| `route_after_structuring` | `transitions.py` | Checks `structuring_result.overall_confidence` vs 0.6 threshold and retry count |
| `route_after_go_no_go` | `transitions.py` | Checks `go_no_go_result.decision` for GO or NO_GO |
| `route_after_validation` | `transitions.py` | Checks `technical_validation.decision` for PASS/REJECT and retry count |
| `route_after_commercial_legal` | `transitions.py` | Checks `commercial_legal_gate.gate_decision` for CLEAR/BLOCK |
| `route_after_approval` | `transitions.py` | Checks `approval_package.approval_decision` for APPROVE/REJECT |

### Terminal Nodes

Each terminal node (`end_no_go`, `end_legal_block`, `end_rejected`, `escalate_structuring`, `escalate_validation`) sets the final `status` and routes to `END`.

---

## 6. Where Each File Comes Into Play

A complete reference of when each source file is first activated during a pipeline run.

### Always Active (every run)

| File | Role | When |
|---|---|---|
| `rfp_automation/config.py` | Config singleton (`get_settings()`) | First import — before anything runs |
| `rfp_automation/models/enums.py` | Enum values | Every agent reads these |
| `rfp_automation/models/state.py` | `RFPGraphState` | Every `BaseAgent.process()` call hydrates this |
| `rfp_automation/models/schemas.py` | Data sub-models (20+ Pydantic models) | Every agent creates one or more schema objects |
| `rfp_automation/agents/base_agent.py` | `BaseAgent.process()` | Every agent call goes through this |
| `rfp_automation/orchestration/graph.py` | Graph builder + runner | Runs the entire pipeline |

### Triggered Sequentially

| File | When Activated | What It Produces |
|---|---|---|
| `rfp_automation/agents/intake_agent.py` | Step 1 | `rfp_metadata`, `raw_text` |
| `rfp_automation/agents/structuring_agent.py` | Step 2 | `structuring_result` (sections + confidence) |
| `rfp_automation/orchestration/transitions.py` | After A2 | Decides: retry / escalate / proceed |
| `rfp_automation/agents/go_no_go_agent.py` | Step 3 | `go_no_go_result` (GO/NO_GO) |
| `rfp_automation/orchestration/transitions.py` | After A3 | Decides: end / proceed |
| `rfp_automation/agents/requirement_extraction_agent.py` | Step 4 | `requirements` (list of 12 in mock) |
| `rfp_automation/agents/requirement_validation_agent.py` | Step 5 | `requirements_validation` (issues) |
| `rfp_automation/agents/architecture_agent.py` | Step 6 | `architecture_plan` (5 response sections) |
| `rfp_automation/agents/writing_agent.py` | Step 7 | `writing_result` (prose + coverage) |
| `rfp_automation/agents/narrative_agent.py` | Step 8 | `assembled_proposal` (full doc) |
| `rfp_automation/agents/technical_validation_agent.py` | Step 9 | `technical_validation` (PASS/REJECT) |
| `rfp_automation/orchestration/transitions.py` | After D1 | Decides: retry loop / escalate / proceed |
| `rfp_automation/agents/commercial_agent.py` | Step 10a | `commercial_result` (pricing) |
| `rfp_automation/agents/legal_agent.py` | Step 10b | `legal_result` (risk assessment) |
| `rfp_automation/orchestration/transitions.py` | After E1+E2 | Decides: block / proceed |
| `rfp_automation/agents/final_readiness_agent.py` | Step 11 | `approval_package` (decision brief) |
| `rfp_automation/orchestration/transitions.py` | After F1 | Decides: reject / proceed |
| `rfp_automation/agents/submission_agent.py` | Step 12 | `submission_record` (hash, archive) |

### Only in Real Mode (not yet active)

| File | When Used | By Whom |
|---|---|---|
| `rfp_automation/mcp/mcp_server.py` | Real agent processes | `MCPService` — agents import this |
| `rfp_automation/mcp/vector_store/rfp_store.py` | A1 embeds, A2–D1 query | RFP Vector Store |
| `rfp_automation/mcp/vector_store/knowledge_store.py` | A3, C1, C2, E1, E2 query | Company Knowledge Store |
| `rfp_automation/mcp/rules/policy_rules.py` | A3 Go/No-Go gate | Hard disqualification checks |
| `rfp_automation/mcp/rules/validation_rules.py` | D1 Validation gate | Prohibited language checks |
| `rfp_automation/mcp/rules/commercial_rules.py` | E1 pricing validation | Margin and contract value checks |
| `rfp_automation/mcp/rules/legal_rules.py` | E1+E2 fan-in gate | Gate decision evaluation |
| `rfp_automation/mcp/embeddings/embedding_model.py` | RFP Store embeds text | Sentence Transformers |
| `rfp_automation/services/parsing_service.py` | A1 Intake only | PDF/DOCX → raw text |
| `rfp_automation/prompts/*.txt` | All real agents | LLM prompt templates |

### Only via API Server

| File | When Active | Purpose |
|---|---|---|
| `rfp_automation/api/__init__.py` | `--serve` mode | FastAPI application factory |
| `rfp_automation/api/routes.py` | HTTP requests | Upload, status polling, approval, listing |
| `rfp_automation/api/websocket.py` | Pipeline events | `PipelineCallbacks` (logging only, WebSocket planned) |

### Support / Persistence

| File | Purpose | Will Be Used By |
|---|---|---|
| `rfp_automation/services/file_service.py` | Save/load files to local or S3 | A1, F2 |
| `rfp_automation/services/storage_service.py` | Coordinate file + state persistence | Orchestration layer |
| `rfp_automation/services/audit_service.py` | Record audit trail entries | Every agent |
| `rfp_automation/persistence/state_repository.py` | Persist state (in-memory / MongoDB) | Orchestration layer |
| `rfp_automation/persistence/mongo_client.py` | MongoDB connection wrapper | State repository |
| `rfp_automation/utils/logger.py` | Logging setup | `main.py` → `setup_logging()` |
| `rfp_automation/utils/hashing.py` | SHA-256 hashing | F2 Submission agent |

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
