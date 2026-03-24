# Odigos

Self-hosted personal AI agent with persistent memory, self-improving behavior, and tool creation.

## Tech Stack

- **Backend:** Python 3.12, FastAPI, uvicorn, aiosqlite (SQLite + sqlite-vec)
- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS 4, shadcn/ui, React Router
- **Infra:** Docker Compose, uv (package manager), Makefile
- **Key libs:** sentence-transformers, tiktoken, MCP, scrapling, patchright

## Key Directories

- `odigos/` -- Python package (backend)
  - `core/` -- agent loop, classifier, evolution engine, budget, LLM prompt
  - `api/` -- FastAPI route handlers
  - `tools/` -- agent tools (search, code, scrape, file, MCP bridge, etc.)
  - `memory/` -- vectors, graph, chunking, summarizer, corrections
  - `providers/` -- LLM, search, sandbox, embeddings
  - `channels/` -- web, telegram
  - `skills/` -- code skill validator and registry
  - `personality/` -- dynamic personality/prompt sections
- `dashboard/` -- React/TS frontend (Vite)
- `tests/` -- pytest suite
- `config.yaml` -- runtime config (copy from `config.yaml.example`)
- `migrations/` -- database migrations

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
