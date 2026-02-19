# RFP Response Automation — Implementation Plan

## Timeline Overview

| Phase | Weeks | Focus |
|---|---|---|
| 1. Foundation | 1–2 | Learn tools, design data architecture, scaffold MCP server |
| 2. Orchestration | 3–4 | State management, MCP server foundation, LangGraph skeleton with stubs |
| 3. Intelligent Agents | 5–9 | Build all 12 agents (A1→A2→A3→B1→B2→C1→C2→C3→D1→E1+E2→F1→F2) |
| 4. Finalization & UI | 10–11 | Finalization agents, Next.js frontend |
| 5. Testing & Showcase | 12–13 | Comprehensive testing, prompt refinement, demo preparation |

---

## Phase 1: Foundation (Weeks 1–2)

### Week 1 — Learn the Tools

**Goal:** Get comfortable with the core technologies.

- Set up Python environment — Install Python 3.10+, create virtual environment
- Get LLM API access — OpenAI or Anthropic, set $50 budget limit
- Learn LangChain basics — Complete 2–3 tutorials on prompting and chains
- Learn LangGraph fundamentals — Build a simple 3-node state machine
- Learn MCP server basics — Understand how agents query centralized vector stores and rule layers

**Deliverable:** Can build and run a basic StateGraph with conditional routing.

### Week 2 — Design Data Architecture

**Goal:** Define how information flows through the system.

#### State Schema (Pydantic)

The shared graph state object fields (defined in `rfp_automation/models/state.py`):

- RFP metadata (ID, client, deadline, status)
- Uploaded files (paths, metadata)
- Structured RFP sections (from A2 Structuring)
- Extracted requirements (list with classifications and unique IDs)
- Requirements validation issues (ambiguities, contradictions)
- Architecture plan (requirement groupings + capability mappings)
- Section-level responses (content per response section)
- Assembled proposal document (full narrative)
- Validation results (pass/fail + issues + retry count)
- Commercial response (pricing breakdown)
- Legal status (approved/conditional/blocked + reasoning + risk register)
- Commercial/legal gate result (combined decision)
- Approval package (decision brief for leadership)
- Submission record (archive details + file hash)
- Audit trail (every action logged)

**Deliverable:** Clear state schema + project skeleton + MCP server scaffold ready.

---

## Phase 2: Build the Orchestration (Weeks 3–4)

### Week 3 — State Management Layer + MCP Server Foundation

**Goal:** Build the foundation for state handling and the MCP server.

#### 1. State Schema (Pydantic)
- Define every field with types and validation in `rfp_automation/models/`
- `enums.py` — all enum types (`PipelineStatus`, `GoNoGoDecision`, etc.)
- `schemas.py` — 20+ sub-models (`RFPMetadata`, `Requirement`, `GoNoGoResult`, etc.)
- `state.py` — `RFPGraphState` with all fields, `add_audit()` method
- Each agent "owns" specific sections
- Prevents agents from overwriting each other

#### 2. State Repository
- `rfp_automation/persistence/state_repository.py` — in-memory dict in mock mode
- Save/load operations with versioned snapshots
- Version tracking via `state_version` counter
- Handle concurrent updates safely

#### 3. State Versioning
- When validation fails and loops back, keep both versions
- Essential for audit trail

#### 4. MCP Server Scaffold
- `rfp_automation/mcp/mcp_server.py` — `MCPService` facade (single entry point for agents)
- `rfp_automation/mcp/vector_store/rfp_store.py` — RFP Vector Store (chunking + embedding pipeline)
- `rfp_automation/mcp/vector_store/knowledge_store.py` — Company Knowledge Store
- `rfp_automation/mcp/rules/` — Policy, validation, commercial, legal rule layers
- `rfp_automation/mcp/schema/` — Pydantic models for MCP data types
- `rfp_automation/mcp/embeddings/embedding_model.py` — Sentence Transformers wrapper

**Deliverable:** Can create, save, load, and version state objects; MCP server accepts embeddings and returns queries.

### Week 4 — Build the LangGraph Skeleton

**Goal:** Create the 12-stage state machine with stub agents.

#### The Pipeline Flow

```
START → A1 Intake → A2 Structuring → A3 Go/No-Go →
B1 Req Extraction → B2 Req Validation →
C1 Architecture Planning → C2 Requirement Writing → C3 Narrative Assembly →
D1 Technical Validation → commercial_legal_parallel (E1+E2) →
F1 Final Readiness → Human Approval Gate → F2 Submission → END
```

