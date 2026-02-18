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
| **Company Knowledge Base** | Product specs, past proposals, certifications, pricing rules, legal templates, compliance policies — stored as embeddings |
| **Incoming RFP Store** | Full RFP text chunked and embedded at ingestion — all agents retrieve RFP context from here |

### MCP Server Layers

| Layer | What It Holds | Who Queries It |
|---|---|---|
| RFP Vector Store | Chunked + embedded incoming RFP | A2, A3, B1, C1, C2, D1, E2 |
| Knowledge Base | Company capabilities, past proposals, certs, pricing, legal templates | A3, C1, C2, E1, E2 |
| Policy Rules | Hard disqualification rules (certs, geography, contract limits) | A3 Go/No-Go gate |
| Validation Rules | SLA thresholds, prohibited language, over-promise patterns | D1 Validation gate |
| Commercial & Legal Rules | Combined E1+E2 decision logic, BLOCK conditions | E1+E2 fan-in gate |

---

## Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.10+ |
| Orchestration | LangGraph (state machine), LangChain (prompting, RAG) |
| LLM | OpenAI or Anthropic API |
| Database | MongoDB (state persistence, audit trail) |
| File Storage | AWS S3 (RFP files, outputs, archives) |
| MCP Server | Central vector store + rule layers |
| Vector Embeddings | Sentence Transformers |
| Vector Database | Chroma, Pinecone, or Weaviate (within MCP server) |
| State Models | Pydantic (type safety + validation) |
| Frontend | Next.js, TypeScript, Tailwind CSS, WebSocket |
| File Parsing | PyMuPDF (PDF), python-docx (DOCX) |
| Deployment | Docker on EC2 (backend), Vercel (frontend) |

---

## Project Structure

```
rfp-automation/
├── agents/              # One file per agent (A1, A2, A3, B1, B2, C1, C2, C3, D1, E1, E2, F1, F2)
├── orchestration/       # LangGraph state machine
├── mcp_server/          # MCP server — vector stores, knowledge base, rule layers
├── tools/               # PDF reader, DB client, embedding utilities
├── prompts/             # All LLM prompts
├── storage/             # File & state management
└── tests/               # Test data and cases
```

---

## Pipeline: 12-Stage Flow

### Stage 1 — Intake (A1)
The uploaded RFP file is validated, text is extracted, and the document is immediately chunked and embedded into the MCP server's RFP vector store. Basic metadata (client, deadline, RFP number) is written to state. From this point forward, no agent reads the raw file — all RFP retrieval goes through MCP.

### Stage 2 — RFP Structuring (A2)
Queries the MCP RFP store to retrieve and classify document sections (scope, technical requirements, compliance, legal terms, etc.). Assigns a confidence score to the structure. If confidence is too low, it re-queries with a different chunking strategy and retries up to 3 times before escalating for human review.

### Stage 3 — Go / No-Go Analysis (A3)
Retrieves the scope and compliance sections from the MCP RFP store. Queries the MCP knowledge base for company capabilities, certifications held, and contract history. Runs an LLM assessment scoring strategic fit, technical feasibility, and regulatory risk. The MCP policy rules layer then applies hard disqualification checks (certifications not held, geography restrictions, contract value limits). A violation at either layer produces **NO_GO → END**.

### Stage 4 — Requirements Extraction (B1)
Queries the MCP RFP store section by section to extract every requirement. Each requirement is classified by type (mandatory / optional), category (technical, compliance, commercial, etc.), and impact level. Results are written to state as a structured list with unique IDs.

### Stage 5 — Requirements Validation (B2)
Cross-checks the extracted requirements list for completeness, duplicate detection, and contradictions. Ambiguous mandatory requirements are flagged. Issues do not block the pipeline but are passed forward as context to downstream agents.

### Stage 6 — Architecture Planning (C1)
Queries both MCP stores simultaneously — the RFP store for requirement groupings and the knowledge base for relevant company solutions. Groups requirements into 5–8 logical response sections and maps each section to specific company capabilities. Validates that every mandatory requirement appears in the plan before proceeding.

### Stage 7 — Requirement Writing (C2)
For each response section, retrieves the relevant requirements from the MCP RFP store and matching capability evidence from the MCP knowledge base. Generates a full prose response per section, referencing real products, certifications, and past work. Builds a requirement coverage matrix tracking which requirements are addressed and where.

### Stage 8 — Narrative Assembly (C3)
Combines all section responses into a cohesive proposal document. Adds an executive summary, section transitions, and a requirement coverage appendix. Validates that no placeholder text remains and that the document is within submission length limits.

