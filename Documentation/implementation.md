# 📝 Implementation Blueprint: Neuro-Symbolic RFP Responder (V1)

## 1. Core Architecture Philosophy
The system utilizes a **Master-Worker Supervisor** pattern. A central **Supervisor (Master Node)** orchestrates specialized **Neural Workers**, while the **Model Context Protocol (MCP)** acts as a **Symbolic Reasoning Engine** to enforce hard rules and perform Case-Based Reasoning (CBR).

---

## 2. Project Structure

```text
rfp_automation/
├── main.py                     # Entry point (FastAPI + LangGraph Init)
├── orchestration/
│   ├── supervisor.py           # Master Node (Task Planner & Delegator)
│   ├── graph.py                # LangGraph State Machine
│   └── state.py                # Pydantic State Schema (Requirement Matrix)
├── agents/
│   ├── workers/
│   │   ├── extractor.py        # 300-page Hierarchical Parser
│   │   ├── cbr_adaptor.py      # Neural Adaptation (Past Case -> Current Context)
│   │   └── validator.py        # Neuro-Symbolic Cross-Check
│   └── prompts/                # Isolated Prompt Templates
├── mcp/
│   ├── reasoning/
│   │   ├── cbr_engine.py       # Similarity Search & Case Retrieval
│   │   ├── logic_rules.py      # Symbolic Hard Constraints (Deterministic)
│   │   └── knowledge_graph.py  # Fact-based Entity Mapping
│   └── mcp_server.py           # Unified Interface for Agents
├── services/
│   ├── file_service.py         # S3 Upload & PDF Parsing
│   └── audit_service.py        # Reasoning Trace Logging
└── persistence/
    ├── mongo_client.py         # State & Requirement Matrix Storage
    └── state_repo.py           # Persistence Layer Logic
```

---

## 3. The Requirement Matrix (State Schema)
To handle 300 pages, the state is structured as a **Matrix**, not a string.

| Field | Description | Purpose |
| :--- | :--- | :--- |
| `id` | `RFP-SEC-001` | Unique identifier for the requirement. |
| `evidence` | `{page: 42, text: "..."}` | Physical anchor to the source PDF. |
| `cbr_citation` | `CASE_ID_99` | Link to the historical case used for the answer. |
| `logic_status` | `PASSED / FAILED` | Symbolic validation result. |
| `reasoning_trace` | `Text description` | The "Why" behind the Neuro-Symbolic decision. |

---

## 4. Execution Pipeline (The Data Lifecycle)

### Stage 1: Intake & Hierarchical Parsing
* **Action:** The `extractor.py` worker scans the 300-page document.
* **Technique:** It builds a recursive JSON tree of headings (1.1, 1.1.1) to preserve context.
* **Result:** 100+ discrete `Requirement` objects initialized in MongoDB.

### Stage 2: Case-Based Reasoning (CBR)
* **Action:** The `cbr_adaptor` queries the MCP for each requirement.
* **Process:** 1. **Retrieve:** Find 3 most similar past RFP answers.
    2. **Adapt:** Use Neural LLM to rewrite the old answer to fit the new client's name/specs.

### Stage 3: Symbolic Validation
* **Action:** The `validator.py` checks the draft against the `logic_rules.py`.
* **Example:** If the draft says "24/7 Support" but the Symbolic Rule for "Basic Tier" says "9-5 only," the validator flags a **Conflict**.

### Stage 4: Synthesis & Submission
* **Action:** The Master Node compiles all `PASSED` requirements into a `.docx` template.
* **Output:** Generates a final Response Document and a Compliance Matrix (Excel).

---

## 5. Anti-Hallucination Guardrails
1. **Coordinate Verification:** Agents must provide the exact page and paragraph index for every claim.
2. **Case Citation:** No "free-writing." Answers must be grounded in the CBR Knowledge Base.
3. **Symbolic Override:** If the Logic Engine detects a rule violation, it overrides the Neural LLM's output.

---

## 6. Development Roadmap
1. **Phase 1:** Setup LangGraph Supervisor and Pydantic State Schema.
2. **Phase 2:** Implement Hierarchical PDF Parser for long-document context management.
3. **Phase 3:** Build the MCP CBR Engine for similarity matching.
4. **Phase 4:** Integrate Symbolic Logic rules for hard-constraint validation.

---

## 7. Scaffolded Files (created)
The repository now contains a minimal scaffold to iterate from:

- main.py — FastAPI entrypoint + LangGraph placeholder
- orchestration/supervisor.py — Supervisor (Task planner / delegator) stub
- orchestration/graph.py — LangGraph state machine stub
- orchestration/state.py — Pydantic Requirement / RequirementMatrix schema
- agents/workers/extractor.py — Hierarchical PDF extractor stub
- agents/workers/cbr_adaptor.py — CBR adaptor stub (retrieve + adapt)
- agents/workers/validator.py — Validator stub (neuro-symbolic checks)
- agents/prompts/templates.py — Prompt templates constants
- mcp/reasoning/cbr_engine.py — Similarity search stub
- mcp/reasoning/logic_rules.py — Symbolic rule checker
- mcp/reasoning/knowledge_graph.py — Fact-store stub
- mcp/mcp_server.py — Thin API wrapper for MCP calls
- services/file_service.py — S3 / PDF parse stub
- services/audit_service.py — Reasoning trace logger
- persistence/mongo_client.py — Mongo client wrapper (async)
- persistence/state_repo.py — State persistence repository

## 8. How to run (dev)
1. Create a virtualenv and install: fastapi, uvicorn, pydantic, pymongo (or motor) as needed.
2. Start dev server:
   - uvicorn main:app --reload
3. Use endpoints in main.py to trigger extraction / preview flow.

## 9. Next tasks (priority)
1. Implement extractor parsing for long PDFs (hierarchical headings).
2. Wire CBR engine to a vector DB (Faiss, Milvus) and seed KB.
3. Implement logic_rules and connect validator to override drafts.
4. Add tests and CI.
