# RFP Response Automation — Process Flow

## Architecture Overview

The system has two intelligence sources that all agents draw from via the MCP server:

- **Company Knowledge Base** — product specs, past proposals, certifications, pricing rules, legal templates, compliance policies. Stored as embeddings on the MCP server.
- **Incoming RFP Store** — as soon as the RFP is ingested, its full text is chunked and embedded into the MCP server's vector store. All agents retrieve RFP context from here rather than passing raw text through state.

Agents do not hold data themselves. They query the MCP server, reason over retrieved context, and write their outputs to shared graph state.

---

## Stage-by-Stage Flow

### 1. Intake (A1)
The uploaded RFP file is validated, text is extracted, and the document is immediately chunked and embedded into the MCP server's RFP vector store. Basic metadata (client, deadline, RFP number) is written to state. From this point forward, no agent reads the raw file — all RFP retrieval goes through MCP.

### 2. RFP Structuring (A2)
Queries the MCP RFP store to retrieve and classify document sections (scope, technical requirements, compliance, legal terms, etc.). Assigns a confidence score to the structure. If confidence is too low, it re-queries with a different chunking strategy and retries up to 3 times before escalating for human review.

### 3. Go / No-Go Analysis (A3)
Retrieves the scope and compliance sections from the MCP RFP store. Queries the MCP knowledge base for company capabilities, certifications held, and contract history. Runs an LLM assessment scoring strategic fit, technical feasibility, and regulatory risk. The MCP policy rules layer then applies hard disqualification checks (certifications not held, geography restrictions, contract value limits). A violation at either layer produces **NO_GO → END**.

### 4. Requirements Extraction (B1)
Queries the MCP RFP store section by section to extract every requirement. Each requirement is classified by type (mandatory / optional), category (technical, compliance, commercial, etc.), and impact level. Results are written to state as a structured list with unique IDs.

### 5. Requirements Validation (B2)
Cross-checks the extracted requirements list for completeness, duplicate detection, and contradictions. Ambiguous mandatory requirements are flagged. Issues do not block the pipeline but are passed forward as context to downstream agents.

### 6. Architecture Planning (C1)
Queries both MCP stores simultaneously — the RFP store for requirement groupings and the knowledge base for relevant company solutions. Groups requirements into 5–8 logical response sections and maps each section to specific company capabilities. Validates that every mandatory requirement appears in the plan before proceeding.

### 7. Requirement Writing (C2)
For each response section, retrieves the relevant requirements from the MCP RFP store and matching capability evidence from the MCP knowledge base. Generates a full prose response per section, referencing real products, certifications, and past work. Builds a requirement coverage matrix tracking which requirements are addressed and where.

### 8. Narrative Assembly (C3)
Combines all section responses into a cohesive proposal document. Adds an executive summary, section transitions, and a requirement coverage appendix. Validates that no placeholder text remains and that the document is within submission length limits.

### 9. Technical Validation (D1)
Retrieves original requirements from the MCP RFP store and checks the assembled proposal against them. Runs three checks: coverage completeness (all mandatory requirements addressed), alignment (responses genuinely answer the requirements, not just mention the same keywords), and realism (claims are supportable). The MCP validation rules layer applies hard checks for over-promised SLAs and prohibited language. **REJECT** loops back to Narrative Assembly with specific feedback. After 3 rejections the pipeline escalates to human review.

### 10. Commercial + Legal Review (E1 + E2 — Parallel)
Both agents run simultaneously.

- **E1 Commercial** queries the MCP knowledge base for pricing rules and applies the formula (base cost + per-requirement cost + complexity multiplier + risk margin). Generates the commercial response section.
- **E2 Legal** queries the MCP RFP store for contract clauses and the MCP knowledge base for the company's legal templates and certifications. Classifies each clause by risk level. Any CRITICAL risk (unlimited liability, missing required certification) produces a **BLOCK**.

The MCP commercial and legal rules layer combines both outputs. A BLOCK from E2 always terminates the pipeline regardless of E1's output — **END – Legal Block**.

### 11. Final Readiness (F1)
Compiles the full approval package: proposal document, pricing breakdown, legal risk register, requirement coverage matrix, and a one-page decision brief for leadership. Triggers the **Human Approval Gate** — the graph pauses here until an approver acts. **REJECT** at this gate ends the pipeline.

### 12. Submission & Archive (F2)
Applies final formatting and branding, packages all deliverables, and submits. Archives everything to S3 and MongoDB with file hashes logged for auditability. Final state is written as **SUBMITTED**.

---

## Data Flow Summary

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

## MCP Server Responsibilities

| Layer | What It Holds | Who Queries It |
|---|---|---|
| RFP Vector Store | Chunked + embedded incoming RFP | A2, A3, B1, C1, C2, D1, E2 |
| Knowledge Base | Company capabilities, past proposals, certifications, pricing, legal templates | A3, C1, C2, E1, E2 |
| Policy Rules | Hard disqualification rules (certs, geography, contract limits) | A3 Go/No-Go gate |
| Validation Rules | SLA thresholds, prohibited language, over-promise patterns | D1 Validation gate |
| Commercial & Legal Rules | Combined E1+E2 decision logic, BLOCK conditions | E1+E2 fan-in gate |