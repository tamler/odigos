<p align="center">
  <img src="docs/images/hero-banner-v2.jpg" alt="Odigos" width="100%">
</p>

<h1 align="center">Odigos</h1>

<p align="center">
  <strong>Self-hosted personal AI agent with persistent memory, self-improving behavior, and autonomous sub-agents.</strong><br>
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

A personal AI agent that runs on your machine. It remembers your conversations, learns from its mistakes, builds and saves its own tools, dispatches specialist sub-agents for heavy work, and proactively researches topics you care about. One process, one SQLite database, no cloud dependencies.

**Key differences from ChatGPT/Claude:**
- Your data stays on your machine
- The agent improves itself over time (evolution engine)
- It dispatches specialist sub-agents for research, coding, analysis, and presentations
- It works proactively when idle (researches, synthesizes, compiles knowledge)
- Persistent knowledge stored as durable markdown files (survive database drops)
- Structured memory with typed records, bidirectional links, and evolution
- Connect any OpenAI-compatible LLM provider

## Requirements

- **LLM API key** from [OpenRouter](https://openrouter.ai/keys), OpenAI, Groq, Ollama, or any OpenAI-compatible provider
- **Docker** (recommended) or **Python 3.12+** with `uv` package manager
- **Node.js 20+** (for building the dashboard)
- **1 CPU, 1GB RAM** for a single agent. Odigos is designed to be light — a Raspberry Pi or a tiny VPS is enough for one person.

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

### `.env` -- Secrets only

```env
OPENROUTER_API_KEY=sk-or-v1-your-key-here   # Referenced from config.yaml
SESSION_SECRET=random-string-here            # Generated automatically by install
```

Add one env var per LLM provider you want to use (e.g. `OPENAI_API_KEY`,
`GROQ_API_KEY`). The providers block in `config.yaml` references these by name.

### `config.yaml` -- Everything else

Copy from `config.yaml.example` and edit. The LLM layer is three parts:

```yaml
providers:                              # Each OpenAI-compatible endpoint, one entry
  openrouter:
    base_url: "https://openrouter.ai/api/v1"
    api_key: "${OPENROUTER_API_KEY}"    # Resolved from .env at load time

models:                                 # Each model, with its costs + capabilities
  scout:
    provider: openrouter
    id: "meta-llama/llama-4-scout"
    cost_in_per_mtok: 0.08
    cost_out_per_mtok: 0.30
    vision: true
    context_window: 131072
  deepseek-v3.2:
    provider: openrouter
    id: "deepseek/deepseek-v3.2"
    cost_in_per_mtok: 0.27
    cost_out_per_mtok: 1.10

llm:                                    # Intelligence-tier routing
  fast: scout                           # Default — most tasks
  smart: deepseek-v3.2                  # Reasoning / planning / document queries
  background: scout                     # Heartbeat / background loops
  fallback: scout                       # Safety net on primary failure
  auto_route: true                      # Classifier picks fast vs smart by task

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

- **Activity** -- live hub showing what the agent is doing, goals, plans, budget, todos, and recent findings
- **Chat** -- conversations with the agent, streaming responses, file uploads, voice I/O
- **Notebook** -- markdown notebooks with agent review sidecar (the agent comments on your writing)
- **Todo** -- kanban boards with drag-and-drop for task management
- **Documents** -- file artifacts the agent has created (CSV, DOCX, Markdown, presentations)

### Talking to the agent

Just chat naturally. The agent has 50+ tools and discovers the right one automatically:

- "Research the competitive landscape for X" -- dispatches a researcher sub-agent, delivers findings
- "Make me a 5-slide primer on Y" -- researcher gathers info, presenter formats Marp slides, renders PDF
- "Remember that I prefer Python" -- stores as a typed memory (preference)
- "Check my email" -- reads your inbox (requires email config)
- "Create a kanban board for the project" -- builds a board with columns and cards
- "Generate an image of a sunset" -- creates images via API
- "What did we discuss yesterday?" -- searches structured memory with type-filtered retrieval

### Sub-agents

The orchestrator dispatches specialist sub-agents for heavy work:

| Persona | What it does |
|---------|-------------|
| **researcher** | Deep research with web search, source citing, cross-referencing |
| **coder** | Code generation, review, and testing |
| **editor** | Text editing, refinement, and restructuring |
| **analyst** | Data analysis, synthesis, and quantified insights |
| **summarizer** | Fast summarization of long content |
| **presenter** | Marp slide generation from research or content |
| **brain-compiler** | Compiles memories into interlinked wiki articles |

Sub-agents run asynchronously in the background. The main agent responds immediately ("On it, I'll ping you when ready") and delivers results via notification when complete. Sub-agents can chain: researcher -> presenter produces a research report then formats it as slides automatically.

### Proactive behavior

When idle, the agent:
- Scans recent conversations for topics worth exploring
- Reviews shared notebooks and adds anchored observations
- Compiles accumulated knowledge into interlinked wiki articles
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
  core/           Agent loop, classifier, evolution engine, budget, sub-agent orchestration
    heartbeat/    Background loop (orchestrator, proactive, profiling, brain compiler, sub-agent worker)
    subagent.py   SubagentManager — dispatch, execute, chain, deliver
  api/            FastAPI route handlers
  tools/          Agent tools (search, code, scrape, file, image, music, marp, MCP, sub-agent dispatch)
  memory/         Structured memories (9 types), entity graph, brain writer/reader, chunking, evolution
  providers/      LLM, search, sandbox, embeddings
  channels/       Web, Telegram channel adapters
  skills/         Skill validator and registry (with personality-preserving activation)
  personality/    Dynamic personality/prompt sections (operational rules, behavioral principles)
dashboard/        React/TypeScript frontend (Vite, Tailwind, shadcn/ui)
data/
  brain/          Compiled knowledge — entity pages, concept articles, cross-linked wiki
  subagents/      Sub-agent persona definitions (researcher, coder, editor, analyst, etc.)
  sources/        Archived external content (articles, documents)
  agent/          Agent identity, capabilities, behavioral principles, operational rules
  prompts/        LLM prompt templates for classification, verification, consolidation, review
tests/            pytest suite (140+ tests)
schema.sql        Database schema (single source of truth)
config.yaml       Runtime configuration
```

## Features

### Structured Memory

The agent has a three-layer knowledge system:

**Memory layer** (user-facing knowledge, valuable forever):
- **Structured memories** -- 9 types (fact, preference, task, idea, entity, summary, general) with keywords, tags, context descriptions, and bidirectional links between related memories
- **Hybrid retrieval** -- vector search (sqlite-vec) + FTS5 keyword search + cross-encoder reranking, with type-filtered routing per query classification and recency decay
- **Memory evolution** -- heartbeat phase that refines memories when new related content arrives, supersedes outdated records, and synthesizes high-connectivity memories into higher-order insights
- **Entity graph** -- people, tools, concepts tracked with typed relationships and multi-hop traversal

**Brain layer** (compiled knowledge, durable markdown):
- **Brain compiler** -- 5-pass LLM compilation (scan, extract concepts, generate articles, cross-link, prune stale) dispatched as a background sub-agent when enough new content accumulates
- **Concept articles** -- cross-cutting themes synthesized from multiple entities and memories, with bidirectional links and source citations
- **Entity pages** -- auto-generated from the entity graph, enriched by the compiler with cross-references
- Everything in `data/brain/` is plain markdown -- browseable in Obsidian, VS Code, or any text editor

**Self-improvement layer** (agent operational, prunable):
- **Tactical experiences** -- tool successes/failures stored with lessons, confidence-scored, auto-pruned
- **Corrections** -- user feedback consolidated into behavioral principles and operational rules via two-axis prompt evolution
- **Surrogate skill verifier** -- validates skill quality via isolated LLM evaluation with escalation loop

### Sub-Agent Orchestration

The main agent (orchestrator) dispatches specialist sub-agents for heavy work. Sub-agents run asynchronously with their own persona, tool whitelist, model, and isolated context. Results are delivered via notification when complete.

- **Async-by-default** -- main agent responds immediately, sub-agent works in background
- **Per-pool concurrency** -- bounded parallelism (default: 3, research: 2, heavy: 1)
- **On-complete chaining** -- researcher -> presenter workflows execute automatically
- **On-failure recovery** -- failed tasks can dispatch graceful fallback sub-agents
- **Recursion prevention** -- sub-agents cannot invoke other sub-agents
- **Budget gating** -- sub-agent work respects the budget circuit breaker

### Self-Improvement

The evolution engine runs continuously: classify every query, evaluate every response, propose experiments, run time-boxed trials, promote what works, revert what doesn't. Classification rules, routing, prompt sections, and skills all evolve.

Corrections from user feedback are consolidated into two personality sections:
- **Operational rules** -- concrete "do X not Y" fixes from recent corrections
- **Behavioral principles** -- stable identity patterns generalized across interactions

### Proactive Agent

A 4-stage pipeline (scan, prioritize, execute, publish) replaces passive idle time. The agent scans for knowledge gaps, conversation topics worth exploring, and goal progress opportunities. Findings are written as markdown artifacts and surfaced on the Activity page with push notifications.

The notebook review system scans shared notebooks during idle time and adds anchored observations referencing specific quoted text, visible in a sidebar panel.

### Tools

50+ tools organized in a type hierarchy: `APITool` (HTTP APIs with polling and retry), `CLITool` (subprocess with input hardening), and local tools. The smart tool registry uses JIT schema injection -- only relevant tools are loaded per query, not all 50+.

Includes: web search, code execution, file I/O, image generation, music generation, Marp slide rendering, scraping, MCP bridge, email, calendar, kanban, notebook, sub-agent dispatch.

### Security

- Session-based auth with HTTP-only cookies and API keys
- Sandboxed code execution (bubblewrap isolation, memory/timeout limits)
- Path containment on all file operations (sub-agents get per-task workspace roots)
- Prompt injection defense (multi-layer: regex, NLP, structural separation, canary tokens)
- SSRF protection (private IP ranges blocked)
- Budget controls (daily/monthly spending caps, sub-agent budget gating)

## Architecture

One process. One SQLite database. No microservices.

- **Backend:** Python 3.12, FastAPI, uvicorn, aiosqlite
- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS 4, shadcn/ui
- **Database:** SQLite with sqlite-vec (vector search) and FTS5 (full-text search)
- **Embeddings:** nomic-embed-text-v1.5 on CPU (no API calls)
- **Reranking:** ms-marco-MiniLM cross-encoder
- **Package manager:** uv (Python), npm (frontend)

Everything runs on a single VPS. One agent is comfortable on 1 CPU / 1GB; a host running 15+ agents side-by-side wants 4 CPU / 16GB.

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

Built on research from: [A-MEM](https://arxiv.org/abs/2502.12110) (Zettelkasten memory), [sage-wiki](https://github.com/xoai/sage-wiki) (wiki compilation), [HERA](https://arxiv.org/html/2604.00901v2) (prompt evolution), [EvoSkills](https://arxiv.org/html/2604.01687v1) (skill verification), [ReVeal](https://arxiv.org/html/2506.11442v1) (self-verification), [Mem^p](https://arxiv.org/html/2508.06433v2) (procedural memory), [AnchoredAI](https://arxiv.org/html/2509.16128v1) (anchored feedback), [AREW](https://arxiv.org/abs/2603.12109) (active reasoning), [SAGE](https://arxiv.org/html/2512.17102v2) (executable skills), [XSkill](https://arxiv.org/html/2603.12056v2) (experience learning), [Omni-SimpleMem](https://arxiv.org/html/2604.01007v2) (memory architecture), [Anthropic Harness Design](https://www.anthropic.com/engineering/harness-design-long-running-apps) (evaluator architecture), [npcpy](https://github.com/NPC-Worldwide/npcpy) (agent orchestration), [botctl](https://github.com/montanaflynn/botctl) (agent management), [jot](https://github.com/badlogic/jot) (inline comment threads).

## License

MIT
