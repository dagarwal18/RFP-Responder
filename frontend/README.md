# RFP Responder -- Legacy Frontend

Single-page vanilla JavaScript dashboard served by FastAPI at `/`. No build step or dev server required.

---

## Architecture

| Aspect | Detail |
|---|---|
| Framework | None -- vanilla HTML / CSS / JS |
| Served by | FastAPI `StaticFiles` + `FileResponse` at `/` |
| Real-time | WebSocket (`/api/rfp/ws/{rfp_id}`) for live pipeline progress |
| Fallback | Polling `/api/rfp/{rfp_id}/status` with pause/resume support |
| Styling | CSS with CSS variables for theming (`css/styles.css`, 55KB) |

## File Structure

```
frontend/
+-- index.html          # Single-page app shell
+-- css/
|   +-- styles.css      # All styles with CSS variables
+-- js/
|   +-- app.js          # App initialization + routing
|   +-- kb.js           # Knowledge Base panel logic
|   +-- pipeline.js     # RFP pipeline panel + WebSocket + agent output renderers
+-- README.md
```

## Features

### Left Panel -- Knowledge Base

| Feature | Description |
|---|---|
| Document Upload | Drag-and-drop or click to upload PDF/DOCX/JSON/CSV files |
| Auto-Classification | Regex keyword scoring assigns a `doc_type` badge automatically |
| Uploaded Files | Lists all uploaded files with name, doc type, vector count, and timestamp |
| Query | Search the knowledge base with an optional `doc_type` filter dropdown |
| Seed and Status | Seed bundled knowledge data and check KB vector count |

### Right Panel -- RFP Pipeline

| Feature | Description |
|---|---|
| RFP Upload | Drag-and-drop or click to upload an RFP document |
| WebSocket Stepper | Real-time stage-by-stage progress bar driven by WebSocket events |
| Stage Cards | Each agent stage shows status (pending / running / completed / error) |
| Agent Output Renderers | Structured display of each agent's output (requirements, architecture, validation, etc.) |
| Run History | Lists previous pipeline runs with status, filename, and timestamps |
| Review UI | Human validation interface for approve / reject / request changes |

## API Endpoints Used

### RFP Pipeline

```
POST /api/rfp/upload               -- upload RFP, start pipeline
GET  /api/rfp/{rfp_id}/status      -- poll pipeline status
POST /api/rfp/{rfp_id}/approve     -- submit human decision
WS   /api/rfp/ws/{rfp_id}          -- real-time WebSocket progress
GET  /api/rfp/list                 -- list all pipeline runs
GET  /api/rfp/{rfp_id}/checkpoints -- list available checkpoints
POST /api/rfp/{rfp_id}/rerun       -- re-run from a specific agent
```

### Knowledge Base

```
POST   /api/knowledge/upload       -- upload + auto-classify + embed document
POST   /api/knowledge/query        -- semantic search
POST   /api/knowledge/seed         -- seed bundled JSON knowledge data
GET    /api/knowledge/status       -- KB vector count + health
GET    /api/knowledge/files        -- list uploaded KB files
GET    /api/knowledge/policies     -- list extracted policies
POST   /api/knowledge/policies     -- add a policy
PUT    /api/knowledge/policies/:id -- update a policy
DELETE /api/knowledge/policies/:id -- delete a policy
```

## Running

No separate install or build required. Start the FastAPI server:

```bash
# from project root
uvicorn rfp_automation.api:app --reload
```

Dashboard loads at `http://localhost:8000/`.
