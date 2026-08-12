# Odigos

Self-hosted personal AI agent with persistent memory, self-improving behavior, and tool creation.

## Tech Stack

- **Backend:** Python 3.12, FastAPI, uvicorn, aiosqlite (SQLite + sqlite-vec)
- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS 4, shadcn/ui, React Router
- **Infra:** Docker Compose, uv (package manager), Makefile
- **Key libs:** sentence-transformers, tiktoken, MCP, scrapling, httpx, jsonschema

## Key Directories

- `odigos/` -- Python package (backend)
  - `core/` -- agent loop, classifier, evolution engine, budget, LLM prompt
    - `heartbeat/` -- background loop (orchestrator + scheduled, todos, plans, peers, proactive, profiling, maintenance, background, brain_compiler, brain_maintenance, notes_review, subagent_worker, utils)
  - `api/` -- FastAPI route handlers (5 router aggregators: agent, workspace, content, system, media)
  - `tools/` -- agent tools (see hierarchy below); individual tools: search, code, scrape, file, image_gen, music_gen, MCP bridge, etc.
  - `memory/` -- vectors (sqlite-vec), graph (2-hop traversal with relationship paths), chunking, summarizer, corrections
  - `providers/` -- LLM, search, sandbox, embeddings
  - `channels/` -- web, telegram
  - `skills/` -- code skill validator and registry
  - `personality/` -- dynamic personality/prompt sections
- `dashboard/` -- React/TS frontend (Vite)
  - `src/components/chat/` -- extracted chat components (MessageDisplay, ChatInputArea, SuggestedActions, ArtifactGallery, WelcomeView, VoiceModePanel)
  - `src/layouts/` -- AppLayout, AppSidebar, hooks/ (useWebSocketHandler, useConversationActions, useRouteState, useKeyboardShortcuts)
  - `src/stores/` -- Zustand stores (uiStore, chatStore, conversationStore)
- `tests/` -- pytest suite (~1,600 tests)
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
- Skill activation injects a system message mid-run (`executor.py:215`)
- Background task detection (status="pending" → store in tasks table)

Note: the LLM receives the **full** tool registry (`executor.py:310`), not a
classification-filtered subset. Query classification only picks the intelligence
tier; `find_tools` is the discovery mechanism for large registries.

### Heartbeat Background Loop
Package at `odigos/core/heartbeat/` with phases:
- Phase 0: Morning briefing
- Phase 1-1b: Scheduled tasks, legacy reminders
- Phase 2: Todos (headless mode -- plan context instead of chat history)
- Phase 3: Subagent delivery
- Phase 3b-3f: Legacy cron, background task polling (image_gen, music_gen), subagent work
- Phase 4-4e: Peers, email, nudges, followups, plans
- Phase 5-12: Proactive thinking, evolution, profiling, updates, storage

### Memory & RAG
- XSkill experience store: dynamic tool mapping, confidence feedback, automatic pruning
- Multi-hop GraphRAG: 2-hop entity traversal with relationship paths
- Hybrid search: vector (sqlite-vec) + FTS5 + cross-encoder reranking

## Commands

```bash
make up              # docker compose up -d
make down            # docker compose down
make build           # docker compose build
make test            # pytest tests/ -x -q  (NOT `uv run pytest` -- see Notes)
make audit           # pip-audit dependency vulnerability scan
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
- Tests: use `make test` or `.venv/bin/python -m pytest`. `uv run pytest` fails -- pytest lives in the `dev` extra and isn't in the default sync
- Hosted deploys: `bash deploy.sh` (installs are branch-pinned in its `INSTALLS` table, one Unix user each). `deployment.mode=hosted` refuses to boot without working bubblewrap -- confirm `isolation=bwrap` in the startup log, since "active" alone doesn't mean the sandbox came up. See `docs/deployment/`
