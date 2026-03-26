```text
                                      ┌──────────────────────────────┐
                                      │            USER              │
                                      │ Upload RFP / Review Output   │
                                      └──────────────┬───────────────┘
                                                     │
                                                     ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                              🖥️ FRONTEND LAYER                              │
│                                                                              │
│   ┌───────────────────────┐        ┌────────────────────────────┐            │
│   │  Vanilla JS SPA       │        │   Next.js Frontend         │            │
│   │  - Upload RFP         │        │   - Split-Pane Diff UI     │            │
│   │  - Dashboard          │        │   - KB Management          │            │
│   │  - Live Status        │        │   - Approval Flow          │            │
│   └────────────┬──────────┘        └────────────┬───────────────┘            │
│                │ REST API                       │ REST API                    │
│                └──────────────┬─────────────────┘                             │
│                               │ WebSocket (Live Progress)                    │
└───────────────────────────────▼──────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          ⚙️ BACKEND (FastAPI API Gateway)                    │
│                                                                              │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │ FastAPI Server Middleware                                           │   │
│   │ - /upload /status /human-approve /mcp-sync                          │   │
│   │ - Edge Triggers (Pydantic State Router)                             │   │
│   │ - WebSocket Manager (Telemetry Broadcaster)                         │   │
│   └──────────────┬──────────────────────────────────────────────────────┘   │
└──────────────────▼──────────────────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│              🔄 ORCHESTRATION + STATE MACHINE (LangGraph)                    │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                        FULL PIPELINE FLOW                              │  │
│  │                                                                        │  │
│  │  [START]                                                              │  │
│  │     │                                                                 │  │
│  │     ▼                                                                 │  │
│  │  (A1 Intake - Parse PDF/DOCX)                                         │  │
│  │     │                                                                 │  │
│  │     ▼                                                                 │  │
│  │  (A2 Structuring)                                                     │  │
│  │     ├── retry ↺ [confidence < 0.6, max 3]                              │  │
│  │     ├── ESCALATE → END                                                 │  │
│  │     ▼                                                                 │  │
│  │  (A3 Go/No-Go)                                                         │  │
│  │     ├── NO_GO → END (Pipeline Aborts)                                  │  │
│  │     └── GO (Passes Policy Check)                                       │  │
│  │     ▼                                                                 │  │
│  │  (B1 Extraction)                                                       │  │
│  │     ▼                                                                 │  │
│  │  (B2 Validation)                                                       │  │
│  │     ▼                                                                 │  │
│  │  (C1 Architecture Planning)                                            │  │
│  │     ▼                                                                 │  │
│  │  (C2 Requirement Writing)                                              │  │
│  │     ▼                                                                 │  │
│  │  (C3 Narrative Assembly)                                               │  │
│  │     ▼                                                                 │  │
│  │  (D1 Technical Validation)                                             │  │
│  │     ├── REJECT → C2 ↺ (Routes backward, max 3 retries)                 │  │
│  │     └── PASS / AUTO PASS (Forks to Parallel Execution)                 │  │
│  │           │                                                            │  │
│  │           ├─────▶ (E1 Commercial Pricer)                               │  │
│  │           │                                                            │  │
│  │           └─────▶ (E2 Legal Risk Review)                               │  │
│  │                        ├── BLOCK → END (Legal Veto)                    │  │
│  │                        └── PASS                                        │  │
│  │     ┌──────────────────┴──────────────────┐                            │  │
│  │     ▼       (Commercial/Legal Fan-In Sync Gate)                        │  │
│  │  (H1 Human Validation)                                                 │  │
│  │     ├── REQUEST_CHANGES → dynamic rerun (routes back to C2 target)      │  │
│  │     ├── REJECT → END (Human aborts pipeline)                           │  │
│  │     └── APPROVE → F1                                                   │  │
│  │     ▼                                                                 │  │
│  │  (F1 Final Submission + PDF & Mermaid Generation)                      │  │
│  │     ▼                                                                 │  │
│  │  [END]                                                                │  │
│  │                                                                        │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│   🔁 Key Features:                                                           │
│   • Parallel Execution (E1 Commercial & E2 Legal run concurrently)           │
│   • QA Retry Loops (A2, D1)                                                  │
│   • Conditional Routing & Hard Vetoes (A3, E2)                               │
│   • Human-in-the-loop (H1 breaks loop via Async Pause)                       │
└──────────────────────────────────────────────────────────────────────────────┘
                   │
                   ▼    (Agents query MCP API Facade for exact configs)
┌──────────────────────────────────────────────────────────────────────────────┐
│                     🧠 MCP HUB (Retrieval Facade Layer)                      │
│                                                                              │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │ MCPService Interface (Agent Query Gateway)                           │   │
│   │                                                                      │   │
│   │  ┌────────────────────────┐      ┌────────────────────────────────┐  │   │
│   │  │  Semantic Vector Search│      │  Exact Keyword/Relational      │  │   │
│   │  │  (RFP History)         │      │  (BM25 Search & SQL Logic)     │  │   │
│   │  │  [Pinecone Serverless] │      │  [MongoDB Atlas]               │  │   │
│   │  └───────────▲────────────┘      └──────────────▲─────────────────┘  │   │
│   │              │                                  │                    │   │
│   │  ┌───────────▼────────────┐      ┌──────────────▼─────────────────┐  │   │
│   │  │ 3-Tier Deduplicator    │      │ Policy & Constraints Engine    │  │   │
│   │  │ & bge-m3 Embeddings    │      │ - Rate Cards & Margins (E1)    │  │   │
│   │  │ (Filters redundancies) │      │ - Legal Clauses & MSAs (E2)    │  │   │
│   │  └────────────────────────┘      └────────────────────────────────┘  │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
                   │
                   ▼    (Storage Backing)
┌──────────────────────────────────────────────────────────────────────────────┐
│                          🗄️ DATA + STORAGE                                  │
│                                                                              │
│   MongoDB Atlas     Pinecone Serverless      File Storage (PDF, Mermaid PNG) │
│   (Relational)      (Vector DB)                                              │
└──────────────────────────────────────────────────────────────────────────────┘
                   │
                   ▼    (Inference layer executes agent tasks)
┌──────────────────────────────────────────────────────────────────────────────┐
│                    🌐 AI HARDWARE & INFERENCE SERVICES                       │
│                                                                              │
│   Groq LPU Array    Internal GPU Cluster     HuggingFace       Mermaid CLI   │
│  (Qwen3-32B Fast)   (Llama 4 Scout 17B)     (Qwen3-VL VLM)                   │
└──────────────────────────────────────────────────────────────────────────────┘


🔁 END-TO-END FLOW:

User → Next.js UI → REST Trigger → FastAPI (Pydantic State) → LangGraph Orchestrator
→ (Agents query MCP Server → Pinecone Vectors + Mongo Configs)
→ (Execution routed to Llama/Groq/QwenGPUs) → Response Drafted 
→ Pipeline Pauses (H1) → Human Validates → Mermaid/PDF Assembled → Returned to User
```
