# RFP Response Automation -- Implementation Plan

> **Last Updated:** 2026-03-26
> **Current Progress:** 13 of 13 agents fully implemented (A1-F1). Pipeline runs end-to-end through human validation and PDF submission.

---

## Implementation Status

| Agent | Status | Key Implementation Details |
|---|---|---|
| A1 IntakeAgent | Done | PDF parsing, HuggingFace VLM table extraction (`vision_service.py`), Pinecone embedding, regex metadata |
| A2 StructuringAgent | Done | LLM section classification (6 categories), confidence scoring, retry loop (max 3) |
| A3 GoNoGoAgent | Done | LLM risk analysis + MCP policy rules, requirement-to-policy mapping table, NO_GO bypass (continues pipeline) |
| B1 RequirementsExtractionAgent | Done | Two-layer extraction (`obligation_detector.py` + LLM), 3-tier embedding dedup, temp=0/seed=42, JSON repair for truncated output |
| B2 RequirementsValidationAgent | Done | Grounded refinement with hallucination guards, Llama model with 50K/80K char limits |
| C1 ArchitecturePlanningAgent | Done | LLM section design + programmatic gap-fill + auto-split (max 20 reqs/section) |
| C2 RequirementWritingAgent | Done | Per-section prose, Llama token budgeting (~25K input budget), RFP metadata injection, 3-tier coverage matrix, JSON repair, fillable table format detection |
| C3 NarrativeAssemblyAgent | Done | LLM exec summary + transitions, split-section reassembly, coverage appendix, placeholder detection |
| D1 TechnicalValidationAgent | Done | Single-call/multi-pass validation, 4 checks (completeness/alignment/realism/consistency), Llama 4 Scout budgets |
| E1 CommercialAgent | Done | KB-driven pricing analysis, RFP pricing table layout detection, LLM commercial narrative, `commercial_rules.py` validation, missing data flagging |
| E2 LegalAgent | Done | Contract clause extraction + rule-based scoring + LLM analysis, certification compliance check, VETO authority (BLOCK terminates pipeline) |
| H1 HumanValidationAgent | Done | `ReviewService.build_review_package()`, structured source/response sections with paragraph-level anchoring, pipeline pause at AWAITING_HUMAN_VALIDATION |
| F1 FinalReadinessAgent | Done | Approval package + markdown generation + Mermaid rendering + PDF conversion + SHA-256 hash + archival (merged F1+F2 into single agent) |

### Infrastructure -- Completed

| Component | File(s) | Notes |
|---|---|---|
| State models | `models/enums.py`, `schemas.py`, `state.py` | 20+ Pydantic v2 models, `PipelineStatus` enum, `HumanValidationDecision`, `ApprovalDecision` |
| Orchestration | `orchestration/graph.py`, `transitions.py` | 16-node LangGraph, 5 conditional edges, `run_pipeline()` + `run_pipeline_from()`, Go/No-Go bypass, human validation gate |
| MCP Server | `mcp/mcp_server.py` + vector_store + rules | Pinecone + MongoDB + BM25 + 4 rule layers + rules_config |
| KB Seed Data | `mcp/knowledge_data/` | 7 JSON files (capabilities, certs, pricing, legal, profile, policies, proposals) |
| KB Loader | `mcp/knowledge_loader.py` | `seed_all()` function to bootstrap KB |
| API | `api/routes.py`, `knowledge_routes.py` | REST + WebSocket + CORS + document caching + checkpoint/rerun + human approval |
| Frontend (Legacy) | `frontend/index.html` | Vanilla JS dashboard: upload, status, agent output renderers, KB management, policy CRUD, review UI |
| Frontend (Next.js) | `frontend-next/` | Decoupled Next.js frontend with separate build/deploy |
| Services | `services/` | 11 service files: LLM, vision, parsing, review, obligation detection, cross-ref, section store, policy extraction, file, storage, audit |
| Persistence | `persistence/` | MongoDB client, state repo (in-memory), JSON checkpoints per agent, pipeline error logging |
| Tests | `tests/` | 12 test files covering agents, pipeline, rules, API, extraction, obligation detection, quality fixes, commercial/legal, output cleanup, table formatting |
| Prompts | `prompts/` | 13 prompt templates (A2, A3, B1, B2, C1, C2, C3, C3-transitions, D1, E1, E2, factual correction, policy extraction) |
| Utils | `utils/` | Logger, hashing, text utilities, Mermaid diagram extraction and rendering |
| Scripts | `scripts/` | Markdown-to-PDF converter, pipeline resume, Pinecone verification, Mermaid tests |
| Config | `config.py` + `.env` | Dual-model setup: Qwen3-32B (primary) + Llama 4 Scout (large context), secrets in `.env` |

