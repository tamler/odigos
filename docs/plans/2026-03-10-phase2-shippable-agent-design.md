# Phase 2: Shippable Agent — Design Document

**Goal:** Transform Odigos from a functional prototype into a shippable self-hosted personal AI agent with a web interface, plugin system, robust error handling, and deployment options.

**Guiding principles:**
- Single-user, single-process. No multi-tenancy.
- Bare metal first, Docker as an option. No container proliferation.
- Plugin architecture for extensibility. Built-in components use the same interfaces as plugins.
- WebSocket-first for real-time. REST for stateless queries.
- Chat is the primary interface. Dashboard and canvas are secondary views.
- Agent-to-agent communication enables "teams" of individual installs.

---

## 1. Error Recovery Hardening

Before adding new systems, fix the core request path so failures degrade gracefully instead of crashing.

### 1.1 Executor LLM Call (`executor.py`)

Wrap `provider.complete()` in try/catch. On failure, retry once with the fallback model. If both fail, return a graceful message to the user ("I'm having trouble reaching my language model") instead of propagating the exception. The conversation remains intact.

### 1.2 Embedding Failures (`vectors.py`, `manager.py`)

Wrap all embedding operations. If the embedding model fails, the agent still responds — it skips memory storage for that turn and logs a warning. Memory is best-effort, not critical path. The user's message and the agent's response are still saved to the database.

### 1.3 Database Retry (`db.py`)

Add retry with short exponential backoff (3 attempts: 100ms, 200ms, 400ms) for `SQLITE_BUSY` errors. Single-user means contention is rare but possible when the heartbeat and a user message write simultaneously.

### 1.4 Transaction Safety (`reflector.py`, `ingester.py`)

Wrap multi-step operations (entity creation + edge creation + vector storage) in try/catch blocks so partial failures don't leave orphaned data. Use `execute_in_transaction` where possible. Log partial failures clearly for debugging.

---

## 2. Chunking + Vector Memory

### 2.1 Unified Chunking with Chonkie

Replace the current split: naive `_split_paragraphs` fallback, Docling's HybridChunker for documents, and no chunking for conversation messages.

**New approach:** Chonkie as the single chunking library. A `ChunkingService` wraps Chonkie and exposes `chunk(text, content_type) -> list[str]`.

Strategy selection by content type:
- **Messages <500 tokens:** Store as-is (no chunking needed).
- **Long messages/conversations:** `SemanticChunker` — splits on meaning boundaries using the embedding model.
- **Structured documents:** `RecursiveChunker` — hierarchical splitting respecting headings, paragraphs, sentences.
- **Code blocks:** `CodeChunker` — respects function/class boundaries.
- **Plain text (MarkItDown output):** `SentenceChunker` — sentence-level splitting.

Both `MemoryManager.store()` and `DocumentIngester.ingest()` use the `ChunkingService`. One path, consistent quality.

**Dependency:** `chonkie` — 505KB wheel, 49MB installed, supports sentence-transformers and tiktoken (both already in our stack).

### 2.2 ChromaDB Replaces sqlite-vec

Replace sqlite-vec with ChromaDB in embedded mode as the default vector backend.