#### Routing Logic

Defined in `rfp_automation/orchestration/transitions.py`:

| Decision Point | Function | Condition | Outcome |
|---|---|---|---|
| A2 Structuring | `route_after_structuring` | Confidence < 0.6 after max retries | Escalate to human review |
| A3 Go/No-Go | `route_after_go_no_go` | NO_GO | → END |
| D1 Validation | `route_after_validation` | REJECT | → Loop back to C3 (max 3 retries, then escalate) |
| E1+E2 fan-in | `route_after_commercial_legal` | E2 Legal BLOCK | → END (veto regardless of E1) |
| Human Approval | `route_after_approval` | REJECT | → END |

#### Implementation Steps
- Define `StateGraph(dict)` in `rfp_automation/orchestration/graph.py`
- Add 17 nodes (12 agents + `commercial_legal_parallel` + 5 terminal nodes)
- Add edges (simple, conditional; E1+E2 run sequentially within `commercial_legal_parallel`)
- Create 5 routing functions in `transitions.py`
- Set entry point = `a1_intake`, terminal nodes → `END`

#### Test All Conditional Paths with Stubs
- Happy path: GO → PASS → CLEAR → APPROVE → SUBMITTED
- A3 No-Go: NO_GO → END
- A2 Structuring escalation: low confidence → escalate → END
- D1 Validation loop: REJECT → C3 → D1 (up to 3 retries)
- E2 Legal block: BLOCK → END
- Human rejection: REJECT → END

**Deliverable:** Working 12-stage state machine that executes end-to-end with dummy data.

---

## Phase 3: Build Intelligent Agents (Weeks 5–9)

All agents inherit from `BaseAgent` (`rfp_automation/agents/base_agent.py`) which provides mock/real mode switching. Each agent implements `_mock_process()` (hardcoded data) and `_real_process()` (LLM + MCP queries).

### Week 5 — Intake Agent (A1)

**File:** `rfp_automation/agents/intake_agent.py` — `IntakeAgent`

**Responsibilities:** Process uploaded files, embed RFP into MCP server.

- File Validation — Check size, type (PDF/DOCX), not corrupted
- Text Extraction — `rfp_automation/services/parsing_service.py` handles PDF (PyMuPDF) and DOCX (python-docx)
- Metadata Extraction — Client name, deadline, RFP number via pattern matching
- Storage — Upload original file via `rfp_automation/services/file_service.py`
- Chunk & Embed — Split extracted text into chunks, embed into MCP RFP Vector Store
- Initialize State — Create `RFPMetadata` with status "RECEIVED"

From this point forward, no agent reads the raw file — all RFP retrieval goes through MCP.

**Tech:** PyMuPDF, python-docx, Sentence Transformers

### Week 5 — RFP Structuring Agent (A2)

**File:** `rfp_automation/agents/structuring_agent.py` — `StructuringAgent`

**Responsibilities:** Classify RFP document into logical sections.

- Query MCP RFP Store — Retrieve document chunks
- Section Classification — Identify and label: scope, technical requirements, compliance, legal terms, submission instructions, evaluation criteria
- Assign Confidence Score — Rate how reliably sections were identified
- Retry Logic — If confidence < 0.6, re-query with different chunking strategy (up to 3 retries)
- Escalation — If still low confidence after retries, flag for human review

**Output:** `StructuringResult` with `RFPSection` list and `overall_confidence` score.
**Prompt:** `rfp_automation/prompts/structuring_prompt.txt`

### Weeks 5–6 — Go/No-Go Agent (A3)

**File:** `rfp_automation/agents/go_no_go_agent.py` — `GoNoGoAgent`

**Responsibilities:** Decide if we should respond.

- Retrieve from MCP RFP Store: scope and compliance sections
- Retrieve from MCP Knowledge Store: company capabilities, certifications held, contract history
- LLM Analysis — Score strategic fit, technical feasibility, regulatory risk (1–10 each)
- MCP Policy Rules (`rfp_automation/mcp/rules/policy_rules.py`):
  - Required certifications not held → auto NO_GO
  - Geography restrictions violated → auto NO_GO
  - Contract value outside limits → auto NO_GO
- Decision Logic:
  - Any MCP policy violation → NO_GO
  - Any LLM score < 3 → NO_GO
  - Average > 7 → GO
  - 2+ red flags → NO_GO
- Generate executive summary of decision reasoning

**Output:** `GoNoGoResult` with GO/NO_GO decision, scores, and reasoning.
**Prompt:** `rfp_automation/prompts/go_no_go_prompt.txt`