### Stage 9 — Technical Validation (D1)
Retrieves original requirements from the MCP RFP store and checks the assembled proposal against them. Runs three checks: coverage completeness (all mandatory requirements addressed), alignment (responses genuinely answer the requirements, not just mention the same keywords), and realism (claims are supportable). The MCP validation rules layer applies hard checks for over-promised SLAs and prohibited language. **REJECT** loops back to C3 Narrative Assembly with specific feedback. After 3 rejections the pipeline escalates to human review.

### Stage 10 — Commercial + Legal Review (E1 + E2 — Parallel)
Both agents run simultaneously.

- **E1 Commercial** queries the MCP knowledge base for pricing rules and applies the formula (base cost + per-requirement cost + complexity multiplier + risk margin). Generates the commercial response section.
- **E2 Legal** queries the MCP RFP store for contract clauses and the MCP knowledge base for the company's legal templates and certifications. Classifies each clause by risk level. Any CRITICAL risk (unlimited liability, missing required certification) produces a **BLOCK**.

The MCP commercial and legal rules layer combines both outputs. A BLOCK from E2 always terminates the pipeline regardless of E1's output — **END – Legal Block**.

### Stage 11 — Final Readiness (F1)
Compiles the full approval package: proposal document, pricing breakdown, legal risk register, requirement coverage matrix, and a one-page decision brief for leadership. Triggers the **Human Approval Gate** — the graph pauses here until an approver acts. **REJECT** at this gate ends the pipeline.

### Stage 12 — Submission & Archive (F2)
Applies final formatting and branding, packages all deliverables, and submits. Archives everything to S3 and MongoDB with file hashes logged for auditability. Final state is written as **SUBMITTED**.

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
    │
    ▼
A3 Go/No-Go ◄──────── MCP: RFP Store + Knowledge Base + Policy Rules
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
C1 Architecture Planning ◄──────── MCP: RFP Store + Knowledge Base
    │
    ▼
C2 Requirement Writing ◄─────────── MCP: RFP Store + Knowledge Base
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
  ┌─────────────────────────┐
  │ PARALLEL EXECUTION      │
  │  E1 Commercial ◄── MCP: Knowledge Base (pricing rules)
  │  E2 Legal      ◄── MCP: RFP Store + Knowledge Base (legal templates)
  └────────────┬────────────┘
               │
               ▼
    MCP: Commercial & Legal Rules
               │ BLOCK
               ├──────────────────────────────────► END – Legal Block
               │ CLEAR
               ▼
          F1 Final Readiness
               │
               ▼
        Human Approval Gate
               │ REJECT
               ├──────────────────────────────────► END – Failed
               │ APPROVE
               ▼
          F2 Submission & Archive
               │
               ▼
             END – Submitted
```

---

## State Schema

The shared graph state object contains:

| Field | Owner | Description |
|---|---|---|
| RFP metadata | A1 | ID, client name, deadline, status |
| Uploaded files | A1 | Original file paths + metadata |
| Structured sections | A2 | Section map with confidence scores |
| Requirements list | B1 | Classified requirements with unique IDs |
| Validation issues | B2 | Duplicates, contradictions, ambiguities |
| Architecture plan | C1 | Requirement groupings + capability mappings |
| Section responses | C2 | Per-section prose + coverage matrix |
| Assembled proposal | C3 | Full narrative document |
| Validation results | D1 | Pass/fail + issues + retry count |
| Commercial response | E1 | Pricing breakdown + terms |
| Legal status | E2 | Approved/conditional/blocked + risk register |
| Approval package | F1 | Decision brief for leadership |
| Audit trail | All | Every action logged with timestamps |

---

## Governance & Decision Points

| Gate | Agent | Outcomes |
|---|---|---|
| **Structuring Confidence** | A2 | Retry (up to 3) → Escalate to human |
| **Go / No-Go** | A3 | GO → continue, NO_GO → END |
| **Technical Validation** | D1 | PASS → continue, REJECT → loop to C3 (max 3), then escalate |
| **Legal Review** | E2 | APPROVED / CONDITIONAL → continue, BLOCKED → END (veto) |
| **Human Approval** | F1 | APPROVE → F2, REJECT → END, Timeout (48h) → escalate |

---

## Deployment

| Component | Deployment |
|---|---|
| Backend | Docker container on EC2 — FastAPI + LangGraph + all agents |
| Database | MongoDB container (or Atlas) |
| Queue | Redis for job queue |
| Frontend | Next.js on Vercel |
| File Storage | AWS S3 |
| Monitoring | CloudWatch logging |
| Real-time | WebSocket for live status updates |
