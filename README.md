# RFP Response Automation System

A multi-agent AI pipeline that automates end-to-end RFP (Request for Proposal) response generation. Upload an RFP document and the system extracts requirements, generates a tailored proposal, validates quality, reviews legal and commercial risks, presents the draft for human approval, and produces a submission-ready PDF.

---

## How It Works

The pipeline runs 13 specialized AI agents in sequence, orchestrated by a LangGraph state machine:

```
A1 Intake        -- parse PDF, extract tables (VLM), store chunks
A2 Structuring   -- classify sections into 6 categories
A3 Go / No-Go    -- strategic assessment against company policies (advisory only)
B1 Extraction    -- extract requirements (rule-based + LLM, deduplicated)
B2 Validation    -- cross-check requirements for duplicates and contradictions
C1 Architecture  -- plan response document structure
C2 Writing       -- generate per-section prose with KB context
C3 Assembly      -- combine sections into cohesive narrative
D1 Validation    -- technical quality checks (completeness, alignment, realism, consistency)
E1 Commercial    -- pricing analysis from Knowledge Base (never fabricates values)
E2 Legal         -- contract clause risk assessment (has VETO power)
H1 Review Prep   -- build structured review package, pause for human decision
F1 Submission    -- generate final markdown + PDF, archive with SHA-256 hash
```

Governance checkpoints at A2 (confidence retry), D1 (quality loop back to C2), E2 (legal veto), and H1 (human approve / reject / request changes).

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Groq Cloud -- `qwen/qwen3-32b` (extraction) + `meta-llama/llama-4-scout-17b-16e-instruct` (writing, 131K context) |
| VLM | `Qwen/Qwen3-VL-8B-Instruct:novita` (table extraction) |
| Orchestration | LangGraph state machine (16 nodes, 5 conditional edges) |
| Vector DB | Pinecone Serverless (cosine, `BAAI/bge-m3` embeddings) |
| Structured DB | MongoDB (company config, certifications, pricing, legal) |
| API | FastAPI + WebSocket for real-time progress |
| PDF Output | Custom Markdown-to-PDF with Mermaid diagram rendering |
| Config | pydantic-settings (secrets in `.env`, defaults in `config.py`) |

---

## Quick Start

```bash
# 1. Create virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
copy .env.example .env
# Edit .env -- add GROQ_API_KEYS, HUGGINGFACE_API_KEYS, PINECONE_API_KEY

# 4. Start the server (dashboard at http://localhost:8000)
uvicorn rfp_automation.api:app --reload

# 5. Or run directly on a file
python -m rfp_automation "example_docs/rfp/Telecom RFP Document.pdf"
```

**Prerequisites:** Python 3.10+, Node.js 18+ (for Mermaid diagram rendering), MongoDB

---

## Environment Variables

Only secrets go in `.env`. Model names and thresholds are hardcoded in `config.py`.

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEYS` | Yes | Comma-separated Groq Cloud API keys (round-robin) |
| `HUGGINGFACE_API_KEYS` | Yes | Comma-separated HuggingFace API keys (VLM + embeddings) |
| `PINECONE_API_KEY` | Yes | Pinecone API key |
| `MONGODB_URI` | No | MongoDB connection string (default: `mongodb://localhost:27017`) |

Single-key fallbacks: `GROQ_API_KEY` and `HUGGINGFACE_API_KEY` are used if the plural versions are empty.

---

## API Overview

**RFP Pipeline** (`/api/rfp`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/rfp/upload` | Upload RFP PDF, start pipeline |
| GET | `/api/rfp/{rfp_id}/status` | Poll pipeline status + agent outputs |
| POST | `/api/rfp/{rfp_id}/approve` | Human decision (APPROVE / REJECT / REQUEST_CHANGES) |
| POST | `/api/rfp/{rfp_id}/rerun?start_from=agent` | Re-run pipeline from a specific agent |
| WS | `/api/rfp/ws/{rfp_id}` | Real-time WebSocket progress events |
| GET | `/api/rfp/list` | List all pipeline runs |

**Knowledge Base** (`/api/knowledge`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/knowledge/upload` | Upload company doc, auto-classify, embed |
| POST | `/api/knowledge/seed` | Seed KB from bundled JSON files |
| POST | `/api/knowledge/query` | Semantic search with optional `doc_type` filter |
| GET/POST/PUT/DELETE | `/api/knowledge/policies` | Policy CRUD |

Full Swagger UI at `/docs`.

---

## Frontends

| Frontend | Directory | Stack | Description |
|---|---|---|---|
| Legacy Dashboard | `frontend/` | Vanilla JS + CSS | Single-page app served by FastAPI at `/` |
| Next.js App | `frontend-next/` | Next.js 16, React 19, shadcn, Tailwind 4 | Decoupled frontend with review UI, KB management, policy editor |

See each directory's `README.md` for setup instructions.

---

## Checkpointing and Reruns

After each agent completes, state is saved as JSON at `storage/checkpoints/{rfp_id}/{agent_name}.json`. This enables:

- **Re-run from any agent** without re-executing predecessors
- **Persistence** across server restarts
- **Debugging** by inspecting intermediate state

---

## Project Structure

```
RFP-Responder/
+-- rfp_automation/              # Backend
|   +-- agents/                  # 14 agents (A1-F1)
|   +-- api/                     # FastAPI routes + WebSocket
|   +-- models/                  # Pydantic state + schemas + enums
|   +-- mcp/                     # MCP server (vector stores + rules + KB)
|   +-- services/                # LLM, parsing, review, vision, audit
|   +-- orchestration/           # LangGraph pipeline + routing
|   +-- prompts/                 # 13 LLM prompt templates
|   +-- persistence/             # MongoDB + checkpoints
|   +-- utils/                   # Logging, hashing, Mermaid
|   +-- tests/                   # 12 test files
+-- frontend/                    # Legacy vanilla JS dashboard
+-- frontend-next/               # Next.js decoupled frontend
+-- Documentation/               # Detailed system docs
|   +-- project-description.md   # Full system spec (agents, state, config)
|   +-- implementation-plan.md   # Implementation status + plans
+-- scripts/                     # PDF converter, Pinecone tools
+-- example_docs/                # Sample RFPs and KB docs
+-- .env.example
+-- requirements.txt
```

---

## Documentation

For detailed system documentation, see:

- **[Documentation/project-description.md](Documentation/project-description.md)** -- full system spec with agent descriptions, state schema, MCP architecture, configuration reference
- **[Documentation/implementation-plan.md](Documentation/implementation-plan.md)** -- implementation status, quality metrics, deployment plans

---

## Tests

```bash
pytest rfp_automation/tests/ -v
```

12 test files covering agents, pipeline integration, MCP rules, API endpoints, extraction, obligation detection, commercial/legal agents, output cleanup, and table formatting.
