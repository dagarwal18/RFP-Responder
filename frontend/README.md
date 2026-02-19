# RFP Responder — Frontend

> **Status:** Not started yet (Phase 4 — Week 11 in the implementation plan)

This folder will contain the **Next.js** frontend that talks to the
Python backend API over REST + WebSocket.

## Planned Stack

| Tech | Purpose |
|---|---|
| Next.js 14+ | React framework |
| TypeScript | Type safety |
| Tailwind CSS | Styling |
| WebSocket | Real-time pipeline status updates |

## Planned Pages

| Page | What it does |
|---|---|
| **Upload** | Drag-and-drop RFP file upload |
| **Dashboard** | List all RFP runs with status/filters |
| **Status** | Real-time progress — which agent is running, clickable stages |
| **Approval** | PDF preview + risk summary + Approve/Reject buttons |

## API Endpoints (backend)

The frontend will call these endpoints on the Python backend:

```
GET  /health                  → API health check
POST /api/rfp/upload          → Upload RFP file, start pipeline
GET  /api/rfp/{rfp_id}/status → Poll pipeline status
POST /api/rfp/{rfp_id}/approve → Human approval gate
GET  /api/rfp/list            → List all RFP runs
```

## Deployment

Next.js on **Vercel**, connected to the backend Docker container on EC2.

## Getting Started (when ready)

```bash
cd frontend
npm install
npm run dev        # → http://localhost:3000
```
