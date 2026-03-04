# Phase 0 Design: The Skeleton

**Date:** 2026-03-04
**Status:** Approved
**Milestone:** "Send a message on Telegram, get an LLM response"

---

## Scope

Build the minimal viable skeleton for Odigos. Hit the Phase 0 acceptance criteria from the PRD:
- Telegram bot receives and responds to text messages
- Responses come from an LLM via OpenRouter (model selectable via config)
- Conversations are stored in SQLite
- Config is driven by `.env` + `config.yaml`, no hardcoded values

### Deferred to later phases
- Local Qwen3.5-9B via llama.cpp (needs VPS, deployment complexity)
- Free model pool manager (optimization, add once basic routing works)
- Inline keyboard framework (needed for Phase 2 approvals)
- Full schema (entities, edges, vectors, tasks — build when features need them)
- systemd service file (deployment concern)

---

## Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Build tool | uv | Fast, modern, handles virtualenv + deps + lockfile |
| DB access | aiosqlite + thin helper | Async required (event loop), raw SQL, no ORM |
| Web framework | FastAPI + uvicorn | Webhook endpoint, /health, async event loop |
| Testing | pytest + pytest-asyncio | Standard, async support |
| Agent loop | Three-step skeleton (planner/executor/reflector) | Architecture ready for Phase 1, stubs for now |
| HTTP client | httpx | Async, modern, well-maintained |

---

## Project Structure

```
odigos/
├── pyproject.toml
├── .env.example
├── config.yaml.example
├── .gitignore
├── .python-version
│
├── odigos/
│   ├── __init__.py
│   ├── main.py                   # Entry point: FastAPI + Telegram bot
│   ├── config.py                 # .env + config.yaml -> typed dataclass
│   ├── db.py                     # aiosqlite: connection, migrations, helpers
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── agent.py              # Main loop: plan -> execute -> reflect
│   │   ├── planner.py            # Phase 0: pass-through to LLM
│   │   ├── executor.py           # Phase 0: call LLM, return response
│   │   ├── reflector.py          # Phase 0: store message, no-op learning
│   │   └── context.py            # Build prompt from history
│   │
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py               # Provider ABC + LLMResponse
│   │   └── openrouter.py         # OpenRouter via httpx
│   │
│   └── channels/
│       ├── __init__.py
│       ├── base.py               # Channel ABC + UniversalMessage
│       └── telegram.py           # python-telegram-bot v21+
│
├── migrations/
│   └── 001_initial.sql
│
├── data/
│   └── .gitkeep
│
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_config.py
    ├── test_db.py
    ├── test_core.py
    └── test_providers.py
```

---

## Configuration

### `.env` (secrets only)

```
TELEGRAM_BOT_TOKEN=...
OPENROUTER_API_KEY=...
```

### `config.yaml` (everything else)

```yaml
agent:
  name: "Odigos"

database:
  path: "data/odigos.db"

openrouter:
  default_model: "anthropic/claude-3.5-sonnet"
  fallback_model: "google/gemini-2.0-flash-001"
  max_tokens: 4096
  temperature: 0.7

telegram:
  mode: "polling"       # "polling" or "webhook"
  webhook_url: ""       # required if mode is "webhook"

server:
  host: "0.0.0.0"
  port: 8000
```

Loaded via `config.py` into a pydantic-settings model. Immutable after startup.

---

## Database

Phase 0 schema (001_initial.sql):

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    started_at TEXT DEFAULT (datetime('now')),
    last_message_at TEXT,
    message_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT,
    model_used TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_usd REAL,
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_messages_conversation ON messages(conversation_id);
CREATE INDEX idx_messages_timestamp ON messages(timestamp);
```

`db.py` provides:
- `get_db()` — async context manager for connection
- `run_migrations()` — scans migrations/, applies in order, tracks in `_migrations` table
- `execute()`, `fetch_one()`, `fetch_all()` helpers

---

## Agent Core

### Flow

```
UniversalMessage -> agent.py -> planner -> executor -> reflector -> response
```

### agent.py
- Receives UniversalMessage from channel
- Finds or creates conversation in SQLite
- Stores the user message
- Calls planner -> executor -> reflector pipeline
- Returns response string

### planner.py (Phase 0 stub)
- Takes message + conversation history
- Returns a Plan object: `{action: "respond", requires_tools: false}`
- No intent classification or tool selection

### executor.py (Phase 0)
- Takes the Plan
- Uses context.py to build the message list (system prompt + history + current message)
- Calls the OpenRouter provider
- Returns the LLM response

### reflector.py (Phase 0 stub)
- Stores the assistant message in SQLite
- Returns the response unchanged
- No learning or correction tracking

### context.py
- Builds the messages array for the LLM call
- System prompt: agent name + basic instruction
- Conversation history: last N messages (configurable, default 20)
- Current user message

---

## OpenRouter Provider

### base.py

```python
@dataclass
class LLMResponse:
    content: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float

class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, messages: list[dict], **kwargs) -> LLMResponse: ...
```

### openrouter.py
- httpx.AsyncClient for async HTTP
- Calls `/chat/completions` (OpenAI-compatible)
- Extracts token counts and cost from response
- Error handling: retry on 429 with Retry-After, timeout after 30s
- Falls back to `fallback_model` if primary fails
- Sends required HTTP-Referer and X-Title headers

---

## Telegram Channel

### base.py

```python
@dataclass
class UniversalMessage:
    id: str
    channel: str
    sender: str
    content: str
    timestamp: datetime
    metadata: dict

class Channel(ABC):
    async def start(self): ...
    async def stop(self): ...
```

### telegram.py
- python-telegram-bot v21+ (async)
- Registers handler for text messages
- Converts Telegram Update -> UniversalMessage
- Calls agent, sends response
- Typing indicator while agent thinks
- Supports polling (local dev) and webhook (production) modes

---

## Entry Point (main.py)

Startup sequence:
1. Load config (.env + config.yaml)
2. Initialize database + run migrations
3. Create OpenRouter provider
4. Create agent (planner, executor, reflector, context assembler)
5. Create Telegram channel with agent reference
6. Start FastAPI (with /health endpoint) + Telegram bot
7. Graceful shutdown on SIGINT/SIGTERM

---

## Dependencies

```
python = ">=3.12"
fastapi
uvicorn
httpx
aiosqlite
python-telegram-bot = ">=21.0"
pydantic-settings
pyyaml

# dev
pytest
pytest-asyncio
```
