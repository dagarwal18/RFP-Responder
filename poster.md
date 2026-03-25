# 🚀 RFP Response Automation System
## Enterprise-Grade Generative AI Pipeline

---

### 🌟 Project Abstract
Manually responding to Requests for Proposals (RFPs) is a time-consuming, error-prone process. Our **RFP AI Automation System** tackles this by leveraging a **multi-agent LangGraph architecture** to automate end-to-end RFP ingestion, analysis, strategy, and drafting. With strict governance controls, hallucination guards, and real-time human-in-the-loop interfaces, it generates high-quality, high-compliance proposals in ~8 minutes.

---

### 🏗️ System Architecture

Our system is divided into three core layers seamlessly communicating via REST APIs and WebSockets.

1. **Modern User Interface (Frontend)**
   - **Framework:** Next.js (App Router, React)
   - **Features:** Real-time dashboard, live pipeline progress streams (via WebSockets), interactive knowledge base management, and a Human Approval Gate for quality control.

2. **Backend Services & Orchestration**
   - **API Layer:** FastAPI (Python 3.10+) running over ASGI (`uvicorn`).
   - **Orchestration:** LangGraph state machine maintaining execution context and managing routing across 17 control nodes and 13 individual agents.

3. **Data & Infrastructure Layer**
   - **LLM/VLM Infrastructure:** Groq Cloud (`qwen3-32b`, `llama-4-scout-17b`) and Novita (`Qwen3-VL-8B-Instruct`) for multimodal parsing.
   - **Vector Database:** Pinecone Serverless (us-east-1) using SentenceTransformers (`all-MiniLM-L6-v2`) for semantic search.
   - **Structured Database:** MongoDB storing legal policies, system rules, configurations, and company data constraints.

---

### 🌊 Flow of Data & Execution Pipeline

The pipeline processes proposals chronologically with embedded feedback loops and escalation paths:

1. **Ingestion & Digitization:** User uploads raw RFP documents (PDFs, Word) via the Next.js Frontend.
2. **Parsing & Structuring:** Complex tables are read via Visual Language Models (VLMs), and textual data is semantically clustered.
3. **Strategic Go/No-Go Decision:** The AI evaluates alignment with company capabilities based on the Vector Knowledge Base. Even on a "No-Go" recommendation, the dashboard persists the status while continuing analysis.
4. **Extraction & Validation:** Requirements are extracted, de-duplicated, and grounded using custom LLM guards to prevent hallucinations.
5. **Drafting & Assembly:** Content is generated within safe token limits ("budgeting") and iteratively stitched together to create a cohesive narrative.
6. **Review & Approval:** Output is technically evaluated. Before final submission, execution stalls at the **Human Approval Gate**, notifying the Next.js frontend for strict human validation.

---

### 🤖 Multi-Agent Ecosystem

The system delegates complexity across **13 Specialized AI Agents**, ensuring modularity and isolated responsibilities:

#### Phase A: Intake & Strategy
- **🤖 A1 IntakeAgent:** Handles PDF parsing, VLM-powered table extraction, and Pinecone vector embedding.
- **🤖 A2 StructuringAgent:** Classifies sections into predefined categories using automated LLM retries.
- **🤖 A3 GoNoGoAgent:** Maps extracted RFP needs against MongoDB internal policy rules and computes early risk/violation scores.

#### Phase B: Requirement Analysis
- **🤖 B1 RequirementsExtractionAgent:** Executes dual-layer (rule + LLM-based) extraction, 3-tier de-duplication, and precise JSON repair.
- **🤖 B2 RequirementsValidationAgent:** Acts as the truth-checker, refining output with strict hallucination guards against large-context models.

#### Phase C: Content Generation
- **🤖 C1 ArchitecturePlanningAgent:** Performs programmatic gap-filling and splits overloaded RFP sections to prevent token overflow down the line.
- **🤖 C2 RequirementWritingAgent:** Actively manages LLM token budgets while injecting metadata and writing highly compliant responses accompanied by a multi-tier coverage matrix.
- **🤖 C3 NarrativeAssemblyAgent:** Produces the executive summary, crafts smooth transitions, and reassembles split sections into a unified proposal.

#### Phase D, E & F: Quality & Governance
- **🤖 D1 TechnicalValidationAgent:** Multi-pass technical evaluator assessing completeness, alignment, and consistency.
- **🤖 E1 CommercialAgent & E2 LegalAgent:** Dedicated compliance reviewers designed to instantly flag or block critical financial or legal risks.
- **🤖 F1 FinalReadinessAgent & F2 SubmissionAgent:** Prepares the definitive package payload for the Next.js frontend and manages the final compilation upon manual Human Approval.

---

### 🛠️ Tech Stack Highlights
* **Frontend:** Next.js, React, Tailwind, TypeScript
* **Backend:** FastAPI, Python, LangGraph
* **AI Models:** Llama-4-Scout (131K context), Qwen3-32b, Qwen3-VL.
* **Databases:** Pinecone DB, MongoDB
