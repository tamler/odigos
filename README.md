<p align="center">
  <img src="docs/images/hero-banner-v2.jpg" alt="Odigos" width="100%">
</p>

<h1 align="center">Odigos</h1>

<p align="center">
  <strong>Self-hosted personal AI agent with persistent memory, self-improving behavior, and tool creation.</strong><br>
  Deploy it on your own hardware, connect any LLM provider, and own your data.
</p>

<p align="center">
  <a href="#installation">Install</a> ·
  <a href="#configuration">Configure</a> ·
  <a href="#usage">Usage</a> ·
  <a href="#features">Features</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#development">Development</a> ·
  <a href="#license">MIT License</a>
</p>

---

## What is Odigos?

A personal AI agent that runs on your machine. It remembers your conversations, learns from its mistakes, builds and saves its own tools, and proactively researches topics you care about. One process, one SQLite database, no cloud dependencies.

**Key differences from ChatGPT/Claude:**
- Your data stays on your machine
- The agent improves itself over time (evolution engine)
- It works proactively when idle (researches, synthesizes, surfaces insights)
- Persistent knowledge stored as durable markdown files (survive database drops)
- Connect any OpenAI-compatible LLM provider

## Requirements

- **LLM API key** from [OpenRouter](https://openrouter.ai/keys), OpenAI, Groq, Ollama, or any OpenAI-compatible provider
- **Docker** (recommended) or **Python 3.12+** with `uv` package manager
- **Node.js 20+** (for building the dashboard)
- **2 CPU, 2GB RAM** for a single agent (4 CPU / 8GB if you want local embeddings). Odigos is designed to be light — a Raspberry Pi 5 or a small VPS is plenty for one person.

## Installation

```bash
git clone https://github.com/tamler/odigos.git && cd odigos
```

### Docker (recommended)

```bash
bash install.sh
```

This builds the container, generates a config file, and starts the service. Follow the prompts to enter your LLM API key and choose a provider.

### Bare metal (Ubuntu, Debian, RHEL, macOS)

```bash
bash install-bare.sh
```

Installs Python dependencies via `uv`, builds the dashboard, creates a systemd service, and starts the agent.

### Manual setup

```bash
# Backend
cp config.yaml.example config.yaml     # Edit with your API key
uv sync                                 # Install Python dependencies

# Frontend
cd dashboard && npm install && npm run build && cd ..

# Run
uv run python -m odigos.main
```

Open **http://localhost:8000**, create your account, and start chatting.

## Configuration

Two files control everything:

### `.env` -- Secrets

```env
LLM_API_KEY=sk-or-v1-your-key-here     # Your LLM provider API key
SESSION_SECRET=random-string-here        # Generated automatically by install script
```

### `config.yaml` -- Everything else

Copy from `config.yaml.example` and edit. Key sections:

```yaml
llm:
  base_url: https://openrouter.ai/api/v1    # LLM provider URL
  default_model: anthropic/claude-sonnet-4   # Primary model
  fallback_model: google/gemini-2.0-flash-001 # Cheaper fallback
  background_model: google/gemini-2.0-flash-001 # For background tasks

agent:
  name: Bob                    # Your agent's name
  max_tool_turns: 8            # Max tool calls per response
  run_timeout_seconds: 120     # Max time per response

budget:
  daily_limit_usd: 5.0         # Daily spending cap
  monthly_limit_usd: 50.0      # Monthly spending cap

proactive:
  enabled: true                # Agent researches topics when idle
  max_cycles_per_hour: 4       # How often it looks for opportunities

email:                         # BYO SMTP/IMAP -- connect your own email
  address: you@gmail.com
  imap_host: imap.gmail.com
  smtp_host: smtp.gmail.com
  username: you@gmail.com
  password: app-specific-password

calendar:                      # BYO CalDAV -- connect your own calendar
  url: https://caldav.google.com/
  username: you@gmail.com
  password: app-specific-password
```

All settings are configurable from the web dashboard under Settings. Changes take effect immediately.

| Section | What it controls |
|---------|-----------------|
| `llm` | Models, temperature, base URL, token limits |
| `budget` | Daily/monthly spending caps |
| `agent` | Name, tool turn limits, timeouts |
| `proactive` | Proactive research toggle and frequency |
| `email` | IMAP/SMTP credentials (Gmail, Outlook, Fastmail, any provider) |
| `calendar` | CalDAV credentials (Google, Apple, Fastmail, Nextcloud) |
| `approval` | Which tools need human sign-off |
| `evolution` | Self-improvement trial duration and thresholds |
| `mesh` | Agent-to-agent mesh networking |
| `voice` | TTS/STT provider and voice selection |
| `auto_update` | Automatic code updates from git |
| `image_generation` | Image creation API |
| `storage` | Per-agent storage quota |

## Usage

### Dashboard

The web dashboard at `http://localhost:8000` has five main sections:

- **Activity** -- what the agent is doing: proactive findings, morning briefings, task completions
- **Chat** -- conversations with the agent, streaming responses, file uploads, voice I/O
- **Notebook** -- markdown notebooks with journal mode and agent integration
- **Todo** -- kanban boards with drag-and-drop for task management
- **Documents** -- file artifacts the agent has created (CSV, DOCX, Markdown, etc.)

### Talking to the agent

Just chat naturally. The agent has 45+ tools and discovers the right one automatically:

- "Research the competitive landscape for X" -- deep research with sources
- "Remember that I prefer Python" -- stores as an explicit fact
- "Check my email" -- reads your inbox (requires email config)
- "Create a kanban board for the project" -- builds a board with columns and cards
- "Generate an image of a sunset" -- creates images via API
- "What did we discuss yesterday?" -- searches conversation history

### Proactive behavior

When idle, the agent:
- Scans recent conversations for topics worth exploring
- Checks its knowledge for gaps and unresolved questions
- Researches opportunities and writes findings to the Activity page
- Sends push notifications when it finds something interesting

Control this from Settings > Proactive (toggle on/off, adjust frequency).

### Email and calendar

Connect your own email (IMAP/SMTP) and calendar (CalDAV) in Settings. The agent checks for new mail and upcoming events, includes them in morning briefings, and can send replies on your behalf.

Supported providers: Gmail, Outlook, Fastmail, iCloud, Nextcloud, any standard IMAP/SMTP or CalDAV.

### Mobile

Install as a PWA -- "Add to Home Screen" on mobile or desktop. Push notifications reach you when the app is closed. Biometric login via WebAuthn passkeys.

### Telegram

Connect a Telegram bot for mobile chat. Configure the bot token in Settings > Plugins.

### API

All functionality is available via REST API with API key authentication:

```bash
# Send a message
curl -X POST http://localhost:8000/api/chat \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello"}'

# List notifications
curl http://localhost:8000/api/notifications \
  -H "Authorization: Bearer YOUR_API_KEY"
```

## Project Structure

```
odigos/
  core/           Agent loop, classifier, evolution engine, budget, LLM prompts
    heartbeat/    Background loop (orchestrator, proactive, profiling, maintenance)
  api/            FastAPI route handlers
  tools/          Agent tools (search, code, scrape, file, image, music, MCP)
  memory/         Vectors (sqlite-vec), entity graph, brain writer/reader, chunking
  providers/      LLM, search, sandbox, embeddings
  channels/       Web, Telegram channel adapters
  skills/         Skill validator and registry
  personality/    Dynamic personality/prompt sections
dashboard/        React/TypeScript frontend (Vite, Tailwind, shadcn/ui)
data/
  brain/          Compiled knowledge -- entity pages, topics, synthesis, conversations
  sources/        Archived external content (articles, documents)
  agent/          Agent identity, capabilities, diary
tests/            pytest suite (95+ tests)
schema.sql        Database schema (single source of truth)
config.yaml       Runtime configuration
```

## Features

### Memory

The agent has a layered memory system:

- **Brain** (`data/brain/`) -- compiled knowledge as durable markdown files. Entity pages, topic indexes, synthesized insights. Survives database drops.
- **Vector memory** -- all messages and documents embedded locally (nomic-embed-text-v1.5) with hybrid retrieval (vector + FTS5 + cross-encoder reranking)
- **Explicit facts** -- "remember that I prefer Python" stored and injected into every conversation
- **User profile** -- built automatically from conversation analysis during idle time
- **Entity graph** -- people, tools, concepts tracked with typed relationships and multi-hop traversal
- **Tactical experiences** -- tool successes/failures stored with lessons, confidence-scored, auto-pruned

### Self-Improvement

The evolution engine runs continuously: classify every query, evaluate every response, propose experiments, run time-boxed trials, promote what works, revert what doesn't. Classification rules, routing, prompt sections, and skills all evolve.

### Proactive Agent

A 4-stage pipeline (scan, prioritize, execute, publish) replaces passive idle time. The agent scans for knowledge gaps, conversation topics worth exploring, and goal progress opportunities. Findings are written as markdown artifacts and surfaced on the Activity page with push notifications.

### Tools

45+ tools organized in a type hierarchy: `APITool` (HTTP APIs with polling and retry), `CLITool` (subprocess with input hardening), and local tools. The smart tool registry uses JIT schema injection -- only relevant tools are loaded per query, not all 45.

### Security

- Session-based auth with HTTP-only cookies and API keys
- Sandboxed code execution (bubblewrap isolation, memory/timeout limits)
- Path containment on all file operations
- Prompt injection defense (multi-layer: regex, NLP, structural separation, canary tokens)
- SSRF protection (private IP ranges blocked)
- Budget controls (daily/monthly spending caps)

## Architecture

One process. One SQLite database. No microservices.

- **Backend:** Python 3.12, FastAPI, uvicorn, aiosqlite
- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS 4, shadcn/ui
- **Database:** SQLite with sqlite-vec (vector search) and FTS5 (full-text search)
- **Embeddings:** nomic-embed-text-v1.5 on CPU (no API calls)
- **Reranking:** ms-marco-MiniLM cross-encoder
- **Package manager:** uv (Python), npm (frontend)

Everything runs on a single VPS. One agent is comfortable on 2 CPU / 2GB; a host running 15+ agents side-by-side wants 4 CPU / 16GB.

## Commands

```bash
# Docker
make up              # Start
make down            # Stop
make build           # Rebuild
make logs            # View logs

# Bare metal
uv sync              # Install dependencies
uv run pytest        # Run tests
uv run python -m odigos.main   # Start
cd dashboard && npm run dev    # Frontend dev server
cd dashboard && npm run build  # Production build
```

## Updating

```bash
git pull
cd dashboard && npm run build && cd ..
# Docker: make build && make up
# Bare metal: systemctl restart odigos
```

Or enable auto-updates: set `auto_update.enabled: true` in config.yaml.

## Development

```bash
uv sync                        # Install Python dependencies
cd dashboard && npm install    # Install frontend dependencies
uv run pytest                  # Run tests
cd dashboard && npm run dev    # Frontend dev server (hot reload)
uv run python -m odigos.main   # Start backend
```

Linting: `ruff check odigos/` (line-length 100, target py312)

## Acknowledgments

Built on research from: [AREW](https://arxiv.org/abs/2603.12109) (active reasoning critique), [SAGE](https://arxiv.org/html/2512.17102v2) (executable skills), [XSkill](https://arxiv.org/html/2603.12056v2) (experience learning), [Omni-SimpleMem](https://arxiv.org/html/2604.01007v2) (memory architecture), [HERA](https://arxiv.org/html/2604.00901v2) (experience library), [EvoSkills](https://arxiv.org/html/2604.01687v1) (self-evolving skills), [Karpathy LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) (knowledge persistence), [NLAH](https://arxiv.org/html/2603.25723v1) (execution contracts), [Paperclip](https://github.com/paperclipai/paperclip) (autonomous behavior), [Hyperagents](https://arxiv.org/abs/2603.19461) (meta-improvement), [Anthropic Harness Design](https://www.anthropic.com/engineering/harness-design-long-running-apps) (evaluator architecture).

## License

MIT
