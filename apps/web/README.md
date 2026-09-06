# RAGorbit Web — Next.js Frontend

Visual builder for RAG/agentic pipelines. Ports the full functionality of `apps/web-lite/index.html` to a production-grade Next.js 14 app.

## Requirements

- Node 18+ with pnpm (or npm)
- Backend running at `http://127.0.0.1:8000`

## Start the backend

```bash
# From the repo root — stdlib server:
python -m ragorbit serve --port 8000

# Or FastAPI server (requires pip install -e ".[api]"):
uvicorn apps.api.main:app --reload --port 8000
```

## Install and run the frontend

```bash
cd apps/web
pnpm install      # or: npm install
pnpm dev          # or: npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Build for production

```bash
pnpm build
pnpm start
```

## Project structure

```
apps/web/
├── app/
│   ├── layout.tsx       # Root layout, imports globals.css + reactflow styles
│   ├── page.tsx         # Main page: topbar, template gallery, Validate/Run/Export
│   └── globals.css      # Dark theme CSS (matches web-lite)
├── components/
│   ├── Canvas.tsx       # ReactFlow canvas with drag-drop and port validation
│   ├── NodeCard.tsx     # Custom node with input/output Handles per port type
│   ├── Palette.tsx      # Grouped palette (draggable items)
│   └── Inspector.tsx    # Config form (RJSF) + mock result panel
├── lib/
│   ├── api.ts           # fetch wrappers for /api/* endpoints
│   ├── ir.ts            # Flow IR types + toIR/fromIR converters
│   └── store.ts         # Zustand store (registry, templates, nodes, edges)
├── next.config.mjs      # Rewrites /api/* → http://127.0.0.1:8000
├── tsconfig.json
└── package.json
```

## Features

- **Template gallery** — loads 10 example flows from `/api/templates`
- **Palette** — grouped by category, drag to canvas
- **Canvas** — React Flow with custom nodes; handles keyed as `in:Type` / `out:Type`
- **Connection validation** — blocks incompatible port types (same type, Any, or Message↔Query)
- **Inspector** — auto-generated config form via `@rjsf/core` from each node's `configSchema`
- **Validate** — calls `/api/validate`, shows errors / warnings
- **Run mock** — calls `/api/run-mock`, displays response with chips for citations, escalations, tool calls, fanout
- **Export** — calls `/api/generate`, downloads project ZIP