### Dual-Model LLM Architecture

The system uses two Groq Cloud models based on agent context requirements:

| Model | Config Key | Context | TPM | Agents |
|---|---|---|---|---|
| `qwen/qwen3-32b` | `llm_model` | ~32K | 6K | A2, A3, B1, C1 (deterministic extraction/structuring) |
| `meta-llama/llama-4-scout-17b-16e-instruct` | `llm_large_model` | ~131K | 30K | B2, C2, C3, D1, E1, E2 (large-context writing/validation/analysis) |

Both share `max_tokens=8192` for output generation. Agents that process large inputs (full proposals, all requirements) use the Llama model via `llm_large_text_call()`. API key rotation (`groq_api_keys`) distributes calls across multiple keys with per-key TPM-aware throttling via `KeyRotator`.

---

## Recent Fixes (March 2026)

### Token Budget Corrections

Several agents had budget calculations based on `llm_max_tokens=8192` (an **output** limit), treating it as an input context limit. This caused severe data truncation:

| Agent | Issue | Fix |
|---|---|---|
| B1 | `MAX_CONTEXT_LEN` too small for Qwen's actual ~32K context | Increased to ~32K context, added `_repair_truncated_json_array()` for resilience |
| B2 | Requirements JSON truncated at 12K chars, RFP text at 15K | Raised to 50K/80K chars respectively to use Llama's capacity |
| C2 | Budget computed from 8192 output tokens instead of ~25K input budget | Recalculated using Llama's actual capacity (~100K chars), added JSON repair |
| D1 | Proposal and requirements truncated at small limits | `_SINGLE_CALL_MAX_CHARS=80K`, `_MAX_PROPOSAL_CHARS=100K`, `_MAX_REQUIREMENTS_CHARS=50K` |

### Go/No-Go Bypass

Modified `route_after_go_no_go()` in `transitions.py` to always route to `b1_requirements_extraction`, regardless of the decision. The `NO_GO` decision is preserved in `go_no_go_result` for frontend display but does not terminate the pipeline.

### E1/E2 Agent Implementation

- E1 CommercialAgent: KB-driven pricing with zero fabrication policy. Detects RFP pricing table layouts and mirrors them. Missing KB data is flagged for manual review.
- E2 LegalAgent: Two-layer analysis (rule-based + LLM) with contract clause extraction, certification compliance checking, and VETO authority.

### H1 and F1 Agent Implementation

- H1 HumanValidationAgent: Builds structured review packages with paragraph-level anchoring for source and response sections.
- F1 FinalReadinessAgent: Merged F1+F2 into single agent. Handles approval package, markdown generation, Mermaid rendering, and PDF conversion.

### Human Validation Workflow

Added `ReviewService` (533 lines) supporting:
- Section-level and paragraph-level review comments with domain anchoring
- Automatic rerun target computation based on comment domains
- Section-specific feedback injection into LLM prompts on rerun
- Pipeline `REQUEST_CHANGES` decision that re-runs from computed agent

### PDF and Mermaid Pipeline

- `scripts/md_to_pdf.py`: Custom markdown-to-PDF converter with professional formatting
- `utils/mermaid_utils.py`: Extracts Mermaid code blocks, validates syntax, renders to PNG via `npx @mermaid-js/mermaid-cli`
- F1 handles table row deduplication, invalid Mermaid block stripping, and technical parent section collapsing

---

## Quality Metrics (Latest Run -- March 2026)

| Metric | Value |
|---|---|
| Requirements extracted (B1) | 88-104 depending on RFP complexity |
| Coverage quality (D1) | 90-95% full, 5-10% partial, 0% missing |
| D1 validation decision | PASS (0 critical failures, 0 warnings) |
| Pipeline completion time | ~7-8 minutes (A1 to F1) |
| Assembled proposal word count | ~8,500 words across 13-15 sections |
| D1 checks | completeness, alignment, realism, consistency |

---

## Deployment

| Component | Current | Planned |
|---|---|---|
| Backend | Local dev (`uvicorn rfp_automation.api:app`) | Docker container on EC2 |
| Frontend (Legacy) | Served by FastAPI at `/` (vanilla JS) | Same (or deprecated) |
| Frontend (Next.js) | Separate dev server | Same container or CDN |
| Vector DB | Pinecone Serverless (AWS us-east-1, `BAAI/bge-m3`) | Same |
| Config DB | MongoDB local | MongoDB Atlas |
| Monitoring | Pipeline logs + WebSocket events | Same + structured logging |
