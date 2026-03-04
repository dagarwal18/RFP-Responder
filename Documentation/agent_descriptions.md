# RFP Pipeline — Detailed Agent Descriptions

> **Last Updated:** 2026-02-28  
> **Pipeline Version:** 12-stage LangGraph state machine  
> **Agents:** 13 total (6 implemented, 7 stubs)

---

## Table of Contents

1. [Pipeline Overview](#pipeline-overview)
2. [Phase A — Document Understanding & Strategic Assessment](#phase-a--document-understanding--strategic-assessment)
   - [A1 — Intake Agent](#a1--intake-agent)
   - [A2 — Structuring Agent](#a2--structuring-agent)
   - [A3 — Go / No-Go Agent](#a3--go--no-go-agent)
3. [Phase B — Requirements Analysis](#phase-b--requirements-analysis)
   - [B1 — Requirements Extraction Agent](#b1--requirements-extraction-agent)
   - [B2 — Requirements Validation Agent](#b2--requirements-validation-agent)
4. [Phase C — Response Generation](#phase-c--response-generation)
   - [C1 — Architecture Planning Agent](#c1--architecture-planning-agent)
   - [C2 — Requirement Writing Agent](#c2--requirement-writing-agent)
   - [C3 — Narrative Assembly Agent](#c3--narrative-assembly-agent)
5. [Phase D — Quality Assurance](#phase-d--quality-assurance)
   - [D1 — Technical Validation Agent](#d1--technical-validation-agent)
6. [Phase E — Commercial & Legal Review](#phase-e--commercial--legal-review)
   - [E1 — Commercial Agent](#e1--commercial-agent)
   - [E2 — Legal Agent](#e2--legal-agent)
7. [Phase F — Finalization & Delivery](#phase-f--finalization--delivery)
   - [F1 — Final Readiness Agent](#f1--final-readiness-agent)
   - [F2 — Submission & Archive Agent](#f2--submission--archive-agent)
8. [Shared Infrastructure](#shared-infrastructure)
   - [BaseAgent](#baseagent)
   - [Pipeline State Model](#pipeline-state-model)
   - [Pipeline Graph & Routing](#pipeline-graph--routing)

---

## Pipeline Overview

```
A1 → A2 ──┬── (retry loop, max 3) ──→ A3 ──┬── GO ──→ B1 → B2 → C1 → C2 → C3 → D1 ──┬── PASS ──→ E1+E2 → F1 → F2 → END
           │                                │                                           │
           └── escalate_structuring → END    └── NO_GO → END                             ├── REJECT → C3 (retry, max 3)
                                                                                         └── escalate_validation → END
```

**Pipeline flow:**  
`A1 → A2 →(conditional)→ A3 →(conditional)→ B1 → B2 → C1 → C2 → C3 → D1 →(conditional)→ E1‖E2 →(conditional)→ F1 →(conditional)→ F2 → END`

**Conditional exits:** `NO_GO`, `LEGAL_BLOCK`, `REJECTED`, `ESCALATED`

---

## Phase A — Document Understanding & Strategic Assessment

### A1 — Intake Agent

| Property | Value |
|---|---|
| **Code ID** | `A1_INTAKE` |
| **Class** | `IntakeAgent` |
| **File** | `rfp_automation/agents/intake_agent.py` |
| **Status** | ✅ **Fully Implemented** |
| **Uses LLM** | ❌ No |
| **Uses MCP** | ✅ Yes — stores chunks to RFP Store |
| **Deterministic** | ✅ Yes — no randomness, same input → same output |

#### Purpose

The gateway agent. Takes a raw uploaded PDF, validates it, extracts all text and metadata, builds semantic chunks, and stores them in MCP for all downstream agents to retrieve. This is the **only agent that touches the raw file**.

#### Detailed Processing Steps

1. **File validation** — Verifies the file path exists in state, confirms the file is present on disk, and rejects non-PDF formats.
2. **SHA-256 hashing** — Reads the full file bytes and computes a content hash for deduplication and audit trail integrity.
3. **Structured block extraction** — Calls `ParsingService.parse_pdf_blocks()` to produce a list of typed blocks (`heading`, `text`, `table_mock`, etc.) each with a `page_number` and raw `text`. Logs block-type distribution for diagnostics.
4. **Metadata extraction via regex** — Calls `ParsingService.extract_metadata(blocks)` to pull structured fields: `rfp_number`, `organization`, `contact_email`, `contact_phone`, `issue_date`, `deadline`. This is regex-only — no LLM involvement.
5. **Semantic chunk preparation** — Calls `ParsingService.prepare_semantic_chunks(blocks)` which produces chunks annotated with `content_type` and `section_hint`. These chunks are the unit of storage and retrieval for all subsequent agents.
6. **Raw text concatenation** — Joins all block texts with newlines into `state.raw_text`. This is a temporary field used as a fallback by later agents (e.g., A2 retry strategy 2).
7. **MCP storage** — Instantiates `MCPService()` and calls `store_rfp_chunks(rfp_id, chunks, source_file)` to persist all chunks in the vector store indexed by `rfp_id`.
8. **Metadata object construction** — Builds `RFPMetadata` with: `rfp_id` (from extracted `rfp_number` or generated `RFP-XXXXXXXX`), `rfp_title` (first heading block or first text line), `page_count` (max page number from blocks), `word_count`, `file_hash`, contact info, and dates.
9. **State update** — Sets `state.rfp_metadata`, `state.uploaded_file_path` (resolved absolute path), `state.raw_text`, `state.status = INTAKE_COMPLETE`.

#### State Ownership

| Field | Access |
|---|---|
| `rfp_metadata` | ✍️ Write |
| `uploaded_file_path` | ✍️ Write (resolves to absolute) |
| `raw_text` | ✍️ Write |
| `status` | ✍️ Write → `INTAKE_COMPLETE` |

#### Error Conditions

- `ValueError` — No file path provided, or non-PDF file type
- `FileNotFoundError` — File path does not exist on disk
- `ValueError` — No text blocks extracted from document

#### Dependencies

- `ParsingService` — PDF parsing and chunking
- `MCPService` — Vector store chunk persistence

---

### A2 — Structuring Agent

| Property | Value |
|---|---|
| **Code ID** | `A2_STRUCTURING` |
| **Class** | `StructuringAgent` |
| **File** | `rfp_automation/agents/structuring_agent.py` |
| **Status** | ✅ **Fully Implemented** |
| **Uses LLM** | ✅ Yes — `llm_text_call(prompt, deterministic=True)` |
| **Uses MCP** | ✅ Yes — deterministic full fetch from RFP Store |
| **Deterministic** | ✅ Yes — temperature=0 via deterministic flag |
| **Has Retry Loop** | ✅ Yes — up to 3 attempts with retry hints in the prompt |

#### Purpose

Classifies the RFP document into logical sections across six predefined categories: `scope`, `technical`, `compliance`, `legal`, `submission`, `evaluation`. Assigns confidence scores to each section. If overall confidence is below 0.6, retries with a more granular retrieval strategy (up to 3 attempts).

#### Section Categories

| Category | What It Covers |
|---|---|
| `scope` | Project objectives, deliverables, background, overview |
| `technical` | Technical requirements, specs, architecture, system design |
| `compliance` | Regulatory standards, certifications |
| `legal` | Contract terms, liability, indemnification, IP |
| `submission` | Proposal format, deadline, delivery instructions |
| `evaluation` | Scoring methodology, selection criteria, weighting |

#### Detailed Processing Steps

1. **Retrieve all chunks deterministically** via `mcp.fetch_all_rfp_chunks(rfp_id)` — fetches every chunk in document order. The same complete chunk set is used on every retry; what changes on retry is the prompt (which includes hints referencing low-confidence sections from the previous attempt).
2. **Build prompt** from template (`prompts/structuring_prompt.txt`), injecting numbered chunk texts and retry hints referencing low-confidence sections from previous attempts.
3. **Call LLM** with `deterministic=True` — produces a JSON array of section objects.
4. **Parse JSON** — extracts `section_id`, `title`, `category` (normalized to valid values), `content_summary`, `confidence`, `page_range`. Handles markdown fences and malformed JSON gracefully.
5. **Compute overall confidence** — arithmetic mean of all section confidences.
6. **Update state** — If confidence ≥ 0.6: status → `GO_NO_GO`. If < 0.6: increments `retry_count`, status → `STRUCTURING` (triggers re-entry).

#### State Ownership

| Field | Access |
|---|---|
| `structuring_result` | ✍️ Write — `StructuringResult(sections, overall_confidence, retry_count)` |
| `status` | ✍️ Write → `GO_NO_GO` or `STRUCTURING` |
| `rfp_metadata.rfp_id` | 👁️ Read |
| `raw_text` | 👁️ Read (for strategy 2) |

#### Routing After A2

```
overall_confidence >= 0.6 → a3_go_no_go
retry_count < 3 and confidence < 0.6 → a2_structuring (retry)
retry_count >= 3 and confidence < 0.6 → escalate_structuring → END
```

---

### A3 — Go / No-Go Agent

| Property | Value |
|---|---|
| **Code ID** | `A3_GO_NO_GO` |
| **Class** | `GoNoGoAgent` |
| **File** | `rfp_automation/agents/go_no_go_agent.py` |
| **Status** | ✅ **Fully Implemented** |
| **Uses LLM** | ✅ Yes — `llm_text_call(prompt, deterministic=True)` |
| **Uses MCP** | ✅ Yes — RFP Store + Knowledge Store + Policy Store |
| **Deterministic** | ✅ Yes |

#### Purpose

Makes the strategic **GO / NO_GO** decision by evaluating the RFP against company policies, capabilities, and risk factors. Produces a detailed requirement-to-policy mapping table with per-requirement alignment status. This is the **critical gate** — a `NO_GO` terminates the entire pipeline.

#### Detailed Processing Steps

1. **Gather RFP content** — Formats `state.structuring_result.sections` into readable text (`### Title [category]\nSummary`). Falls back to MCP `query_rfp_all_chunks(rfp_id, top_k=50)` if no structured sections exist.
2. **Load company policies** — Calls `mcp.get_extracted_policies()` to retrieve pre-extracted company policy documents. These are the baseline for requirement alignment.
3. **Load company capabilities** — Calls `mcp.query_knowledge("company capabilities services", top_k=10)` to get contextual capability data for feasibility assessment.
4. **Build prompt** — Loads `prompts/go_no_go_prompt.txt` and injects: RFP sections (max 12K chars), policies (max 8K chars), capabilities (max 5K chars).
5. **Call LLM** — Single deterministic call producing a JSON response.
6. **Parse response** — Extracts:
   - `decision` — `GO` or `NO_GO`
   - `strategic_fit_score` — 0-10 scale
   - `technical_feasibility_score` — 0-10 scale
   - `regulatory_risk_score` — 0-10 scale
   - `policy_violations` — list of violation descriptions
   - `red_flags` — list of risk items
   - `justification` — free-text rationale
   - `requirement_mappings[]` — per-requirement alignment analysis with:
     - `mapping_status`: `ALIGNS`, `VIOLATES`, `RISK`, `NO_MATCH`
     - `matched_policy` / `matched_policy_id`
     - `confidence` score
     - `reasoning`
7. **State update** — Sets `go_no_go_result` and status to `EXTRACTING_REQUIREMENTS` (GO) or `NO_GO`.
8. **Logs formatted table** — Outputs a detailed Unicode-bordered requirement mapping table at INFO level for visibility.

#### State Ownership

| Field | Access |
|---|---|
| `go_no_go_result` | ✍️ Write — `GoNoGoResult` with mappings and scores |
| `status` | ✍️ Write → `EXTRACTING_REQUIREMENTS` or `NO_GO` |
| `structuring_result.sections` | 👁️ Read |
| `rfp_metadata.rfp_id` | 👁️ Read |

#### Important Behavioral Note

A3's output is **advisory context only** — it does NOT filter or modify the requirements list. The full requirement set from B1 flows unchanged to all subsequent agents regardless of A3's mapping findings.

---

## Phase B — Requirements Analysis

### B1 — Requirements Extraction Agent

| Property | Value |
|---|---|
| **Code ID** | `B1_REQUIREMENTS_EXTRACTION` |
| **Class** | `RequirementsExtractionAgent` |
| **File** | `rfp_automation/agents/requirement_extraction_agent.py` |
| **Status** | ✅ **Fully Implemented** |
| **Uses LLM** | ✅ Yes — `llm_deterministic_call(prompt)` — batched per section |
| **Uses MCP** | ✅ Yes — `fetch_all_rfp_chunks(rfp_id)` |
| **Deterministic** | ✅ Yes — temperature=0, seed=42 |

#### Purpose

The most complex agent. Performs a **full-document sweep** to extract every obligation, requirement, and evaluation criterion from the RFP, producing a deduplicated, sequentially-numbered list of structured `Requirement` objects. Uses a two-layer architecture: rule-based candidate detection followed by LLM-based structuring.

> **Note on grouping:** B1 groups chunks by `section_hint` — a field set by A1's `prepare_semantic_chunks()` during intake, derived from the PDF's heading structure. This is **independent of A2's LLM classification**, making B1's grouping deterministic and stable.

#### Architecture (Two-Layer Extraction)

```
Layer 1: Rule-Based Obligation Detection (ObligationDetector)
    ↓ candidate sentences with indicators
Layer 2: LLM Structuring & Classification
    ↓ structured Requirement JSON objects
```

#### Detailed Processing Steps

1. **Full-document retrieval** — `mcp.fetch_all_rfp_chunks(rfp_id)` — deterministic, sorted by `chunk_index`. No vector search randomness.
2. **Section grouping** — Groups chunks by `section_hint` (from A1's semantic chunking). Preserves semantic coherence for extraction context.
3. **Per-section two-layer extraction:**
   - **Layer 1 — Rule-based candidate detection**:
     - `ObligationDetector.detect_candidates(raw_text, source_section)` scans for obligation indicator patterns (must, shall, will, required, etc.)
     - Counts total obligation indicators for coverage validation
     - **Density check**: If candidate text density < `extraction_min_candidate_density`, falls back to full-text extraction (splits all sentences)
   - **Layer 2 — LLM structuring (batched)**:
     - Section context is truncated to 8,000 chars via `truncate_at_boundary()`
     - Token budget is calculated: output headroom ratio → input budget → overhead → available candidate chars
     - Candidates are batched into prompt-sized groups
     - Each batch is sent through `llm_deterministic_call()` using `prompts/extraction_prompt.txt`
     - On `ExtractionBatchError`: batch size is halved and retried; single-candidate failures are skipped
4. **JSON parsing with recovery** — Handles: markdown fences, missing closing brackets (truncated output), partial JSON repair (truncate to last `}`, append `]`). Filters out: empty text, truncated fragments (detected via regex), and very short text (< 15 chars).
5. **Requirement construction** — Each requirement gets:
   - `requirement_id` (from LLM or generated `REQ-NNNN`)
   - `text`, `type` (MANDATORY/OPTIONAL), `classification` (FUNCTIONAL/NON_FUNCTIONAL/EVALUATION_CRITERIA)
   - `category` (TECHNICAL/FUNCTIONAL/SECURITY/COMPLIANCE/COMMERCIAL/OPERATIONAL)
   - `impact` (CRITICAL/HIGH/MEDIUM/LOW), `source_section`, `keywords[]`
   - `source_chunk_indices[]` — traceability back to source chunks
6. **Embedding-based deduplication** — Three-tier strategy:
   - **Tier 1** (sim ≥ 0.99 + identical normalized text) → exact duplicate removal
   - **Tier 2** (sim ≥ 0.92 + same section) → same-section semantic dedup, keeps longer version
   - **Tier 3** (sim ≥ 0.95 + 60% keyword overlap) → cross-section dedup, keeps longer version
   - Falls back to text normalization dedup if embeddings fail
7. **Sequential ID re-assignment** — After dedup, all requirements are re-numbered `REQ-0001`, `REQ-0002`, etc. in document order.
8. **Coverage validation** — Compares extracted count vs. obligation indicator count. Logs warning if ratio < `extraction_coverage_warn_ratio`.
9. **State update** — Sets `state.requirements` and `status = VALIDATING_REQUIREMENTS`.

#### State Ownership

| Field | Access |
|---|---|
| `requirements` | ✍️ Write — `list[Requirement]` |
| `status` | ✍️ Write → `VALIDATING_REQUIREMENTS` |
| `rfp_metadata.rfp_id` | 👁️ Read |

#### Key Configuration (from `settings`)

| Setting | Purpose |
|---|---|
| `extraction_min_candidate_density` | Threshold below which full-text fallback triggers |
| `extraction_dedup_similarity_threshold` | Cosine similarity threshold for dedup |
| `extraction_coverage_warn_ratio` | Min ratio of requirements/indicators before warning |
| `llm_max_tokens` | Total token budget for LLM calls |
| `extraction_min_output_headroom_ratio` | Fraction of token budget reserved for output |

#### Dependencies

- `ObligationDetector` — Rule-based candidate sentence detection
- `EmbeddingModel` — For deduplication cosine similarity
- `MCPService` — Chunk retrieval
- `llm_deterministic_call` — Temperature=0 LLM calls

---

### B2 — Requirements Validation Agent

| Property | Value |
|---|---|
| **Code ID** | `B2_REQUIREMENTS_VALIDATION` |
| **Class** | `RequirementsValidationAgent` |
| **File** | `rfp_automation/agents/requirement_validation_agent.py` |
| **Status** | ✅ **Fully Implemented** |
| **Uses LLM** | ✅ Yes — `llm_text_call(prompt, deterministic=True)` (1-2 calls) |
| **Uses MCP** | ❌ No |
| **Deterministic** | ✅ Yes |

#### Purpose

Cross-checks B1's extracted requirements for quality issues: duplicates, contradictions, ambiguities. Produces a confidence score and issue list. If confidence falls below threshold, performs one grounded refinement pass using the original RFP text. **Issues do NOT block the pipeline** — they flow forward as advisory context.

#### Detailed Processing Steps

1. **Build validation prompt** — Serializes requirements as JSON (max 12K chars), injects into `prompts/requirements_validation_prompt.txt`.
2. **Call LLM for validation** — Single deterministic call. On failure, passes requirements through unvalidated with `confidence_score=0.0`.
3. **Parse validation JSON** — Extracts `confidence_score` and `issues[]` (each with `issue_type`, `requirement_ids[]`, `description`, `severity`).
4. **Conditional refinement** — If `confidence_score < min_validation_confidence`:
   - Builds a refinement prompt including: original issues, requirements JSON (max 10K chars), and **original RFP raw text** (max 8K chars) for grounding.
   - **Refinement guardrails**:
     - Can only REMOVE issues or LOWER severity
     - Cannot add new issues — if LLM returns more issues than original, refinement is **discarded entirely** to prevent hallucinated issue injection
     - Cannot modify requirement text
     - Cannot add new requirements
5. **Build result** — Constructs `RequirementsValidationResult` with computed counts:
   - `mandatory_count`, `optional_count`, `functional_count`, `non_functional_count`
   - `duplicate_count`, `contradiction_count`, `ambiguity_count`
6. **State update** — Sets `state.requirements_validation`, status → `ARCHITECTURE_PLANNING`.

#### State Ownership

| Field | Access |
|---|---|
| `requirements_validation` | ✍️ Write — `RequirementsValidationResult` |
| `status` | ✍️ Write → `ARCHITECTURE_PLANNING` |
| `requirements` | 👁️ Read |
| `raw_text` | 👁️ Read (for refinement grounding) |

#### Important Behavioral Note

B2 does **NOT filter** the requirements list. The full `state.requirements` from B1 passes unchanged to C1. B2's validated requirements are stored separately in `state.requirements_validation.validated_requirements` as advisory output.

---

## Phase C — Response Generation

### C1 — Architecture Planning Agent

| Property | Value |
|---|---|
| **Code ID** | `C1_ARCHITECTURE_PLANNING` |
| **Class** | `ArchitecturePlanningAgent` |
| **File** | `rfp_automation/agents/architecture_agent.py` |
| **Status** | ✅ **Fully Implemented** |
| **Uses LLM** | ✅ Yes — `llm_text_call(prompt, deterministic=True)` |
| **Uses MCP** | ✅ Yes — RFP Store + Knowledge Store |
| **Deterministic** | ✅ Yes |

#### Purpose

Produces the **complete response document blueprint**. Designs the proposal's section structure by combining RFP structure (from A2), extracted requirements (from B1/B2), submission instructions (from the RFP itself), and company capabilities (from the Knowledge Store). The output is the architectural plan that C2 uses to write each section.

#### Section Types

| Type | Description |
|---|---|
| `requirement_driven` | Sections that directly address extracted requirements |
| `knowledge_driven` | Sections built from company knowledge/capabilities |
| `commercial` | Pricing, cost breakdowns |
| `legal` | Terms, conditions, compliance statements |
| `boilerplate` | Standard sections (cover letter, table of contents, etc.) |

#### Detailed Processing Steps

1. **Gather requirements** — Uses `requirements_validation.validated_requirements` (B2 output). Falls back to raw `state.requirements` (B1 output) if B2's list is empty.
2. **Format A2 sections** — Converts `structuring_result.sections` into readable text with section IDs, titles, categories, and summaries.
3. **Fetch submission instructions** — Runs 4 targeted MCP queries against the RFP Store:
   - "submission instructions proposal format response structure"
   - "proposal should include following sections"
   - "evaluation criteria scoring methodology"
   - "vendor qualification requirements eligibility"
   - Results are deduplicated by text content.
4. **Fetch company capabilities** — Queries Knowledge Store using:
   - 4 general queries (capabilities, profile, case studies, certifications)
   - Per-category queries from requirement categories
   - Per-topic queries from A2 section topics
   - All results deduplicated by text content.
5. **Build prompt** — Loads `prompts/architecture_prompt.txt`, injects: RFP sections (12K), requirements (15K), capabilities (10K), submission instructions (8K).
6. **Call LLM** — Single deterministic call, returns JSON with `sections[]` and `rfp_response_instructions`.
7. **Parse response** — Builds `ResponseSection` objects with: `section_id`, `title`, `section_type`, `description`, `content_guidance`, `requirement_ids[]`, `mapped_capabilities[]`, `priority`, `source_rfp_section`.
8. **Coverage gap detection** — Identifies any `MANDATORY` requirement IDs not assigned to any `requirement_driven` section. Logs warnings for gaps.
9. **State update** — Sets `state.architecture_plan` with sections, gaps, and instructions; status → `WRITING_RESPONSES`.

#### State Ownership

| Field | Access |
|---|---|
| `architecture_plan` | ✍️ Write — `ArchitecturePlan` |
| `status` | ✍️ Write → `WRITING_RESPONSES` |
| `requirements_validation.validated_requirements` | 👁️ Read |
| `requirements` | 👁️ Read (fallback) |
| `structuring_result.sections` | 👁️ Read |
| `rfp_metadata.rfp_id` | 👁️ Read |

---

### C2 — Requirement Writing Agent

| Property | Value |
|---|---|
| **Code ID** | `C2_REQUIREMENT_WRITING` |
| **Class** | `RequirementWritingAgent` |
| **File** | `rfp_automation/agents/writing_agent.py` |
| **Status** | ⚠️ **Stub — Not Implemented** |

#### Intended Purpose

Generate prose response for each section defined in the C1 architecture plan. Uses requirement context and matched company capability evidence to write persuasive, compliant proposal content. Builds a coverage matrix tracking which requirements are addressed in which sections.

#### Expected Inputs

- `architecture_plan.sections` — The blueprint from C1 with section definitions, assigned requirement IDs, and mapped capabilities
- `requirements` / `requirements_validation.validated_requirements` — Full requirement details for each assigned ID
- Company capabilities from MCP Knowledge Store — evidence and proof points

#### Expected Outputs

- `writing_result.section_responses[]` — `SectionResponse` objects with `section_id`, `title`, `content` (prose), `requirements_addressed[]`, `word_count`
- `writing_result.coverage_matrix[]` — `CoverageEntry` objects with `requirement_id`, `addressed_in_section`, `coverage_quality` (`full`/`partial`/`none`)

#### State Ownership

| Field | Access |
|---|---|
| `writing_result` | ✍️ Write |
| `status` | ✍️ Write → `ASSEMBLING_NARRATIVE` |

---

### C3 — Narrative Assembly Agent

| Property | Value |
|---|---|
| **Code ID** | `C3_NARRATIVE_ASSEMBLY` |
| **Class** | `NarrativeAssemblyAgent` |
| **File** | `rfp_automation/agents/narrative_agent.py` |
| **Status** | ⚠️ **Stub — Not Implemented** |

#### Intended Purpose

Combine individual section responses (from C2) into a cohesive, unified proposal document. Generates an executive summary, creates smooth transitions between sections, ensures consistent tone and terminology, and produces a coverage appendix.

#### Expected Inputs

- `writing_result.section_responses[]` — Individual section content from C2
- `architecture_plan` — Section ordering and structure
- `rfp_metadata` — Title, client name, RFP number for document headers

#### Expected Outputs

- `assembled_proposal` — `AssembledProposal` with: `executive_summary`, `full_proposal_text`, `section_order[]`, `total_word_count`, `coverage_appendix`

#### State Ownership

| Field | Access |
|---|---|
| `assembled_proposal` | ✍️ Write |
| `status` | ✍️ Write → `TECHNICAL_VALIDATION` |

#### Special Routing

C3 participates in a **retry loop** with D1. If D1 rejects the proposal, control returns to C3 for re-assembly (max 3 retries before escalation).

---

## Phase D — Quality Assurance

### D1 — Technical Validation Agent

| Property | Value |
|---|---|
| **Code ID** | `D1_TECHNICAL_VALIDATION` |
| **Class** | `TechnicalValidationAgent` |
| **File** | `rfp_automation/agents/technical_validation_agent.py` |
| **Status** | ⚠️ **Stub — Not Implemented** |

#### Intended Purpose

Validates the assembled proposal against the original RFP requirements. Checks for completeness (all mandatory requirements addressed), alignment (response matches what was asked), realism (claims are supportable), and consistency (no contradictions within the proposal).

#### Expected Inputs

- `assembled_proposal` — The unified proposal from C3
- `requirements` — Original extracted requirements from B1
- `architecture_plan` — Expected section structure and requirement assignments

#### Expected Outputs

- `technical_validation` — `TechnicalValidationResult` with: `decision` (`PASS`/`REJECT`), `completeness_score`, `alignment_score`, `issues[]`, `retry_count`

#### State Ownership

| Field | Access |
|---|---|
| `technical_validation` | ✍️ Write |
| `status` | ✍️ Write → `COMMERCIAL_LEGAL_REVIEW` or back to `ASSEMBLING_NARRATIVE` |

#### Routing After D1

```
decision == PASS → commercial_legal_parallel (E1 + E2)
decision == REJECT && retry_count < 3 → c3_narrative_assembly (retry)
decision == REJECT && retry_count >= 3 → escalate_validation → END
```

---

## Phase E — Commercial & Legal Review

> **E1 and E2 run in parallel** (currently implemented as sequential execution in a combined `commercial_legal_parallel` node, with a fan-in gate that evaluates the combined result).

### E1 — Commercial Agent

| Property | Value |
|---|---|
| **Code ID** | `E1_COMMERCIAL` |
| **Class** | `CommercialAgent` |
| **File** | `rfp_automation/agents/commercial_agent.py` |
| **Status** | ⚠️ **Stub — Not Implemented** |

#### Intended Purpose

Generate a pricing breakdown using MCP knowledge base pricing rules. Analyzes the proposal's scope and requirements to produce detailed cost estimates, pricing tiers, and commercial terms.

#### Expected Inputs

- `assembled_proposal` — Validated proposal from D1
- `requirements` — For scoping and pricing per requirement category
- MCP pricing rules from Knowledge Store

#### Expected Outputs

- `commercial_result` — `CommercialResult` with: pricing breakdown, total cost, payment terms, assumptions

#### State Ownership

| Field | Access |
|---|---|
| `commercial_result` | ✍️ Write |

---

### E2 — Legal Agent

| Property | Value |
|---|---|
| **Code ID** | `E2_LEGAL` |
| **Class** | `LegalAgent` |
| **File** | `rfp_automation/agents/legal_agent.py` |
| **Status** | ⚠️ **Stub — Not Implemented** |
| **Special Authority** | 🚫 **Has VETO power — can BLOCK the entire pipeline** |

#### Intended Purpose

Analyze contract clauses for legal risk, verify compliance certifications, review liability and indemnification terms. This is the **only agent with BLOCK authority** — if it decides the legal risk is unacceptable, the pipeline terminates with `LEGAL_BLOCK`.

#### Expected Inputs

- `assembled_proposal` — Validated proposal
- `requirements` — For compliance requirement checking
- MCP legal templates and compliance rules

#### Expected Outputs

- `legal_result` — `LegalResult` with: `decision` (`APPROVED`/`CONDITIONAL`/`BLOCKED`), `block_reasons[]`, `risk_register[]`, `compliance_status`

#### State Ownership

| Field | Access |
|---|---|
| `legal_result` | ✍️ Write |

#### Fan-In Gate (After E1 + E2)

The `commercial_legal_parallel` node combines results:
- If `legal_result.decision == "BLOCKED"` → gate decision = `BLOCK` → pipeline ends with `LEGAL_BLOCK`
- Otherwise → gate decision = `CLEAR` → proceeds to F1

---

## Phase F — Finalization & Delivery

### F1 — Final Readiness Agent

| Property | Value |
|---|---|
| **Code ID** | `F1_FINAL_READINESS` |
| **Class** | `FinalReadinessAgent` |
| **File** | `rfp_automation/agents/final_readiness_agent.py` |
| **Status** | ⚠️ **Stub — Not Implemented** |

#### Intended Purpose

Compile the complete approval package: proposal document, pricing breakdown, legal risk register, requirement coverage matrix, and executive decision brief. Triggers the **human approval gate** — the only point in the pipeline where human intervention is required.

#### Expected Inputs

- `assembled_proposal` — Final validated proposal
- `commercial_result` — Pricing data from E1
- `legal_result` — Legal risk assessment from E2
- `writing_result.coverage_matrix` — Requirement coverage tracking

#### Expected Outputs

- `approval_package` — `ApprovalPackage` with: `decision_brief`, `proposal_summary`, `risk_summary`, `pricing_summary`, `approval_decision` (`APPROVE`/`REJECT`/`REQUEST_CHANGES`)

#### State Ownership

| Field | Access |
|---|---|
| `approval_package` | ✍️ Write |
| `status` | ✍️ Write → `SUBMITTING` or `REJECTED` |

#### Routing After F1

```
approval_decision == APPROVE → f2_submission
approval_decision == REJECT → end_rejected → END
```

---

### F2 — Submission & Archive Agent

| Property | Value |
|---|---|
| **Code ID** | `F2_SUBMISSION` |
| **Class** | `SubmissionAgent` |
| **File** | `rfp_automation/agents/submission_agent.py` |
| **Status** | ⚠️ **Stub — Not Implemented** |

#### Intended Purpose

Apply final formatting to the approved proposal, package all deliverables (proposal PDF, pricing sheets, compliance certificates), and archive everything to storage with file hashes for auditability. This is the **final agent** — pipeline status becomes `SUBMITTED` and the graph terminates.

#### Expected Inputs

- `approval_package` — Approved package from F1
- `assembled_proposal` — Final proposal content
- `commercial_result` — Pricing documents
- `rfp_metadata` — For file naming and archival metadata

#### Expected Outputs

- `submission_record` — `SubmissionRecord` with: `submitted_at`, `file_paths[]`, `file_hashes{}`, `archive_location`

#### State Ownership

| Field | Access |
|---|---|
| `submission_record` | ✍️ Write |
| `status` | ✍️ Write → `SUBMITTED` |

---

## Shared Infrastructure

### BaseAgent

**File:** `rfp_automation/agents/base_agent.py`

All 13 agents inherit from `BaseAgent`. It provides:

1. **`process(state: dict) → dict`** — The public entry point called by LangGraph. Converts the raw dict to `RFPGraphState`, invokes `_real_process()`, handles errors, manages audit trail, and broadcasts WebSocket progress events.
2. **`_real_process(state: RFPGraphState) → RFPGraphState`** — Abstract method that each agent overrides.
3. **Error handling**: 
   - `NotImplementedError` → Agent skipped gracefully, state preserved, pipeline continues
   - Any other `Exception` → Logged, re-raised (pipeline fails)
4. **WebSocket progress** — Broadcasts `on_node_start` / `on_node_end` / `on_error` events for real-time frontend tracking.
5. **Audit trail** — Automatically appends `completed` / `skipped` / `error` entries to `state.audit_trail`.
6. **Debug logging** — Logs input state summary, output state summary, and state diff for every agent execution.

### Pipeline State Model

**File:** `rfp_automation/models/state.py`

`RFPGraphState` (Pydantic BaseModel) is the single shared object flowing through every node. Key design rules:
- Each field is **owned by one agent** (marked in comments)
- Agents may **read any field** but should only **write to their owned fields**
- State is versioned via `state_version` (incremented on every audit entry)

### Pipeline Graph & Routing

**File:** `rfp_automation/orchestration/graph.py`

The LangGraph `StateGraph` wires all agents together with:
- **5 conditional edges** (A2 retry, A3 go/no-go, D1 validation, E1+E2 gate, F1 approval)
- **5 terminal nodes** (`end_no_go`, `end_legal_block`, `end_rejected`, `escalate_structuring`, `escalate_validation`)
- **1 parallel composite node** (`commercial_legal_parallel` — E1 + E2 sequential with fan-in gate)
