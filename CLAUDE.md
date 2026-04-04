# Odigos

Self-hosted personal AI agent with persistent memory, self-improving behavior, and tool creation.

## Tech Stack

- **Backend:** Python 3.12, FastAPI, uvicorn, aiosqlite (SQLite + sqlite-vec)
- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS 4, shadcn/ui, React Router
- **Infra:** Docker Compose, uv (package manager), Makefile
- **Key libs:** sentence-transformers, tiktoken, MCP, scrapling, patchright, httpx, jsonschema

## Key Directories

- `odigos/` -- Python package (backend)
  - `core/` -- agent loop, classifier, evolution engine, budget, LLM prompt
    - `heartbeat/` -- background loop (9-module package: orchestrator, scheduled, todos, plans, peers, idle, profiling, maintenance, background, utils)
  - `api/` -- FastAPI route handlers (5 router aggregators: agent, workspace, content, system, media)
  - `tools/` -- agent tools with type hierarchy:
    - `base.py` -- BaseTool, ToolResult (with status/task_id for background tasks), auto_distill, format_for_context
    - `api_tool.py` -- APITool base class (shared httpx client, api_post/get, poll_until, poll_once)
    - `cli_tool.py` -- CLITool base class (subprocess execution, input hardening, JSON-first output)
    - Individual tools: search, code, scrape, file, image_gen, music_gen, MCP bridge, etc.
  - `memory/` -- vectors (sqlite-vec), graph (2-hop traversal with relationship paths), chunking, summarizer, corrections
  - `providers/` -- LLM, search, sandbox, embeddings
  - `channels/` -- web, telegram
  - `skills/` -- code skill validator and registry
  - `personality/` -- dynamic personality/prompt sections
- `dashboard/` -- React/TS frontend (Vite)
  - `src/components/chat/` -- extracted chat components (MessageDisplay, ChatInputArea, SuggestedActions, ArtifactGallery, WelcomeView, VoiceModePanel)
  - `src/layouts/` -- AppLayout, AppSidebar, hooks/ (useWebSocketHandler, useConversationActions, useRouteState, useKeyboardShortcuts)
  - `src/stores/` -- Zustand stores (uiStore, chatStore, conversationStore)
- `tests/` -- pytest suite (95+ tests)
- `config.yaml` -- runtime config (copy from `config.yaml.example`)
- `migrations/` -- database migrations
- `docs/superpowers/specs/` -- design specs
- `docs/superpowers/plans/` -- implementation plans

## Architecture

### Tool Type Hierarchy
```
BaseTool (abstract) -- format_for_context(), auto_distill fallback
  ├── APITool -- shared httpx client, api_post/get, poll_until, poll_once
  │     ├── GenerateImageTool (backgroundable)
  │     └── GenerateMusicTool (backgroundable)
  ├── CLITool -- subprocess, input hardening, JSON-first
  └── Local tools -- code, file, notebook, kanban, etc.
```

### Executor Features
- Pre-call parameter validation (type coercion + jsonschema)
- Post-call observation filtering (format_for_context + auto_distill)
- XSkill experience feedback (confidence adjustment on tool outcomes)
- JIT tool schema injection (auto-inject relevant tools from classification)
- Background task detection (status="pending" → store in tasks table)

### Heartbeat Background Loop
Package at `odigos/core/heartbeat/` with phases:
- Phase 0: Morning briefing
- Phase 1-1b: Scheduled tasks, legacy reminders
- Phase 2: Todos (headless mode -- plan context instead of chat history)
- Phase 3: Subagent delivery
- Phase 3b: Legacy cron
- Phase 3c: Background task polling (image_gen, music_gen)
- Phase 4-4e: Peers, email, nudges, followups, plans
- Phase 5-12: Idle thinking, evolution, profiling, updates, storage

### Memory & RAG
- XSkill experience store: dynamic tool mapping, confidence feedback, automatic pruning
- Multi-hop GraphRAG: 2-hop entity traversal with relationship paths
- Hybrid search: vector (sqlite-vec) + FTS5 + cross-encoder reranking

## Commands

```bash
make up              # docker compose up -d
make down            # docker compose down
make build           # docker compose build
make test            # pytest tests/ -x -q
make logs            # tail odigos container logs
cd dashboard && npm run dev    # frontend dev server
cd dashboard && npm run build  # production build
```

## Notes

- Entry point: `odigos/main.py` (also `odigos` CLI via pyproject.toml scripts)
- Config: `config.yaml` (LLM provider, budget, features, sandbox, MCP servers)
- Linting: ruff (line-length 100, target py312)
- Frontend patterns: use `@/lib/api` helpers, lucide-react icons, sonner toasts
- New API tools: extend `APITool` from `odigos/tools/api_tool.py`, implement `execute()` and optionally `complete_background()` for backgroundable tools
- New CLI tools: extend `CLITool` from `odigos/tools/cli_tool.py`, use `run_cli()` or `run_json()`
- Headless execution: heartbeat uses `build_headless()` for plan/todo steps (selective context, ~67% token savings)