### Weeks 6–7 — Requirements Extraction Agent (B1)

**File:** `rfp_automation/agents/requirement_extraction_agent.py` — `RequirementsExtractionAgent`

**Responsibilities:** Extract and classify all requirements from the RFP.

1. Query MCP RFP Store section by section (using A2's structure map)
2. Extract requirements per section:
   - LLM prompt: "Identify requirements for the system being proposed"
   - Signal words: "must", "shall" (mandatory); "should", "prefer" (optional)
   - Output structured JSON with requirement text, type, category
3. Classify each requirement:
   - Type: `MANDATORY` vs `OPTIONAL`
   - Category: `TECHNICAL`, `FUNCTIONAL`, `SECURITY`, `COMPLIANCE`, `COMMERCIAL`, `OPERATIONAL`
   - Impact: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`
4. Assign unique IDs (REQ-001, REQ-002, ...) to each requirement
5. Extract evaluation criteria separately

**Output:** Complete `Requirement` list with unique IDs (typically 50–150 items in real mode, 12 in mock).
**Prompt:** `rfp_automation/prompts/extraction_prompt.txt`

### Week 7 — Requirements Validation Agent (B2)

**File:** `rfp_automation/agents/requirement_validation_agent.py` — `RequirementsValidationAgent`

**Responsibilities:** Quality-check the extracted requirements list.

- Completeness Check — Verify all RFP sections produced requirements
- Duplicate Detection — Use embeddings to find semantically similar requirements
- Contradiction Detection — Flag requirements that conflict with each other
- Ambiguity Flagging — Flag vague mandatory requirements ("adequate", "user-friendly")

Issues do not block the pipeline — they are passed forward as context to downstream agents.

**Output:** `RequirementsValidationResult` with `ValidationIssue` list (duplicates, contradictions, ambiguities).

### Weeks 7–8 — Architecture Planning Agent (C1)

**File:** `rfp_automation/agents/architecture_agent.py` — `ArchitecturePlanningAgent`

**Responsibilities:** Plan the response structure and map capabilities.

- Query both MCP stores simultaneously:
  - RFP Store: requirement groupings from B1/B2
  - Knowledge Store: relevant company solutions, products, certifications
- Group requirements into 5–8 logical response sections
- Map each section to specific company capabilities
- Coverage validation: verify every mandatory requirement appears in the plan

**Output:** `ArchitecturePlan` with `ResponseSection` list (section → requirements → capabilities).
**Prompt:** `rfp_automation/prompts/architecture_prompt.txt`

### Week 8 — Requirement Writing Agent (C2)

**File:** `rfp_automation/agents/writing_agent.py` — `RequirementWritingAgent`

**Responsibilities:** Generate prose responses per section.

For each response section from C1's plan:
- Retrieve relevant requirements from MCP RFP Store
- Retrieve matching capability evidence from MCP Knowledge Store
- LLM generates response per section
- Build requirement coverage matrix — `CoverageEntry` per requirement

**Output:** `WritingResult` with `SectionResponse` list + `CoverageEntry` list.
**Prompt:** `rfp_automation/prompts/writing_prompt.txt`

### Week 8 — Narrative Assembly Agent (C3)

**File:** `rfp_automation/agents/narrative_agent.py` — `NarrativeAssemblyAgent`

**Responsibilities:** Combine section responses into a cohesive proposal document.

- Assemble all C2 section responses into cohesive narrative
- Add executive summary
- Add transitions between sections
- Add coverage appendix (full requirement coverage matrix)
- Quality check: no placeholder text, within submission length limits

**Output:** `AssembledProposal` with executive summary, full narrative, and word count.

### Weeks 8–9 — Technical Validation Agent (D1)

**File:** `rfp_automation/agents/technical_validation_agent.py` — `TechnicalValidationAgent`

**Responsibilities:** Quality-check the assembled proposal against original requirements.

**Checks** (4 `ValidationCheckResult` entries):
- Completeness — All mandatory requirements addressed
- Alignment — Responses genuinely answer requirements
- Realism — No overpromising (MCP Validation Rules checks prohibited language)
- Consistency — No contradictions between sections

**Decision Logic:**
- critical_failures > 0 → REJECT
- warnings > 5 → REJECT
- Otherwise → PASS

**On REJECT:** Increment retry counter, route back to C3. Max 3 retries, then escalate.

**Output:** `TechnicalValidationResult` with PASS/REJECT + checks + retry count.
**Prompt:** `rfp_automation/prompts/validation_prompt.txt`

### Week 9 — Commercial & Legal Agents (E1 + E2)

Both agents execute within `commercial_legal_parallel()` in `rfp_automation/orchestration/graph.py`. Results are combined via `rfp_automation/mcp/rules/legal_rules.py` → `evaluate_commercial_legal_gate()`.

#### E1 — Commercial Agent

**File:** `rfp_automation/agents/commercial_agent.py` — `CommercialAgent`

- Queries MCP Knowledge Store for pricing rules
- Applies formula: base cost + (per-requirement cost × complexity multiplier) + risk margin
- Defines payment terms
- Lists assumptions and exclusions

**Output:** `CommercialResult` with `PricingBreakdown` (total price, line items, margin).

#### E2 — Legal Agent

**File:** `rfp_automation/agents/legal_agent.py` — `LegalAgent`

- Queries MCP RFP Store for contract clauses
- Queries MCP Knowledge Store for legal templates and certifications
- Classifies each clause: LOW / MEDIUM / HIGH / CRITICAL via `ContractClauseRisk`
- Decision: `APPROVED` / `CONDITIONAL` / `BLOCKED` (veto authority)

**Output:** `LegalResult` with decision + `ContractClauseRisk` list + compliance status.
**Prompt:** `rfp_automation/prompts/legal_prompt.txt`

#### MCP Commercial & Legal Rules Fan-In

- `rfp_automation/mcp/rules/legal_rules.py` → `evaluate_commercial_legal_gate()`
- BLOCK from E2 → END – Legal Block (regardless of E1)
- Otherwise → CLEAR, proceed

---

## Phase 4: Finalization & UI (Weeks 10–11)

### Week 10 — Finalization Agents (F1, F2)

#### F1 — Final Readiness Agent

**File:** `rfp_automation/agents/final_readiness_agent.py` — `FinalReadinessAgent`

- Compile full `ApprovalPackage`:
  - Proposal document (from C3)
  - Pricing summary (from E1)
  - Legal risk summary (from E2)
  - Requirement coverage stats (from C2)
  - One-page decision brief for leadership
- Trigger **Human Approval Gate** — in mock mode, auto-approves
  - APPROVE → proceed to F2
  - REJECT → END – Rejected
  - REQUEST_CHANGES → END (currently same as reject)

#### F2 — Submission & Archive Agent

**File:** `rfp_automation/agents/submission_agent.py` — `SubmissionAgent`

- Package all deliverables for submission
- Generate SHA-256 hash of the full narrative for auditability (via `rfp_automation/utils/hashing.py`)
- Log completion — `SubmissionRecord` with archive paths and timestamps
- Final state written as **SUBMITTED**

### Week 11 — Build Frontend (Next.js)

**Directory:** `frontend/` (not yet started)

**Essential Pages:**

1. **Upload Page** — Drag-and-drop file upload, validation and progress indicator
2. **Dashboard** — List all RFPs with status, filter by status/client/date
3. **Status Page** — Real-time progress showing which agent is running, timeline of completed steps
4. **Approval Page** — Proposal preview, risk summary, Approve/Reject/Request Changes buttons

**Tech:** Next.js, TypeScript, Tailwind CSS, WebSocket for real-time updates

---

## Phase 5: Testing & Showcase Prep (Weeks 12–13)

### Week 12 — Comprehensive Testing

#### Unit Tests (`rfp_automation/tests/test_agents.py`)
- IntakeAgent: metadata creation, text extraction
- StructuringAgent: section classification, confidence scoring
- GoNoGoAgent: GO/NO_GO decision logic
- RequirementsExtractionAgent: requirement parsing, classification
- RequirementsValidationAgent: duplicate/contradiction detection
- TechnicalValidationAgent: PASS/REJECT logic, retry tracking
- CommercialAgent: pricing calculation
- LegalAgent: clause risk classification
- FinalReadinessAgent: approval package compilation

#### Rule Layer Tests (`rfp_automation/tests/test_rules.py`)
- PolicyRules: certification checks, geography restrictions
- ValidationRules: prohibited phrase detection
- CommercialRules: pricing margin validation
- LegalRules: gate decision evaluation

#### Integration Tests (`rfp_automation/tests/test_pipeline.py`)
- Happy path: GO → PASS → CLEAR → APPROVE → SUBMITTED
- A3 Go/No-Go termination: NO_GO → END
- D1 Validation loop: REJECT → C3 retry → PASS
- State persists across all agent transitions

#### End-to-End Tests (planned)
- Early termination: NO_GO stops at A3
- Structuring escalation: low confidence at A2 → escalate
- Legal veto: BLOCK at E1+E2 fan-in → END – Legal Block
- Human rejection: REJECT at F1 gate → END – Rejected

#### Test Data
- Simple RFP (20 requirements, clear scope)
- Complex RFP (100+ requirements, multi-domain)
- Ambiguous RFP (vague language, contradictions)

#### Error Handling
- LLM API failures (retry logic)
- Malformed files (graceful failure)
- Database errors (transaction rollback)

### Week 13 — Prompt Refinement & Polish

#### Performance Measurement
- Requirement extraction accuracy
- Technical response quality (human ratings)
- Validation accuracy

#### Prompt Iteration
- 7 prompt templates in `rfp_automation/prompts/` as `.txt` files
- Add examples (few-shot prompting)
- Add constraints (word count, specificity requirements)
- Add chain-of-thought reasoning
- Enforce structured output formats

#### A/B Testing
- Compare old vs new prompts on same RFPs
- Adopt only if clearly better

#### UI Polish
- Clear visual design
- Intuitive navigation
- Helpful tooltips and error messages
- Mobile-responsive (bonus)

### Week 13 — Prepare Showcase Demo

#### Demo Script (15-minute presentation)

| Segment | Duration | Content |
|---|---|---|
| Introduction | 2 min | Problem: RFP response is slow, expensive, error-prone. Solution: Multi-agent AI with governance. |
| Architecture | 3 min | State machine diagram, orchestration vs agent intelligence, governance controls. |
| Live Demo | 8 min | Upload RFP → status page → extracted requirements → generated response → validation → approval → final proposal. |
| Results | 2 min | Cycle time (weeks → days), requirement coverage (>95%), validation pass rate, cost savings. |

#### Demo RFP Selection
- Medium complexity (50–70 requirements)
- Covers technical, commercial, compliance areas
- Known to generate good results in testing
- Completes in ~10 minutes (for live demo pacing)

#### Backup Plan
- Pre-record the demo
- Have completed examples ready
- Prepare for Q&A on limitations

---

## Current Status

### Completed ✅

| Component | File(s) | Status |
|---|---|---|
| Package structure | `rfp_automation/` | All modules created |
| Configuration | `rfp_automation/config.py` | `Settings` with pydantic-settings, `.env` support |
| Data models | `rfp_automation/models/` | `enums.py`, `schemas.py` (20+ models), `state.py` |
| Base agent | `rfp_automation/agents/base_agent.py` | Mock/real switching, audit logging |
| All 13 agents | `rfp_automation/agents/` | Mock implementations complete |
| Orchestration | `rfp_automation/orchestration/graph.py` | Full LangGraph state machine |
| Routing logic | `rfp_automation/orchestration/transitions.py` | 5 routing functions |
| MCP facade | `rfp_automation/mcp/mcp_server.py` | `MCPService` with all sub-components |
| MCP rules | `rfp_automation/mcp/rules/` | Policy, validation, commercial, legal |
| MCP vector stores | `rfp_automation/mcp/vector_store/` | RFP store + knowledge store |
| MCP schemas | `rfp_automation/mcp/schema/` | Capability, pricing, requirement models |
| MCP embeddings | `rfp_automation/mcp/embeddings/` | Sentence Transformers wrapper |
| Services | `rfp_automation/services/` | File, parsing, storage, audit |
| Persistence | `rfp_automation/persistence/` | MongoDB client, state repository |
| API server | `rfp_automation/api/` | FastAPI app, routes, callbacks |
| Prompts | `rfp_automation/prompts/` | 7 `.txt` template files |
| Utilities | `rfp_automation/utils/` | Logger, SHA-256 hashing |
| Tests | `rfp_automation/tests/` | Agent tests, pipeline tests, rule tests |
| CLI entry point | `rfp_automation/__main__.py` | `--serve` flag support |

### Next Steps 🔄

| Task | Priority |
|---|---|
| Graduate agents from mock to real (connect LLM + MCP) | High |
| Wire `ParsingService` into A1 Intake for real file processing | High |
| Connect `MCPService` to actual vector store backend | High |
| Implement WebSocket for real-time pipeline status | Medium |
| Build Next.js frontend | Medium |
| Wire `StateRepository` into orchestration for persistence | Medium |
| Connect `AuditService` to MongoDB | Low |
| Add S3 support to `FileService` | Low |
