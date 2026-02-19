# RFP Responder — Frontend

> **Status:** ✅ Implemented — single-page vanilla JS dashboard served by FastAPI

The frontend is a single HTML file (`index.html`) with inline CSS and JavaScript.  
FastAPI serves it at `GET /` so there is no separate build step or dev server.

## Architecture

| Aspect | Detail |
|---|---|
| Framework | None — vanilla HTML / CSS / JS |
| Served by | FastAPI `StaticFiles` + `FileResponse` at `/` |
| Real-time | WebSocket (`/api/rfp/ws/{rfp_id}`) for live pipeline progress |
| Fallback | Polling `/api/rfp/{rfp_id}/status` with pause/resume support |
| Styling | Embedded CSS with CSS variables for theming |

## Layout

The dashboard is split into two panels:

### Left Panel — Knowledge Base

| Feature | Description |
|---|---|
| **Document Upload** | Drag-and-drop or click to upload PDF/DOCX/JSON/CSV files |
| **Auto-Classification** | Regex keyword scoring assigns a `doc_type` badge automatically |
| **Uploaded Files** | Lists all uploaded files with name, doc type, vector count, and timestamp |
| **Query** | Search the knowledge base with an optional `doc_type` filter dropdown |
| **Seed & Status** | Seed bundled knowledge data and check KB vector count |

### Right Panel — RFP Pipeline

| Feature | Description |
|---|---|
| **RFP Upload** | Drag-and-drop or click to upload an RFP document |
| **WebSocket Stepper** | Real-time stage-by-stage progress bar driven by WebSocket events |
| **Stage Cards** | Each agent stage shows status (pending / running / completed / error) |
| **Run History** | Lists previous pipeline runs with status, filename, and timestamps |

## API Endpoints Used

### RFP Pipeline

```
POST /api/rfp/upload               → Upload RFP + start pipeline in background thread
GET  /api/rfp/{rfp_id}/status      → Poll pipeline status (fallback)
WS   /api/rfp/ws/{rfp_id}          → WebSocket real-time progress stream
GET  /api/rfp/list                 → List all pipeline runs
```

### Knowledge Base

```
POST /api/knowledge/upload         → Upload + auto-classify + embed document
GET  /api/knowledge/query          → Semantic search (?q=...&doc_type=...)
POST /api/knowledge/seed           → Seed bundled JSON knowledge data
GET  /api/knowledge/status         → KB vector count + health
GET  /api/knowledge/files          → List uploaded KB files
```

## Running

No separate install or build is required. Start the FastAPI server and
open your browser:

```bash
# from project root
python -m rfp_automation          # → http://localhost:8000
```

The frontend loads automatically at `http://localhost:8000/`.
