# RFP-Responder — Project Handover Report
### Agentic B2B RFP Automation Engine | Technical & Stakeholder Reference

---

> **Document Purpose:** This report serves as a complete handover document for both the incoming development team and project stakeholders. It covers the LangGraph multi-agent system architecture, LLM choices, deployment setup, known issues with recommended fixes, and a comparative analysis of the technology stack. The system is delivered as a **reusable enterprise automation engine**, replacing a 4-6 person manual bid team with a single Human-In-The-Loop proposal operator.

---

## Table of Contents

1. [Project Overview & Scope](#1-project-overview--scope)
2. [System Architecture](#2-system-architecture)
3. [AI Pipeline — Agents, LLMs & Orchestration](#3-ai-pipeline--agents-llms--orchestration)
4. [Backend & Agentic API Reference](#4-backend--agentic-api-reference)
5. [Frontend Review Interface](#5-frontend-review-interface)
6. [MCP Hub & Database Setup (Pinecone + MongoDB)](#6-mcp-hub--database-setup-pinecone--mongodb)
7. [Deployment & Environment Setup](#7-deployment--environment-setup)
8. [Known Issues & Critical Bugs](#8-known-issues--critical-bugs)
9. [Technology Comparison & Alternatives](#9-technology-comparison--alternatives)
10. [Future Work & Roadmap](#10-future-work--roadmap)
11. [Glossary](#11-glossary)

---

## 1. Project Overview & Scope

### What RFP-Responder Is

RFP-Responder is an **Agentic AI system** designed to automate and orchestrate the complex B2B Request for Proposal (RFP) response process. Built on LangGraph, it orchestrates 13 specialized AI agents to handle document ingestion, semantic solution matching, pricing estimation, and compliance verification.

The core deliverable of this project is:
- A **14-Node LangGraph state machine** executing specialized AI roles.
- An **In-Process Model Context Protocol (MCP) Hub** for exact commercial and legal retrieval.
- A **Dual-LLM Engine** utilizing Qwen3-32B via Groq for speed and Llama 4 Scout 17B for deep context validation.
- A **Vision Language Model (Qwen3-VL-8B)** integration for extracting complex PDF tables.
- A **FastAPI / Next.js 16 decoupled web application** featuring a critical Human-In-The-Loop (HITL) review dashboard.
- A **Custom PDF rendering engine** ensuring enterprise-grade final documentation with dynamic architecture diagrams via Mermaid-CLI.

### What RFP-Responder Is NOT

This project is scoped as an **intelligent proposal assistant and pipeline**, not a fully autonomous legal authority. It explicitly does not cover:
- Zero-touch (fully automated) legal or commercial commitments.
- Direct submission of bids to external client portals.
- Acting as a System of Record (SoR) replacing core CRM/ERP systems (e.g., Salesforce).
- Complete replacement of final human sign-offs.

> **For Stakeholders:** The system elevates the human from a "prompt engineer" or "manual drafter" to a final strategic approver. A single proposal owner can oversee the execution of an entire Discover → Match → Price → Verify → Respond workflow.

### Inference Pipeline (End-to-End)

```text
Complex RFP PDF / Word Document
         │
         ▼
  ┌─────────────────┐
  │  Intake & VLM   │  ← Qwen3-VL-8B-Instruct
  │  (Extraction)   │    Outputs: Clean JSON, Extracted Tables & SLAs
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │   LangGraph     │  ← 14-Node State Machine (Routing & Agents)
  │ (Orchestration) │    Parallel tracks for Tech, Legal, and Pricing
  └────────┬────────┘
           │  Query exact rate cards & clauses
           ▼
  ┌─────────────────┐
  │    MCP Hub      │  ← Hybrid Search
  │ (RAG Retrieval) │    Pinecone (Vector) + MongoDB (BM25)
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │ Human-In-The-   │  ← Node H1 (FastAPI Next.js Split-Pane)
  │ Loop Gateway    │    Human approval / rewrite rejection
  └────────┬────────┘
           │
           ▼
   Final Formatted Word/PDF Response
   (w/ dynamic Mermaid architecture diagrams)
```

---

## 2. System Architecture

RFP-Responder follows an agent-driven microservice architecture with asynchronous real-time telemetry.

```text
┌──────────────────────────────────────────────────┐
│               CLIENT LAYER                        │
│   Next.js 16 · React 19 · TailwindCSS 4          │
│   Stateful Split-Pane Diff Review Editor         │
└─────────────────────┬────────────────────────────┘
                      │ WebSockets (Telemetry) + HTTP REST
                      ▼
┌──────────────────────────────────────────────────┐
│               API LAYER                           │
│   FastAPI + Uvicorn + Pydantic v2                 │
│   Handles state triggers, WebSockets, file I/O    │
└─────────────────────┬────────────────────────────┘
                      │ Pydantic State Dictionary Mutation
                      ▼
┌──────────────────────────────────────────────────┐
│           ORCHESTRATION LAYER                     │
│   LangGraph (14 Nodes, 13 Specialized Agents)     │
│   Dual-LLM Router (Groq + Llama 4)                │
└─────────────────────┬────────────────────────────┘
                      │ Model Context Protocol (MCP)
                      ▼
┌──────────────────────────────────────────────────┐
│           KNOWLEDGE & DATABASE LAYER              │
│   Pinecone Serverless (us-east-1)                 │
│   MongoDB Atlas (BM25 + Master Configs)           │
└──────────────────────────────────────────────────┘
```

### File Structure

```text
RFP-Responder/
├── backend/
│   ├── main.py                   # FastAPI entry point
│   ├── graph/
│   │   ├── state.py              # Pydantic RFPGraphState definition
│   │   ├── nodes/                # Individual agent node scripts (A1-F1)
│   │   └── workflow.py           # LangGraph directed graph compilation
│   ├── mcp/                      # Model Context Protocol hub logic
│   ├── utils/
│   │   ├── md_to_pdf.py          # Custom PDF formatter
│   │   └── key_rotator.py        # Token Bucket API Key manager
│   ├── requirements.txt
│   └── .env                      # Secret keys
├── frontend-next/
│   ├── app/                      # Next.js 16 app router
│   ├── components/               # React 19 UI components (Shadcn)
│   ├── package.json
│   └── .env.local
└── Documentation/                # Core docs & Handover reports
```

---

## 3. AI Pipeline — Agents, LLMs & Orchestration

> **Traceability Note:** The pipeline state is tracked across all nodes using the central `RFPGraphState` Pydantic model. If the pipeline fails, it can be resumed exactly at the failed node without discarding previous work.

### 3.1 Orchestration — LangGraph

We chose LangGraph over linear pipelines to support complex conditional logic and internal validation retry loops.
- **Total Nodes:** 16 (14 functional agents, 2 routing hubs)
- **Conditional Edges:** 5 (used for Go/No-Go checks, QA validation retries, Legal Veto blocks)
- **Parallel Subgraphs:** Commercial (E1) and Legal (E2) execute concurrently and merge at a sync node before proceeding to the Human H1 node.

### 3.2 Key Agents in the Pipeline

| Node ID | Agent Role | LLM Engine | Description |
|---|---|---|---|
| **A2** | Structural Extraction | Qwen3-32B | Breaks down 50-page PDFs into distinct, actionable JSON blocks. |
| **A3** | Go/No-Go Evaluator | Qwen3-32B | Evaluates strategic fit early. Can abort the entire pipeline to save compute cost. |
| **B1** | Requirement Parser | Llama 4 Scout | Deep context understanding to map client pain points. |
| **C2** | Proposal Writer | Llama 4 Scout | Drafts precise, localized response prose. |
| **D1** | QA Validation Loop | Llama 4 Scout | Compares drafted response against the raw RFP. Automatically routes back to C2 on failure (max 3 retries). |
| **E1** | Commercial Pricer | Qwen3-32B + MCP | Calculates rates against MongoDB rate menus. Hard constrained by DB retrievals. |
| **E2** | Legal Reviewer | Llama 4 Scout | Has "Veto" power. Will terminate pipeline if compliance fails critical risk thresholds. |
| **H1** | Human Validation | N/A (UI Gateway) | Halts pipeline. Serves state payload to Next.js dashboard for human Boolean approval. |
| **F1** | Final Readiness | Qwen3-32B | Post-human formatting, triggers Mermaid flowcharts and PDF assembly. |

### 3.3 The Dual-LLM Strategy

1. **Fast Extraction (`qwen/qwen3-32b` via Groq LPU):**
   Used for structural tasks. Groq's hardware provides deterministic, millisecond latency for heavy routing nodes. Managed by a custom `KeyRotator` to prevent Groq API key exhaustion.
2. **Deep Narrative (`Llama 4 Scout 17B`):**
   Writing prose and executing Node D1 (QA) requires massive context. Llama 4 provides a ~131K window, allowing the system to ingest the entire RFP and the drafted response simultaneously for contradiction checking without silent token truncation.

### 3.4 Vision Parsing (VLM)

Standard document parsers scramble corporate SLAs and pricing grids embedded in PDFs.
- **Model:** `Qwen3-VL-8B-Instruct`
- **Purpose:** Natively visually processes complex PDF pages to retain row/column logic and exact acronym structures, translating them flawlessly into JSON arrays prior to text embeddings.

---

## 4. Backend & Agentic API Reference

**Base URL:** `http://127.0.0.1:8000` (FastAPI)

### Endpoints

#### `POST /api/v1/rfp/upload`
Upload an RFP document and initiate preprocessing.
- **Body:** `multipart/form-data`
- **Response:** `{ success, rfp_id, basic_metadata }`

#### `POST /api/v1/pipeline/start`
Trigger the LangGraph state machine.
- **Body:** `{ rfp_id, run_mode }`
- **Response:** `{ success, run_id, message }`

#### `ws://127.0.0.1:8000/api/v1/pipeline/ws/{run_id}`
Real-time WebSocket telemetry for pipeline execution.
- **Events broadcasted:** Node transitions, validation loop metrics, time-to-completion estimates, and error traces.

#### `GET /api/v1/pipeline/state/{run_id}`
Retrieve the full current `RFPGraphState` dict.
- **Response:** `{ status: "AWAITING_H1", state: { ... } }`

#### `POST /api/v1/pipeline/human-approve`
Submit human modifications and resume pipeline from the Node H1 halt.
- **Body:** `{ run_id, approved: true/false, modified_text: "..." }`
- **Response:** `{ success, new_node: "F1_readiness" }`

#### `POST /api/v1/mcp/trigger-sync`
Force the Model Context Protocol hub to sync Pinecone and MongoDB.
- **Response:** `{ success, chunks_embedded }`

---

## 5. Frontend Review Interface

The dashboard represents a massive upgrade over basic AI wrapper tools, built specifically for concurrent Human-In-The-Loop proposal management.

| View | Functionality |
|---|---|
| **Pipeline Monitor** | Live WebSocket connection tracking LangGraph node execution. |
| **Human Validation Gate** | A synchronized split-pane Diff Editor. Left: Raw RFP source. Right: AI Drafted Response. Allows paragraph-level approvals. |
| **Knowledge Base (MCP) Manager** | UI to view, upload, and force-sync rate cards and legal templates in the MongoDB/Pinecone store. |
| **Export Hub** | Download final Word/Excel/PDF artifacts and generated Mermaid diagrams. |

**Tech Stack:** Next.js 16 (App Router), React 19 (Concurrent Rendering), TailwindCSS v4, Shadcn UI.
**Why React 19:** Essential to prevent the main UI thread from locking when rendering and diffing massive 8,500-word payloads generated by the QA nodes.

---

## 6. MCP Hub & Database Setup (Pinecone + MongoDB)

The pipeline uses a Model Context Protocol (MCP) facade to entirely eliminate commercial hallucination. Standard RAG relies purely on vector similarity, which mathematically fails at exact string matches (e.g., retrieving an exact alphanumeric product SKU).

### 6.1 Vector Search (Pinecone)
- **Use Case:** Semantic understanding of complex RFP requirements and past winning answers.
- **Provider:** Pinecone Serverless (AWS us-east-1).
- **Embeddings:** `BAAI/bge-m3` (Selected for multi-lingual, dense engineering text superiority).
- **Deduplication:** 3-tier embedding deduplication prevents the LLM from outputting repetitive answers to redundant questions in the RFP.

### 6.2 Relational & Keyword Search (MongoDB + BM25)
- **Use Case:** Exact extraction of commercial rate menus and legal clauses.
- **Setup:** MongoDB Atlas utilizing native BM25 full-text indexing.
- **Governance:** Nodes E1 (Commercial) and E2 (Legal) are hard-coded to **only** construct responses utilizing payloads proven to be retrieved from this database, mathematically blocking hallucinated numbers.

---

## 7. Deployment & Environment Setup

### System Requirements

| Component | Minimum | Recommended |
|---|---|---|
| Python | 3.10+ | 3.11 |
| Node.js | v18+ | v20+ (for Next.js & Mermaid) |
| RAM | 8 GB | 16 GB |
| OS | Windows / Linux / macOS | Ubuntu 22.04 or WSL2 |

### Step-by-Step Setup

**Step 1 — Clone the repository and install Backend Dependencies:**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\\Scripts\\activate
pip install -r requirements.txt
```

**Step 2 — Set Environment Variables (`backend/.env`):**
```bash
GROQ_API_KEY="your-groq-key,comma,separated,for,rotator"
LLAMA_ENDPOINT="your-llama-4-endpoint"
PINECONE_API_KEY="your-pinecone-key"
MONGO_URI="mongodb+srv://..."
```

**Step 3 — Install Mermaid-CLI (Required for F1 Final Readiness):**
```bash
npm install -g @mermaid-js/mermaid-cli
```

**Step 4 — Start the FastAPI Server:**
```bash
uvicorn main:app --reload --port 8000
```

**Step 5 — Start the Next.js Frontend:**
```bash
cd ../frontend-next
npm install
npm run dev
```
Open `http://localhost:3000` in the browser.

---

## 8. Known Issues & Critical Bugs

The following issues require monitoring by the incoming team.

### HIGH — Token Bucket Rate Limit Exhaustion (Groq)
**File:** `backend/utils/key_rotator.py`
**Impact:** Pipeline fails mid-execution because the 30K TPM limit is breached across all Groq keys during concurrent parallel runs.
**Fix:** Consider migrating to a paid Groq enterprise tier or expanding the key pool. The sliding window algorithm works perfectly but cannot bypass hard limits if traffic volume spikes.

### HIGH — Mermaid-CLI Cold Start Failures
**File:** `backend/utils/md_to_pdf.py`
**Impact:** The `F1_readiness` node sometimes times out or fails silently when `npx mmdc` spins up Puppeteer to render architecture diagrams, particularly on Windows environments.
**Fix:** Pre-warm the headless browser or replace the `npx` call with a persistent Dockerized Mermaid rendering microservice (e.g., Kroki).

### MEDIUM — WebSocket Disconnects During 8-Minute Pipeline Runs
**File:** `backend/main.py`
**Impact:** Next.js frontend loses live telemetry connection during massive inference spikes (e.g., Node D1 executing a 3-loop QA retry). User sees a "stalled" UI.
**Fix:** Implement aggressive ping/pong keep-alive logic inside the React 19 client and FastAPI WebSocket router. Store the latest state in Redis so the frontend can recover instantly on reconnection.

---

## 9. Technology Comparison & Alternatives

The following documents the rigorous justification behind the system architecture, specifically detailing why industry-standard alternatives were rejected in favor of the current stack.

### 9.1 Orchestration Layer
- **Tech Used:** LangGraph
- **Alternatives:** Temporal, Airflow, CrewAI.
- **Verdict:** Temporal/Airflow are overkill for purely LLM state graphs; CrewAI abstracts away too much explicit execution logic. LangGraph provides crucial directed-graph state management with granular, Python-controlled conditional edges (necessary for the hard "Legal Veto" routing strings).

### 9.2 Fast Structural Extraction
- **Tech Used:** Groq LPU Inference + Qwen3-32B
- **Alternatives:** GPT-4o-mini, Claude 3.5 Haiku.
- **Verdict:** Groq provides unparalleled, deterministic millisecond latency essential for powering the 10+ sub-graph routing tasks per run. Additionally, using an open-weights model ensures long-term corporate IP privacy regarding B2B pricing grids compared to proprietary APIs.

### 9.3 Deep Narrative Validation
- **Tech Used:** Llama 4 Scout 17B
- **Alternatives:** Gemini 1.5 Pro, Claude 3.5 Sonnet.
- **Verdict:** Recursively running full 50-page RFPs through multi-agent validation/retry loops is financially prohibitive on commercial APIs. Llama 4 provides a self-managed 131K context window for aggressive cross-document semantic error checking at a fraction of the cost.

### 9.4 Multimodal Table Parsing
- **Tech Used:** Qwen3-VL-8B-Instruct
- **Alternatives:** AWS Textract, Azure Document Intelligence.
- **Verdict:** Traditional OCR visually strips context from complex B2B SLA matrices containing merged cells and jargon. The VLM natively comprehends the link between physical layout and context, outputting flawless JSON payloads.

### 9.5 RAG & Knowledge Retrieval
- **Tech Used:** Pinecone (bge-m3) + MongoDB (BM25)
- **Alternatives:** pgvector, Elasticsearch, OpenAI Embeddings.
- **Verdict:** Serverless Pinecone gracefully handles spiky 50-page embedding loads instantly without infrastructure scaling. Mated with MongoDB’s native BM25 search, it enforces deterministic keyword retrieval of strict SKU codes and rate cards—mathematically blocking commercial hallucinations.

### 9.6 Backend & Frontend Setup
- **Tech Used:** FastAPI + Next.js 16 (React 19)
- **Alternatives:** Node.js/Go backend, Legacy React/Vanilla JS frontend.
- **Verdict:** FastAPI eliminates Python-bridge latency entirely since the whole AI ecosystem is Python-native while streaming LangGraph telemetry via WebSockets. React 19’s concurrent rendering handles massive 10,000+ word split-pane diffs without locking the UI thread during Human Validation.

---

## 10. Future Work & Roadmap

### High Priority (Phase 1)
1. **Dockerize the Pipeline:** Containerize the FastAPI backend, Next.js frontend, and Mermaid-CLI to eliminate local environment and Puppeteer setup issues.
2. **WebSocket Keep-Alives:** Resolve frontend stall bugs by implementing Redis-backed state recovery.

### Medium Priority (Phase 2)
3. **Self-Hosted Llama 4 Instance:** Move entirely off external endpoints by deploying Llama 4 Scout on internal enterprise GPU clusters to guarantee absolute data sovereignty.
4. **Enhanced Legal Veto Logic:** Expand Node E2 to execute automated red-lining on standard MSA contracts via detailed regular-expression checks alongside LLM inference.

### Lower Priority (Phase 3)
5. **Native Salesforce/HubSpot Integration:** Automatically ingest new RFPs the moment an opportunity is marked as "Proposal Requested" in CRM.
6. **Multi-Tenant Architecture:** Adapt the single-user local deployment to support isolated company tenant databases in MongoDB and localized Pinecone namespaces.

---

## 11. Glossary

| Term | Definition |
|---|---|
| **LangGraph** | A framework built on LangChain for creating stateful, multi-actor applications using graph-centric orchestration. |
| **Agentic AI** | AI models structured to execute independent tasks, plan steps, and utilize tools rather than just outputting text to a chat screen. |
| **MCP (Model Context Protocol)** | A standardized interface hub allowing the AI agents to seamlessly query databases (Pinecone/Mongo) for grounded context. |
| **VLM (Vision Language Model)** | An LLM trained to simultaneously process images/PDF layouts and text, resolving structure alongside semantics. |
| **RAG (Retrieval-Augmented Generation)** | Enhancing LLM responses by grounding them in retrieved factual data. |
| **BM25** | A robust term-frequency/inverse document frequency (TF-IDF) scoring algorithm excellent for exact keyword matching in MongoDB. |
| **LPU** | Language Processing Unit. Specialized hardware designed to run deterministic, ultra-fast structural LLM inference. |
| **Mermaid-CLI** | A command-line tool used by the pipeline to securely transform declarative markdown code into visual PNG system architecture charts. |
| **HITL (Human-in-the-Loop)** | The critical architectural design where the automated pipeline explicitly halts, requiring human validation (Node H1) and approval to resume execution. |

---

*Report prepared as part of the RFP-Responder project handover. All sections reflect the current Agentic AI architecture, and should act as the core source of truth for incoming developers and enterprise stakeholders.*