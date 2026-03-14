# Odigos

A self-improving AI agent platform. Deploy it as a Docker container, connect an LLM provider, and get a personal AI assistant with a web dashboard that learns and improves over time.

**License:** MIT

---

## What is Odigos?

Odigos is a self-hosted AI agent that connects to any OpenAI-compatible LLM and provides a conversational assistant through a web dashboard. It maintains long-term memory across conversations using vector search and entity graphs. A built-in evolution engine evaluates the agent's own performance and refines its behavior automatically -- no manual prompt tuning required.

## Features

**Core**

- Multi-model LLM support (OpenRouter, OpenAI, Ollama, LM Studio, or any OpenAI-compatible API)
- Primary and fallback model configuration
- Conversation memory with vector search, entity graphs, and automatic summarization
- Web dashboard (React) with real-time WebSocket updates
- SQLite storage -- no external databases required

**Tools**

- Web scraping (Scrapling)
- RSS feed parsing
- Document processing (MarkItDown, optional Docling for deep extraction)
- Code execution (sandboxed, memory-limited, network-restricted by default)
- File management with configurable allowed paths
- Google Workspace integration (Gmail, Calendar, Drive -- via plugin)
- Browser automation (via plugin)
- Web search (SearXNG -- via plugin)
- MCP server bridge -- connect any MCP-compatible tool server

**Intelligence**

- Evolution engine: automatic self-evaluation and prompt refinement over trial periods
- Strategist: autonomous goal-setting and self-direction
- Checkpointing with rollback on regressions
- Corrections manager for learning from mistakes

**Scheduling and Notifications**

- Cron jobs for recurring tasks
- Proactive notifications across channels
- Heartbeat loop for background processing, goal tracking, and idle-time thinking

**Security**

- Approval gates for dangerous tools (code execution, shell, file writes)
- Content filtering for prompt injection
- Sandboxed code execution with memory and timeout limits
- Budget controls (daily and monthly spending caps with warnings)
- API key authentication for dashboard and API access

**Extensibility**

- Plugin system for tools, channels, and providers
- Custom skills (Markdown-defined, hot-reloadable)
- Multi-channel: Web dashboard, Telegram (via plugin)
- MCP server integration

**Multi-Agent**

- Peer-to-peer agent networking over WebSocket with persistent outbox
- Specialist agent spawning with deployment targets
- Cross-agent evaluation routing

## Quick Start

Prerequisites: [Docker](https://docs.docker.com/get-docker/) and an LLM API key (from [OpenRouter](https://openrouter.ai/keys), OpenAI, or a local provider like Ollama).

```bash
git clone https://github.com/tamler/odigos.git && cd odigos
bash install.sh
```

The install script will:

1. Check for Docker and Docker Compose v2
2. Create data directories (`data/`, `skills/`, `plugins/`)
3. Copy `.env.example` to `.env` and generate an API key
4. Walk you through LLM provider selection (OpenRouter, OpenAI, Ollama, LM Studio, or custom)
5. Write `config.yaml` with your settings
6. Pull or build the Docker image and start the container

Once running, open **http://localhost:8000** and log in with the API key shown in the terminal.

## Manual Setup

```bash
cp .env.example .env
# Edit .env -- set LLM_API_KEY and optionally LLM_BASE_URL, LLM_DEFAULT_MODEL
docker compose up -d
```

The compose stack includes:

- **odigos** -- the agent container (FastAPI on port 8000)
- **caddy** -- reverse proxy with automatic HTTPS via Let's Encrypt (set `ODIGOS_DOMAIN` in `.env` for a real domain)

Useful commands:

```bash
docker compose logs -f odigos    # View logs
docker compose restart odigos    # Restart
docker compose down              # Stop
```

## Configuration

Odigos is configured through two files:

- **`.env`** -- Secrets and API keys (never committed). See [`.env.example`](.env.example) for all variables.
- **`config.yaml`** -- Agent settings, model selection, budget limits, tool configuration, peer agents. See [`odigos/config.py`](odigos/config.py) for all available options and defaults.

Key configuration areas:

| Section | What it controls |
|---------|-----------------|
| `llm` | Base URL, default/fallback/background models, temperature, timeouts |
| `budget` | Daily and monthly spending limits (USD) |
| `agent` | Name, role, description, tool turn limits |
| `sandbox` | Code execution timeout, memory limit, network access |
| `approval` | Which tools require human approval before running |
| `evolution` | Trial duration, evaluation thresholds, auto-trial confidence |
| `mcp` | External MCP server connections |
| `peers` | Trusted peer agents for multi-agent networking |

## Plugins

Plugins live in the `plugins/` directory and extend Odigos with optional capabilities.

| Plugin | Category | What it adds |
|--------|----------|-------------|
| SearXNG | Search | Web search via a SearXNG instance |
| Google Workspace | Tools | Gmail, Calendar, Drive access |
| Agent Browser | Tools | Browser automation for web interaction |
| Telegram | Channel | Telegram bot interface |
| Docling | Provider | Deep document extraction (tables, figures, layout) |

Enable plugins by providing their required configuration in the dashboard or `config.yaml`. Restart to apply.

## Skills

Skills are Markdown files in the `skills/` directory that define reusable behaviors. Built-in skills:

- `general-chat.md` -- Default conversational behavior
- `research-deep-dive.md` -- Multi-source research workflow
- `summarize-page.md` / `summarize-doc.md` -- Content summarization
- `google-workspace.md` -- Google Workspace operations
- `agent-browser.md` -- Browser automation tasks
- `tag-conversation.md` -- Conversation categorization

The agent can activate, create, and update skills at runtime.

## Architecture

Odigos runs as a single FastAPI application backed by SQLite.

- **FastAPI** with WebSocket support for real-time communication
- **SQLite** with **sqlite-vec** (vector search) and **FTS5** (full-text search) for all storage
- **sentence-transformers** (nomic-embed-text-v1.5) for local embeddings on CPU
- **Heartbeat loop** drives background processing: goal execution, evolution trials, cron jobs, peer announcements, idle-time thinking
- **Plugin system** with two-phase loading: tools/providers first, then channels (which depend on the agent service)
- **Subagent manager** for spawning focused subtasks within a conversation
- **Tracer** for structured logging of all agent actions and tool calls

## Development

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/)

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Start the server locally
uv run python -m odigos.main

# Run linting
uv run ruff check .
```

Dashboard development:

```bash
cd dashboard
npm install
npm run dev
```

The dashboard is a React app served from `dashboard/dist/` in production.

## License

MIT