**Why:**
- sqlite-vec uses brute-force scan (no index). Slows past ~100K vectors.
- No metadata filtering during search.
- Virtual table quirks (raw tuples, can't ALTER, special SQL).

**ChromaDB embedded provides:**
- HNSW index for fast approximate nearest-neighbor search.
- Native metadata filtering (source_type, conversation_id, timestamps).
- Scales to millions of vectors.
- Runs in-process, no separate server.
- Python-native, well-maintained.

**Migration:**
- `VectorMemory` keeps the same interface: `store()`, `search()`. Backend changes internally.
- Remove sqlite-vec extension from `db.py` initialization.
- Remove `memory_vectors` virtual table. Vector data lives in ChromaDB's persistence directory.
- Existing vectors need a one-time migration script (read from sqlite-vec, write to ChromaDB).

**Plugin point:** The vector backend is a swappable provider. ChromaDB is default. Plugins can provide `QdrantVectorBackend`, `PineconeVectorBackend`, etc. implementing the same interface.

---

## 3. Document Processing

### 3.1 MarkItDown as Default

Add Microsoft's MarkItDown as the default document processor. Lightweight Python library that converts documents to Markdown.

**Supported formats:** PDF, Word, PowerPoint, Excel, HTML, images (OCR), audio (transcription), YouTube URLs, CSV, JSON, XML, ZIP, EPUB.

**Uses:**
- Document conversion for the `process_document` tool.
- Conversation export to Markdown.
- Quick file-to-text for LLM consumption.

**Dependency:** `markitdown[all]` — pip-installable, no heavy ML models.

### 3.2 Docling Moves to Plugin

Docling (~1GB+ dependencies) becomes an optional plugin at `plugins/providers/docling/`.

- Base install uses MarkItDown for all document processing. Covers ~80% of use cases.
- Users who need deep PDF extraction (tables, figures, layout analysis, scientific papers) install the docling plugin.
- The `process_document` tool checks if the docling provider is available and escalates when needed.
- `docling` removed from core `pyproject.toml` dependencies.
- This is the first "real" provider plugin, validating the plugin architecture.

---

## 4. REST API

FastAPI routes for the dashboard and external integrations. All routes under `/api/`.

### 4.1 Dashboard Endpoints (read-mostly)

```
GET  /api/conversations              — list/search (pagination, date filter)
GET  /api/conversations/:id          — conversation detail
GET  /api/conversations/:id/messages — message history
GET  /api/conversations/:id/export   — export (JSON or Markdown via MarkItDown)
GET  /api/goals                      — goals list
GET  /api/todos                      — todos list
GET  /api/reminders                  — reminders list
GET  /api/memory/entities            — entity graph (nodes + edges)
GET  /api/memory/search?q=           — semantic memory search
GET  /api/budget                     — spend summary (daily, monthly, by model)
GET  /api/metrics                    — system health (uptime, message count, tool usage)
GET  /api/plugins                    — loaded plugins and status
```

### 4.2 External Endpoints

```
POST /api/message                    — programmatic message submission (webhooks, automations)
```

### 4.3 Authentication

Single API key in config. Passed as `Authorization: Bearer <key>` header. Peer agents each get their own key configured in the peers section.

---

## 5. Unified WebSocket

Single WebSocket endpoint at `/api/ws`. All real-time communication flows through typed JSON messages.

### 5.1 Protocol

```
Connection: WS /api/ws?token=<api_key>

Client -> Server:
  {type: "chat", content: "...", conversation_id: "..."}
  {type: "subscribe", channels: ["status", "events"]}

Server -> Client:
  {type: "chat", content: "...", conversation_id: "...", role: "assistant"}
  {type: "chat_stream", delta: "...", conversation_id: "..."}
  {type: "status", entity: "todo|goal|reminder", action: "created|updated|completed", data: {...}}
  {type: "event", source: "heartbeat|tool|plugin", data: {...}}

Peer Agent <-> Agent:
  {type: "agent", subtype: "message|help_request|knowledge_share|task_delegation", from: "...", data: {...}}
  {type: "agent", subtype: "status", task_id: "...", status: "working|completed|failed", data: {...}}

Future (STT/TTS):
  {type: "audio", format: "pcm16", data: "base64..."}
```

### 5.2 Design Principles

- One WebSocket, typed messages. No proliferation of endpoints.
- REST endpoints for stateless queries. WebSocket for real-time streams.
- The protocol is extensible — new message types don't break existing clients.
- Audio frames are a future message type, not a separate transport.

---

## 6. Web Channel

A `WebChannel` class implementing the `Channel` abstract base class, backed by the WebSocket.

- Registered in `ChannelRegistry` as `"web"`.
- Conversation IDs: `web:<session_id>`.
- `send_message()` pushes to all connected WebSocket clients for that conversation.
- `send_approval_request()` renders an approval UI in the dashboard.
- Messages flow through the same agent pipeline as Telegram — same executor, same tools, same memory.

---

## 7. Plugin Architecture

### 7.1 Extension Points (v1)

Three plugin types, with more added later:

- **Tools** — Adds new tools to the agent's toolkit.
- **Channels** — Adds new communication channels (Discord, Slack, email).
- **Providers** — Swaps or adds LLM providers, embedding providers, vector backends, document processors.

### 7.2 Plugin Loading

Each plugin is a Python module with a `register(ctx)` function:

```python
# plugins/tools/spotify.py
from odigos.tools.base import BaseTool, ToolResult

class SpotifyTool(BaseTool):
    name = "spotify"
    description = "Control Spotify playback"
    parameters_schema = {...}

    async def execute(self, params: dict) -> ToolResult:
        ...

def register(ctx):
    ctx.register_tool(SpotifyTool())
```

The plugin context (`ctx`) exposes: `register_tool()`, `register_channel()`, `register_provider()`. Built-in components use the exact same interfaces — plugins are first-class.

### 7.3 Plugin Config

Each plugin can include a `plugin.yaml` declaring its configuration needs. Users set values in the main `config.yaml` under `plugins.<name>`:

```yaml
plugins:
  spotify:
    client_id: "..."
    client_secret: "..."
```

### 7.4 Discovery and Load Order

On startup, scan the `plugins/` directory. Each subdirectory or `.py` file with a `register()` function gets loaded. Order: providers first, then tools, then channels (channels may depend on providers).

### 7.5 Future Extension Points (D goal)

The `register(ctx)` pattern is designed for extensibility. Future additions:
- `ctx.register_middleware()` — pre/post processing of messages.
- `ctx.register_memory_backend()` — custom memory storage.
- `ctx.register_chunker()` — custom chunking strategies.

These require only adding methods to the context object, not changing the plugin loading mechanism.

---

## 8. Web Dashboard

### 8.1 Tech Stack

- **React + Vite** — SPA, built to static files, served by FastAPI.
- **shadcn/ui** — Component library (includes chat components).
- **Tailwind CSS** — Styling.
- **Excalidraw** — Infinite canvas for visual thinking.
- **Recharts** — Budget and metrics charts.
- **React Router** — Deep linking.

### 8.2 Layout: Three Modes

**Chat mode (default):** Full-width conversational interface. Markdown rendering, tool call display, streaming responses via `chat_stream` WebSocket messages, file upload. Shows peer agent interactions inline as attributed messages. This is where most users live. This is the first impression.

**Dashboard mode:** Monitoring and control view. Split into panels:
- Goals — active goals with progress, linked todos and reminders.
- Budget — daily/monthly spend charts, breakdown by model.
- Activity — live event feed (tool executions, heartbeat actions, plugin events). Always updating.
- Memory — entity graph visualization, semantic search, browse by type.
- Settings — plugin management, peer agent config, personality editor, skill browser, tool configuration (GWS auth, browser setup, etc.).

**Canvas mode:** Excalidraw infinite canvas alongside chat. The agent can render diagrams, entity graphs, project plans. The user can sketch, annotate, organize visually. Shared thinking space between human and agent.

Users switch between modes or split-screen combinations. Chat is always accessible as a collapsible panel in dashboard/canvas modes.

### 8.3 Deep Links

Every view is linkable: `/chat/conv-123`, `/dashboard/goals`, `/canvas/project-456`, `/memory/entity/789`.

### 8.4 Public Pages

The agent gets a `publish_page` tool. Creates pages served at `/public/<slug>`. Two access levels:
- **Public** — open to anyone with the link.
- **Token-protected** — visitor needs a simple token/password the owner shares.

Reports, dashboards, forms, or anything the agent builds with HTML.

### 8.5 First-Run Experience

Setup wizard in the chat. Clean, conversational. "I see Google Workspace isn't configured yet. Want to set it up?" The settings page reflects changes in real-time. No YAML editing required for basic setup.

### 8.6 Build and Serve

`npm run build` in `dashboard/` produces static files in `dashboard/dist/`. FastAPI mounts this directory with a catch-all route. In Docker, the build step runs during image creation. For bare metal, `install.sh` runs the build.

---

## 9. Agent-to-Agent Communication

### 9.1 Phase 1: Manual Peer Config

Each agent declares trusted peers in config:

```yaml
peers:
  - name: "sarah-agent"
    url: "https://sarah.example.com"
    api_key: "shared-secret-123"
```

### 9.2 message_peer Tool

The agent gets a `message_peer` tool to reach out to peers:

```
message_peer(peer: "sarah-agent", message: "Do you know anything about Project X?")
```

The tool sends via WebSocket if a connection is active, falls back to REST (`POST /api/agent/message`).

### 9.3 Message Types

```
message      — plain conversation between agents
help_request — "I don't know how to do X, can you help?"
knowledge_share — push an entity, correction, or memory chunk to a peer
task_delegation — "Research Y and send me the results"
status       — progress updates on delegated tasks
```

### 9.4 UI Visibility

The user sees all peer interactions in their chat, attributed clearly: "I asked sarah-agent about X, they said Y." The activity feed shows peer events. The user never messages external agents directly — they ask their agent to do it.

### 9.5 Future: Discovery Service

Phase 1 is manual config. Later, a lightweight registry (plugin or hosted service) where agents announce themselves and discover peers by name or capability. The message format and auth are designed now so discovery layers on without protocol changes.

### 9.6 Future: Knowledge Sharing and Help

Agents can share knowledge (entities, corrections, memory chunks) and request help. An agent that doesn't know how to do something can ask peers if they have a relevant skill. This works over the same message protocol — just typed payloads.

---

## 10. Deployment

### 10.1 Bare Metal

- `install.sh` — Installs Python deps, builds dashboard (`npm run build`), creates config from template, prompts for API keys, optionally installs CLI tools (gws, agent-browser).
- `odigos.service` — systemd unit template. Runs as user service, auto-restart on failure, `WorkingDirectory` and `ExecStart` configured.
- Config: `~/.config/odigos/config.yaml` or project-local `config.yaml`.
- Data: `~/.local/share/odigos/` (SQLite DB, ChromaDB persistence, plugins, skills) or project-local `data/`.

### 10.2 Docker

- `Dockerfile` — Multi-stage build.
  - Stage 1: Node, builds dashboard static files.
  - Stage 2: Python, copies dashboard dist, installs Python deps, downloads embedding model.
- `docker-compose.yml` — Single service. Volumes for config, data, and plugins.
- `docker compose up` and it works. No external services, no multi-container orchestration.

### 10.3 Both Paths

- Same `config.yaml` format.
- Same plugin directory structure.
- Dashboard at `http://localhost:8000`.
- First-run setup wizard in chat UI — no manual config editing required for basic setup.

---

## Implementation Order

Each layer builds on the previous:

| # | Workstream | Depends On | Key Deliverable |
|---|-----------|-----------|-----------------|
| 1 | Error recovery hardening | — | Graceful degradation on LLM/embedding/DB failures |
| 2 | Chunking + ChromaDB | — | Chonkie integration, ChromaDB replacing sqlite-vec |
| 3 | Document processing | 2 | MarkItDown default, Docling to plugin |
| 4 | Plugin architecture | — | Plugin loader, context, extension points |
| 5 | REST API | — | FastAPI routes for all dashboard data |
| 6 | Unified WebSocket | 5 | Real-time protocol, typed messages |
| 7 | Web channel | 4, 6 | WebChannel class in ChannelRegistry |
| 8 | Dashboard | 5, 6, 7 | React SPA: chat, dashboard, canvas modes |
| 9 | Agent-to-agent | 4, 6 | Peer config, message_peer tool, WS protocol |
| 10 | Deployment | 8 | Dockerfile, docker-compose, systemd, install.sh |

Items 1-4 can be parallelized (no dependencies between them). Items 5-6 can start once the plugin architecture exists. The dashboard (8) is the integration point that pulls everything together.

---

## Dependencies Added

```
chonkie              — Unified chunking (replaces naive splitting)
chromadb             — Embedded vector database (replaces sqlite-vec)
markitdown[all]      — Lightweight document-to-Markdown conversion
websockets           — WebSocket support (if not already via FastAPI)
```

## Dependencies Removed from Core

```
docling              — Moves to optional plugin
sqlite-vec           — Replaced by ChromaDB
```

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Vector DB | ChromaDB embedded | HNSW index, metadata filtering, scales, no server |
| Chunking | Chonkie | Lightweight, fast, semantic+token+code+recursive |
| Document processing | MarkItDown default, Docling plugin | 80/20 — lean base, heavy option available |
| Dashboard framework | React + Vite + shadcn/ui | Standard, flexible, static build |
| Canvas | Excalidraw | Mature whiteboard, hand-drawn aesthetic, React-native |
| Real-time transport | Unified WebSocket | One endpoint, typed messages, future audio-ready |
| Plugin pattern | `register(ctx)` | Extensible, same interfaces as built-in components |
| Deployment | Bare metal + Docker | No forced containerization, both paths supported |
| Multi-user | No. Single-user + agent-to-agent | Each person runs their own instance |
| Workers/threading | Single process, async | Correct for single-user; multi-worker breaks state |
