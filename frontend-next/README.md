# RFP Responder -- Next.js Frontend

Decoupled frontend for the RFP Response Automation System. Connects to the FastAPI backend via REST and WebSocket APIs.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | Next.js 16 (App Router) |
| Language | TypeScript |
| UI Components | shadcn/ui (Base UI) |
| Styling | Tailwind CSS 4 |
| Icons | Lucide React |
| Typography | Space Grotesk (via Fontsource) |
| Markdown | react-markdown + remark-gfm |
| Diagrams | Mermaid (client-side rendering) |
| Theme | next-themes (light/dark toggle) |

## Pages

| Route | File | Description |
|---|---|---|
| `/` | `app/page.tsx` | RFP upload + live pipeline progress with WebSocket stepper and agent output panels |
| `/review` | `app/review/page.tsx` | Human validation UI -- side-by-side source/response sections, paragraph-level commenting, approve/reject/request changes |
| `/knowledge-base` | `app/knowledge-base/page.tsx` | Knowledge Base management -- upload docs, semantic search, seed data, file listing |
| `/policies` | `app/policies/page.tsx` | Policy CRUD -- list, create, edit, delete extracted company policies |
| `/company-profile` | `app/company-profile/page.tsx` | Company profile editor |
| `/history` | `app/history/page.tsx` | Pipeline run history with status, timestamps, and checkpoint management |

## Components

| Component | File | Description |
|---|---|---|
| Sidebar | `components/sidebar.tsx` | Navigation sidebar with route links |
| Topbar | `components/topbar.tsx` | Top navigation bar with theme toggle |
| Page Shell | `components/page-shell.tsx` | Layout wrapper (sidebar + topbar + content area) |
| Agent Outputs | `components/agent-outputs.tsx` | Structured renderers for each agent's output (requirements table, architecture tree, validation results, etc.) |
| Checkpoints Panel | `components/checkpoints-panel.tsx` | Checkpoint management and pipeline rerun controls |
| Theme Provider | `components/theme-provider.tsx` | next-themes wrapper |
| Theme Toggle | `components/theme-toggle.tsx` | Dark/light mode toggle button |

### UI Primitives (shadcn)

Badge, Button, Card, Dialog, Dropzone, Input, Log Viewer, Scroll Area, Select, Separator, Table, Textarea, Tooltip

## API Client

All backend communication goes through `lib/api.ts`. Types are defined in `lib/types.ts`.

The frontend expects the backend at `http://localhost:8000` (configurable via `NEXT_PUBLIC_API_URL` in `.env`).

## Getting Started

```bash
# 1. Install dependencies
npm install

# 2. Configure backend URL
cp .env.example .env
# Edit .env -- set NEXT_PUBLIC_API_URL if backend is not at localhost:8000

# 3. Start dev server
npm run dev
```

Open `http://localhost:3000` in your browser. The backend must be running at the configured API URL.

## Project Structure

```
frontend-next/
+-- src/
|   +-- app/
|   |   +-- page.tsx              # Home -- upload + pipeline progress
|   |   +-- layout.tsx            # Root layout (Space Grotesk, theme)
|   |   +-- globals.css           # Tailwind + custom CSS variables
|   |   +-- review/page.tsx       # Human validation review UI
|   |   +-- knowledge-base/page.tsx   # KB management
|   |   +-- policies/page.tsx     # Policy CRUD
|   |   +-- company-profile/page.tsx  # Company profile editor
|   |   +-- history/page.tsx      # Run history + checkpoints
|   +-- components/
|   |   +-- sidebar.tsx           # Navigation
|   |   +-- topbar.tsx            # Top bar
|   |   +-- page-shell.tsx        # Layout shell
|   |   +-- agent-outputs.tsx     # Agent output renderers
|   |   +-- checkpoints-panel.tsx # Checkpoint controls
|   |   +-- theme-provider.tsx    # Theme wrapper
|   |   +-- theme-toggle.tsx      # Dark/light toggle
|   |   +-- ui/                   # 13 shadcn primitives
|   +-- lib/
|       +-- api.ts                # Backend API client
|       +-- types.ts              # TypeScript type definitions
|       +-- utils.ts              # Utility functions
+-- public/                       # Static assets
+-- package.json
+-- tsconfig.json
+-- next.config.ts
+-- components.json               # shadcn configuration
```

## Build

```bash
npm run build     # Production build
npm run start     # Start production server
npm run lint      # ESLint check
```
