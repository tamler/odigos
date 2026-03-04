# Phase 0: Skeleton Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the minimal Odigos skeleton — send a Telegram message, get an LLM response via OpenRouter, persist the conversation in SQLite.

**Architecture:** FastAPI app wires together a Telegram channel, a three-step agent core (planner/executor/reflector stubs), and an OpenRouter LLM provider. aiosqlite for async SQLite access. Config via pydantic-settings (.env + config.yaml).

**Tech Stack:** Python 3.12, uv, FastAPI, uvicorn, httpx, aiosqlite, python-telegram-bot v21+, pydantic-settings, pyyaml, pytest, pytest-asyncio

**Design doc:** `docs/plans/2026-03-04-phase0-skeleton-design.md`

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `config.yaml.example`
- Create: `odigos/__init__.py`
- Create: `odigos/core/__init__.py`
- Create: `odigos/providers/__init__.py`
- Create: `odigos/channels/__init__.py`
- Create: `migrations/.gitkeep`
- Create: `data/.gitkeep`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Initialize git repo**

```bash
cd /Users/jacob/Projects/odigos
git init
```

**Step 2: Create .python-version**

```
3.12
```

**Step 3: Create pyproject.toml**

```toml
[project]
name = "odigos"
version = "0.1.0"
description = "Self-hosted personal AI agent"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "httpx>=0.28.0",
    "aiosqlite>=0.20.0",
    "python-telegram-bot>=21.0",
    "pydantic-settings>=2.7.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24.0",
    "ruff>=0.9.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
target-version = "py312"
line-length = 100
```

**Step 4: Create .gitignore**

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
.venv/

# Environment
.env

# Data
data/
!data/.gitkeep

# IDE
.idea/
.vscode/
*.swp

# OS
.DS_Store
```

**Step 5: Create .env.example**

```
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
OPENROUTER_API_KEY=your-openrouter-api-key
```

**Step 6: Create config.yaml.example**

```yaml
agent:
  name: "Odigos"

database:
  path: "data/odigos.db"

openrouter:
  default_model: "anthropic/claude-sonnet-4"
  fallback_model: "google/gemini-2.0-flash-001"
  max_tokens: 4096
  temperature: 0.7

telegram:
  mode: "polling"
  webhook_url: ""

server:
  host: "0.0.0.0"
  port: 8000
```

**Step 7: Create empty __init__.py files**

Create these as empty files:
- `odigos/__init__.py`
- `odigos/core/__init__.py`
- `odigos/providers/__init__.py`
- `odigos/channels/__init__.py`
- `tests/__init__.py`

**Step 8: Create migrations/.gitkeep and data/.gitkeep**

Empty files.

**Step 9: Create tests/conftest.py**

```python
import asyncio
import os
import tempfile
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from odigos.config import Settings


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def tmp_db_path() -> AsyncGenerator[str, None]:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    os.unlink(path)


@pytest.fixture
def test_settings(tmp_db_path: str) -> Settings:
    return Settings(
        telegram_bot_token="test-token",
        openrouter_api_key="test-key",
        agent={"name": "TestAgent"},
        database={"path": tmp_db_path},
        openrouter={
            "default_model": "test/model",
            "fallback_model": "test/fallback",
            "max_tokens": 100,
            "temperature": 0.5,
        },
        telegram={"mode": "polling", "webhook_url": ""},
        server={"host": "127.0.0.1", "port": 8000},
    )
```

**Step 10: Install dependencies**

```bash
cd /Users/jacob/Projects/odigos
uv sync --all-extras
```

**Step 11: Verify pytest runs (no tests yet, should report 0)**

```bash
uv run pytest -v
```
Expected: `no tests ran` or similar (0 collected).

**Step 12: Commit**

```bash
git add -A
git commit -m "chore: project scaffolding with uv, pyproject.toml, directory structure"
```

---

### Task 2: Configuration System

**Files:**
- Create: `odigos/config.py`
- Create: `tests/test_config.py`

**Step 1: Write the failing test**

`tests/test_config.py`:

```python
import os
import tempfile

import yaml

from odigos.config import Settings, load_settings


def test_settings_from_env_and_yaml():
    """Settings load from .env vars + config.yaml."""
    config = {
        "agent": {"name": "TestBot"},
        "database": {"path": "data/test.db"},
        "openrouter": {
            "default_model": "test/model",
            "fallback_model": "test/fallback",
            "max_tokens": 512,
            "temperature": 0.5,
        },
        "telegram": {"mode": "polling", "webhook_url": ""},
        "server": {"host": "127.0.0.1", "port": 9000},
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        config_path = f.name

    try:
        os.environ["TELEGRAM_BOT_TOKEN"] = "test-token-123"
        os.environ["OPENROUTER_API_KEY"] = "test-key-456"

        settings = load_settings(config_path)

        assert settings.telegram_bot_token == "test-token-123"
        assert settings.openrouter_api_key == "test-key-456"
        assert settings.agent.name == "TestBot"
        assert settings.database.path == "data/test.db"
        assert settings.openrouter.default_model == "test/model"
        assert settings.openrouter.max_tokens == 512
        assert settings.telegram.mode == "polling"
        assert settings.server.port == 9000
    finally:
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("OPENROUTER_API_KEY", None)
        os.unlink(config_path)


def test_settings_defaults():
    """Settings have sensible defaults from config.yaml.example."""
    settings = Settings(
        telegram_bot_token="tok",
        openrouter_api_key="key",
    )
    assert settings.agent.name == "Odigos"
    assert settings.database.path == "data/odigos.db"
    assert settings.openrouter.max_tokens == 4096
    assert settings.telegram.mode == "polling"
    assert settings.server.port == 8000
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_config.py -v
```
Expected: FAIL (module not found).

**Step 3: Write implementation**

`odigos/config.py`:

```python
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class AgentConfig(BaseModel):
    name: str = "Odigos"


class DatabaseConfig(BaseModel):
    path: str = "data/odigos.db"


class OpenRouterConfig(BaseModel):
    default_model: str = "anthropic/claude-sonnet-4"
    fallback_model: str = "google/gemini-2.0-flash-001"
    max_tokens: int = 4096
    temperature: float = 0.7


class TelegramConfig(BaseModel):
    mode: str = "polling"
    webhook_url: str = ""


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class Settings(BaseSettings):
    telegram_bot_token: str
    openrouter_api_key: str

    agent: AgentConfig = AgentConfig()
    database: DatabaseConfig = DatabaseConfig()
    openrouter: OpenRouterConfig = OpenRouterConfig()
    telegram: TelegramConfig = TelegramConfig()
    server: ServerConfig = ServerConfig()

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


def load_settings(config_path: str = "config.yaml") -> Settings:
    """Load settings from environment variables and a YAML config file."""
    yaml_config: dict = {}
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            yaml_config = yaml.safe_load(f) or {}

    return Settings(**yaml_config)
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_config.py -v
```
Expected: 2 passed.

**Step 5: Commit**

```bash
git add odigos/config.py tests/test_config.py
git commit -m "feat: configuration system with pydantic-settings and YAML loading"
```

---

### Task 3: Database Layer

**Files:**
- Create: `odigos/db.py`
- Create: `migrations/001_initial.sql`
- Create: `tests/test_db.py`

**Step 1: Write the migration SQL**

`migrations/001_initial.sql`:

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

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
```

**Step 2: Write the failing tests**

`tests/test_db.py`:

```python
import pytest

from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


async def test_migrations_applied(db: Database):
    """Migrations create the expected tables."""
    tables = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    table_names = [row["name"] for row in tables]
    assert "conversations" in table_names
    assert "messages" in table_names
    assert "_migrations" in table_names


async def test_migrations_idempotent(db: Database):
    """Running migrations twice doesn't error."""
    await db.run_migrations()  # second time
    tables = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    table_names = [row["name"] for row in tables]
    assert "conversations" in table_names


async def test_execute_and_fetch(db: Database):
    """Basic insert and query works."""
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        ("conv-1", "telegram"),
    )
    row = await db.fetch_one(
        "SELECT id, channel FROM conversations WHERE id = ?", ("conv-1",)
    )
    assert row is not None
    assert row["id"] == "conv-1"
    assert row["channel"] == "telegram"


async def test_fetch_all(db: Database):
    """fetch_all returns multiple rows."""
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        ("conv-1", "telegram"),
    )
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        ("conv-2", "email"),
    )
    rows = await db.fetch_all("SELECT id FROM conversations ORDER BY id")
    assert len(rows) == 2
    assert rows[0]["id"] == "conv-1"
    assert rows[1]["id"] == "conv-2"


async def test_fetch_one_returns_none(db: Database):
    """fetch_one returns None when no rows match."""
    row = await db.fetch_one(
        "SELECT id FROM conversations WHERE id = ?", ("nonexistent",)
    )
    assert row is None
```

**Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/test_db.py -v
```
Expected: FAIL (module not found).

**Step 4: Write implementation**

`odigos/db.py`:

```python
import sqlite3
from pathlib import Path

import aiosqlite


class Database:
    """Async SQLite helper with migration support."""

    def __init__(self, db_path: str, migrations_dir: str = "migrations") -> None:
        self.db_path = db_path
        self.migrations_dir = Path(migrations_dir)
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open connection and run migrations."""
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self.run_migrations()

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._conn

    async def run_migrations(self) -> None:
        """Apply SQL migration files in order, tracking which have been applied."""
        await self.conn.execute(
            "CREATE TABLE IF NOT EXISTS _migrations ("
            "  name TEXT PRIMARY KEY,"
            "  applied_at TEXT DEFAULT (datetime('now'))"
            ")"
        )
        await self.conn.commit()

        applied = {
            row[0]
            for row in await self.conn.execute_fetchall(
                "SELECT name FROM _migrations"
            )
        }

        if not self.migrations_dir.exists():
            return

        migration_files = sorted(self.migrations_dir.glob("*.sql"))
        for migration_file in migration_files:
            if migration_file.name in applied:
                continue
            sql = migration_file.read_text()
            await self.conn.executescript(sql)
            await self.conn.execute(
                "INSERT INTO _migrations (name) VALUES (?)",
                (migration_file.name,),
            )
            await self.conn.commit()

    async def execute(self, sql: str, params: tuple = ()) -> None:
        """Execute a single SQL statement."""
        await self.conn.execute(sql, params)
        await self.conn.commit()

    async def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        """Fetch a single row as a dict, or None."""
        cursor = await self.conn.execute(sql, params)
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        """Fetch all rows as a list of dicts."""
        cursor = await self.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
```

**Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_db.py -v
```
Expected: 5 passed.

**Step 6: Commit**

```bash
git add odigos/db.py migrations/001_initial.sql tests/test_db.py
git commit -m "feat: database layer with aiosqlite, migration runner, query helpers"
```

---

### Task 4: LLM Provider (base + OpenRouter)

**Files:**
- Create: `odigos/providers/base.py`
- Create: `odigos/providers/openrouter.py`
- Create: `tests/test_providers.py`

**Step 1: Write the failing tests**

`tests/test_providers.py`:

```python
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from odigos.providers.base import LLMResponse
from odigos.providers.openrouter import OpenRouterProvider


@pytest.fixture
def provider() -> OpenRouterProvider:
    return OpenRouterProvider(
        api_key="test-key",
        default_model="test/model",
        fallback_model="test/fallback",
        max_tokens=100,
        temperature=0.5,
    )


def _mock_response(content: str = "Hello!", model: str = "test/model") -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "model": model,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


async def test_complete_success(provider: OpenRouterProvider):
    """Successful completion returns LLMResponse."""
    mock_resp = httpx.Response(200, json=_mock_response())

    with patch.object(provider._client, "post", new_callable=AsyncMock, return_value=mock_resp):
        result = await provider.complete([{"role": "user", "content": "Hi"}])

    assert isinstance(result, LLMResponse)
    assert result.content == "Hello!"
    assert result.model == "test/model"
    assert result.tokens_in == 10
    assert result.tokens_out == 5


async def test_complete_falls_back_on_error(provider: OpenRouterProvider):
    """Falls back to fallback model on primary model failure."""
    error_resp = httpx.Response(500, json={"error": "internal"})
    success_resp = httpx.Response(200, json=_mock_response("Fallback!", "test/fallback"))

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return error_resp
        return success_resp

    with patch.object(provider._client, "post", side_effect=mock_post):
        result = await provider.complete([{"role": "user", "content": "Hi"}])

    assert result.content == "Fallback!"
    assert result.model == "test/fallback"


async def test_complete_raises_on_total_failure(provider: OpenRouterProvider):
    """Raises when both primary and fallback fail."""
    error_resp = httpx.Response(500, json={"error": "internal"})

    with patch.object(provider._client, "post", new_callable=AsyncMock, return_value=error_resp):
        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            await provider.complete([{"role": "user", "content": "Hi"}])
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_providers.py -v
```
Expected: FAIL (module not found).

**Step 3: Write base.py**

`odigos/providers/base.py`:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    content: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, messages: list[dict], **kwargs) -> LLMResponse:
        """Send messages to the LLM and get a response."""
        ...

    async def close(self) -> None:
        """Clean up resources."""
        pass
```

**Step 4: Write openrouter.py**

`odigos/providers/openrouter.py`:

```python
import logging

import httpx

from odigos.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(LLMProvider):
    """OpenRouter LLM provider with fallback support."""

    def __init__(
        self,
        api_key: str,
        default_model: str,
        fallback_model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> None:
        self.api_key = api_key
        self.default_model = default_model
        self.fallback_model = fallback_model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://odigos.one",
                "X-Title": "Odigos Personal AI Agent",
                "Content-Type": "application/json",
            },
        )

    async def complete(self, messages: list[dict], **kwargs) -> LLMResponse:
        """Try default model, fall back to fallback model on failure."""
        model = kwargs.get("model", self.default_model)
        models_to_try = [model]
        if model != self.fallback_model:
            models_to_try.append(self.fallback_model)

        last_error: Exception | None = None
        for try_model in models_to_try:
            try:
                return await self._call(messages, try_model, **kwargs)
            except Exception as e:
                logger.warning("Model %s failed: %s", try_model, e)
                last_error = e

        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    async def _call(self, messages: list[dict], model: str, **kwargs) -> LLMResponse:
        """Make a single API call to OpenRouter."""
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
        }

        response = self._client.post(OPENROUTER_API_URL, json=payload)
        if not isinstance(response, httpx.Response):
            response = await response

        if response.status_code != 200:
            raise RuntimeError(
                f"OpenRouter API error {response.status_code}: {response.text}"
            )

        data = response.json()
        usage = data.get("usage", {})

        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            model=data.get("model", model),
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            cost_usd=0.0,  # OpenRouter includes cost in headers, parse later
        )

    async def close(self) -> None:
        await self._client.aclose()
```

**Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_providers.py -v
```
Expected: 3 passed.

**Step 6: Commit**

```bash
git add odigos/providers/base.py odigos/providers/openrouter.py tests/test_providers.py
git commit -m "feat: LLM provider with OpenRouter and model fallback"
```

---

### Task 5: Channel Abstraction + UniversalMessage

**Files:**
- Create: `odigos/channels/base.py`
- Create: `tests/test_channels.py`

**Step 1: Write the failing test**

`tests/test_channels.py`:

```python
from datetime import datetime, timezone

from odigos.channels.base import UniversalMessage


def test_universal_message_creation():
    """UniversalMessage holds all required fields."""
    msg = UniversalMessage(
        id="msg-1",
        channel="telegram",
        sender="user-123",
        content="Hello agent",
        timestamp=datetime(2026, 3, 4, tzinfo=timezone.utc),
        metadata={"chat_id": 12345},
    )
    assert msg.id == "msg-1"
    assert msg.channel == "telegram"
    assert msg.content == "Hello agent"
    assert msg.metadata["chat_id"] == 12345
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_channels.py -v
```
Expected: FAIL.

**Step 3: Write implementation**

`odigos/channels/base.py`:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class UniversalMessage:
    """Platform-agnostic message format."""

    id: str
    channel: str
    sender: str
    content: str
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


class Channel(ABC):
    """Base class for I/O channels (Telegram, email, API, etc.)."""

    @abstractmethod
    async def start(self) -> None:
        """Start listening for messages."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel and clean up."""
        ...
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_channels.py -v
```
Expected: 1 passed.

**Step 5: Commit**

```bash
git add odigos/channels/base.py tests/test_channels.py
git commit -m "feat: channel abstraction with UniversalMessage dataclass"
```

---

### Task 6: Agent Core (planner/executor/reflector/context)

**Files:**
- Create: `odigos/core/context.py`
- Create: `odigos/core/planner.py`
- Create: `odigos/core/executor.py`
- Create: `odigos/core/reflector.py`
- Create: `odigos/core/agent.py`
- Create: `tests/test_core.py`

**Step 1: Write the failing tests**

`tests/test_core.py`:

```python
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from odigos.channels.base import UniversalMessage
from odigos.core.agent import Agent
from odigos.core.context import ContextAssembler
from odigos.core.executor import Executor
from odigos.core.planner import Planner
from odigos.core.reflector import Reflector
from odigos.db import Database
from odigos.providers.base import LLMResponse


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def mock_provider() -> AsyncMock:
    provider = AsyncMock()
    provider.complete.return_value = LLMResponse(
        content="I'm Odigos, your assistant.",
        model="test/model",
        tokens_in=20,
        tokens_out=10,
        cost_usd=0.001,
    )
    return provider


def _make_message(content: str = "Hello") -> UniversalMessage:
    return UniversalMessage(
        id=str(uuid.uuid4()),
        channel="telegram",
        sender="user-1",
        content=content,
        timestamp=datetime.now(timezone.utc),
        metadata={"chat_id": 12345},
    )


class TestContextAssembler:
    async def test_builds_messages_list(self, db: Database):
        assembler = ContextAssembler(db=db, agent_name="TestBot", history_limit=20)

        messages = await assembler.build("conv-1", "Hello there")

        assert messages[0]["role"] == "system"
        assert "TestBot" in messages[0]["content"]
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "Hello there"

    async def test_includes_conversation_history(self, db: Database):
        assembler = ContextAssembler(db=db, agent_name="TestBot", history_limit=20)

        # Insert some history
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-1", "telegram"),
        )
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            ("msg-1", "conv-1", "user", "Previous message"),
        )
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            ("msg-2", "conv-1", "assistant", "Previous response"),
        )

        messages = await assembler.build("conv-1", "New message")

        # system + 2 history + 1 current
        assert len(messages) == 4
        assert messages[1]["content"] == "Previous message"
        assert messages[2]["content"] == "Previous response"
        assert messages[3]["content"] == "New message"


class TestPlanner:
    async def test_returns_respond_plan(self):
        planner = Planner()
        plan = await planner.plan("Hello")
        assert plan.action == "respond"
        assert plan.requires_tools is False


class TestExecutor:
    async def test_calls_provider(self, db: Database, mock_provider: AsyncMock):
        assembler = ContextAssembler(db=db, agent_name="TestBot", history_limit=20)
        executor = Executor(provider=mock_provider, context_assembler=assembler)

        result = await executor.execute("conv-1", "Hello")

        assert result.content == "I'm Odigos, your assistant."
        mock_provider.complete.assert_called_once()


class TestReflector:
    async def test_stores_message(self, db: Database):
        reflector = Reflector(db=db)
        response = LLMResponse(
            content="Hi there",
            model="test/model",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
        )

        await reflector.reflect("conv-1", response)

        msg = await db.fetch_one(
            "SELECT content, role FROM messages WHERE conversation_id = ? AND role = 'assistant'",
            ("conv-1",),
        )
        assert msg is not None
        assert msg["content"] == "Hi there"


class TestAgent:
    async def test_full_loop(self, db: Database, mock_provider: AsyncMock):
        agent = Agent(
            db=db,
            provider=mock_provider,
            agent_name="TestBot",
            history_limit=20,
        )
        message = _make_message("Hello agent")

        response = await agent.handle_message(message)

        assert response == "I'm Odigos, your assistant."

        # Verify conversation was created
        conv = await db.fetch_one("SELECT * FROM conversations LIMIT 1")
        assert conv is not None
        assert conv["channel"] == "telegram"

        # Verify messages stored (user + assistant)
        msgs = await db.fetch_all("SELECT role FROM messages ORDER BY timestamp")
        roles = [m["role"] for m in msgs]
        assert "user" in roles
        assert "assistant" in roles
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_core.py -v
```
Expected: FAIL (modules not found).

**Step 3: Write context.py**

`odigos/core/context.py`:

```python
from odigos.db import Database

SYSTEM_PROMPT_TEMPLATE = """You are {agent_name}, a personal AI assistant.

You are helpful, direct, and concise. You remember past conversations and provide thoughtful responses.
When you don't know something, say so honestly rather than guessing."""


class ContextAssembler:
    """Builds the messages list for an LLM call from conversation history."""

    def __init__(self, db: Database, agent_name: str, history_limit: int = 20) -> None:
        self.db = db
        self.agent_name = agent_name
        self.history_limit = history_limit

    async def build(self, conversation_id: str, current_message: str) -> list[dict]:
        """Assemble the full messages list: system + history + current."""
        messages: list[dict] = []

        # System prompt
        messages.append({
            "role": "system",
            "content": SYSTEM_PROMPT_TEMPLATE.format(agent_name=self.agent_name),
        })

        # Conversation history
        history = await self.db.fetch_all(
            "SELECT role, content FROM messages "
            "WHERE conversation_id = ? "
            "ORDER BY timestamp ASC "
            "LIMIT ?",
            (conversation_id, self.history_limit),
        )
        for row in history:
            messages.append({"role": row["role"], "content": row["content"]})

        # Current message
        messages.append({"role": "user", "content": current_message})

        return messages
```

**Step 4: Write planner.py**

`odigos/core/planner.py`:

```python
from dataclasses import dataclass


@dataclass
class Plan:
    action: str  # "respond" — more actions in Phase 2
    requires_tools: bool = False


class Planner:
    """Decides what actions to take for a given message.

    Phase 0: Always returns a simple "respond" plan.
    Phase 1+: Will classify intent, decide on tools, etc.
    """

    async def plan(self, message_content: str) -> Plan:
        return Plan(action="respond", requires_tools=False)
```

**Step 5: Write executor.py**

`odigos/core/executor.py`:

```python
from odigos.core.context import ContextAssembler
from odigos.providers.base import LLMProvider, LLMResponse


class Executor:
    """Runs the plan — calls LLM, executes tools.

    Phase 0: Just calls the LLM with assembled context.
    Phase 2+: Will handle tool chains, permission checks, etc.
    """

    def __init__(
        self,
        provider: LLMProvider,
        context_assembler: ContextAssembler,
    ) -> None:
        self.provider = provider
        self.context_assembler = context_assembler

    async def execute(self, conversation_id: str, message_content: str) -> LLMResponse:
        messages = await self.context_assembler.build(conversation_id, message_content)
        return await self.provider.complete(messages)
```

**Step 6: Write reflector.py**

`odigos/core/reflector.py`:

```python
import uuid

from odigos.db import Database
from odigos.providers.base import LLMResponse


class Reflector:
    """Evaluates results and stores learnings.

    Phase 0: Just stores the assistant message.
    Phase 1+: Will extract learnings, corrections, entities, etc.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    async def reflect(self, conversation_id: str, response: LLMResponse) -> None:
        await self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, model_used, "
            "tokens_in, tokens_out, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                conversation_id,
                "assistant",
                response.content,
                response.model,
                response.tokens_in,
                response.tokens_out,
                response.cost_usd,
            ),
        )
```

**Step 7: Write agent.py**

`odigos/core/agent.py`:

```python
import uuid

from odigos.channels.base import UniversalMessage
from odigos.core.context import ContextAssembler
from odigos.core.executor import Executor
from odigos.core.planner import Planner
from odigos.core.reflector import Reflector
from odigos.db import Database
from odigos.providers.base import LLMProvider


class Agent:
    """Main agent: receives messages, runs plan->execute->reflect loop."""

    def __init__(
        self,
        db: Database,
        provider: LLMProvider,
        agent_name: str = "Odigos",
        history_limit: int = 20,
    ) -> None:
        self.db = db
        self.planner = Planner()
        self.context_assembler = ContextAssembler(db, agent_name, history_limit)
        self.executor = Executor(provider, self.context_assembler)
        self.reflector = Reflector(db)

    async def handle_message(self, message: UniversalMessage) -> str:
        """Process an incoming message and return a response string."""
        # Find or create conversation
        conversation_id = await self._get_or_create_conversation(message)

        # Store user message
        await self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (message.id, conversation_id, "user", message.content),
        )

        # Plan -> Execute -> Reflect
        plan = await self.planner.plan(message.content)
        response = await self.executor.execute(conversation_id, message.content)
        await self.reflector.reflect(conversation_id, response)

        # Update conversation
        await self.db.execute(
            "UPDATE conversations SET last_message_at = datetime('now'), "
            "message_count = message_count + 2 WHERE id = ?",
            (conversation_id,),
        )

        return response.content

    async def _get_or_create_conversation(self, message: UniversalMessage) -> str:
        """Get existing conversation for this chat, or create a new one.

        Uses chat_id from metadata for Telegram (one conversation per chat).
        """
        chat_id = message.metadata.get("chat_id", message.sender)
        lookup_id = f"{message.channel}:{chat_id}"

        existing = await self.db.fetch_one(
            "SELECT id FROM conversations WHERE id = ?", (lookup_id,)
        )
        if existing:
            return existing["id"]

        await self.db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            (lookup_id, message.channel),
        )
        return lookup_id
```

**Step 8: Run tests to verify they pass**

```bash
uv run pytest tests/test_core.py -v
```
Expected: 7 passed.

**Step 9: Commit**

```bash
git add odigos/core/ tests/test_core.py
git commit -m "feat: agent core with planner/executor/reflector/context pipeline"
```

---

### Task 7: Telegram Channel

**Files:**
- Create: `odigos/channels/telegram.py`
- Modify: `tests/test_channels.py` (add Telegram tests)

**Step 1: Write the failing tests**

Add to `tests/test_channels.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odigos.channels.telegram import TelegramChannel


@pytest.fixture
def mock_agent() -> AsyncMock:
    agent = AsyncMock()
    agent.handle_message.return_value = "Agent response"
    return agent


async def test_telegram_converts_update_to_universal_message(mock_agent: AsyncMock):
    """Telegram handler converts telegram Update to UniversalMessage."""
    channel = TelegramChannel(
        token="test-token",
        agent=mock_agent,
        mode="polling",
    )

    # Create a mock Telegram Update
    update = MagicMock()
    update.effective_message.text = "Hello"
    update.effective_message.message_id = 42
    update.effective_chat.id = 12345
    update.effective_user.id = 67890
    update.effective_user.username = "testuser"

    context = MagicMock()
    context.bot.send_chat_action = AsyncMock()
    update.effective_message.reply_text = AsyncMock()

    await channel._handle_text(update, context)

    # Verify the agent was called with a UniversalMessage
    mock_agent.handle_message.assert_called_once()
    msg = mock_agent.handle_message.call_args[0][0]
    assert msg.channel == "telegram"
    assert msg.content == "Hello"
    assert msg.metadata["chat_id"] == 12345

    # Verify reply was sent
    update.effective_message.reply_text.assert_called_once_with("Agent response")
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_channels.py::test_telegram_converts_update_to_universal_message -v
```
Expected: FAIL (module not found).

**Step 3: Write implementation**

`odigos/channels/telegram.py`:

```python
import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, MessageHandler, filters

from odigos.channels.base import Channel, UniversalMessage
from odigos.core.agent import Agent

logger = logging.getLogger(__name__)


class TelegramChannel(Channel):
    """Telegram bot channel using python-telegram-bot v21+."""

    def __init__(
        self,
        token: str,
        agent: Agent,
        mode: str = "polling",
        webhook_url: str = "",
    ) -> None:
        self.token = token
        self.agent = agent
        self.mode = mode
        self.webhook_url = webhook_url
        self._app: Application | None = None

    async def start(self) -> None:
        """Build and start the Telegram bot."""
        self._app = Application.builder().token(self.token).build()
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text)
        )

        await self._app.initialize()

        if self.mode == "webhook" and self.webhook_url:
            await self._app.bot.set_webhook(self.webhook_url)
            logger.info("Telegram bot started in webhook mode")
        else:
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram bot started in polling mode")

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        if self._app:
            if self._app.updater and self._app.updater.running:
                await self._app.updater.stop()
            if self._app.running:
                await self._app.stop()
            await self._app.shutdown()

    async def _handle_text(self, update: Update, context) -> None:
        """Handle incoming text messages."""
        if not update.effective_message or not update.effective_message.text:
            return

        # Show typing indicator
        try:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id, action=ChatAction.TYPING
            )
        except Exception:
            pass  # typing indicator is best-effort

        # Convert to UniversalMessage
        message = UniversalMessage(
            id=str(update.effective_message.message_id),
            channel="telegram",
            sender=str(update.effective_user.id),
            content=update.effective_message.text,
            timestamp=datetime.now(timezone.utc),
            metadata={
                "chat_id": update.effective_chat.id,
                "username": getattr(update.effective_user, "username", None),
            },
        )

        try:
            response = await self.agent.handle_message(message)
            await update.effective_message.reply_text(response)
        except Exception:
            logger.exception("Error handling message")
            await update.effective_message.reply_text(
                "Something went wrong. Please try again."
            )
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_channels.py -v
```
Expected: 2 passed.

**Step 5: Commit**

```bash
git add odigos/channels/telegram.py tests/test_channels.py
git commit -m "feat: Telegram channel with text message handling and typing indicator"
```

---

### Task 8: Main Entry Point

**Files:**
- Create: `odigos/main.py`

**Step 1: Write implementation**

`odigos/main.py`:

```python
import asyncio
import logging
import signal
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from odigos.channels.telegram import TelegramChannel
from odigos.config import Settings, load_settings
from odigos.core.agent import Agent
from odigos.db import Database
from odigos.providers.openrouter import OpenRouterProvider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Module-level references for cleanup
_db: Database | None = None
_provider: OpenRouterProvider | None = None
_telegram: TelegramChannel | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for FastAPI."""
    global _db, _provider, _telegram

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    settings = load_settings(config_path)

    logger.info("Starting Odigos agent: %s", settings.agent.name)

    # Initialize database
    _db = Database(settings.database.path)
    await _db.initialize()
    logger.info("Database initialized at %s", settings.database.path)

    # Initialize LLM provider
    _provider = OpenRouterProvider(
        api_key=settings.openrouter_api_key,
        default_model=settings.openrouter.default_model,
        fallback_model=settings.openrouter.fallback_model,
        max_tokens=settings.openrouter.max_tokens,
        temperature=settings.openrouter.temperature,
    )

    # Initialize agent
    agent = Agent(
        db=_db,
        provider=_provider,
        agent_name=settings.agent.name,
    )

    # Initialize Telegram channel
    _telegram = TelegramChannel(
        token=settings.telegram_bot_token,
        agent=agent,
        mode=settings.telegram.mode,
        webhook_url=settings.telegram.webhook_url,
    )
    await _telegram.start()
    logger.info("Telegram channel started in %s mode", settings.telegram.mode)

    logger.info("Odigos is ready.")

    yield

    # Shutdown
    logger.info("Shutting down Odigos...")
    if _telegram:
        await _telegram.stop()
    if _provider:
        await _provider.close()
    if _db:
        await _db.close()
    logger.info("Odigos stopped.")


app = FastAPI(title="Odigos", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "odigos"}


def main():
    import uvicorn

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    settings = load_settings(config_path)

    uvicorn.run(
        "odigos.main:app",
        host=settings.server.host,
        port=settings.server.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
```

**Step 2: Add entry point to pyproject.toml**

Add to `pyproject.toml`:

```toml
[project.scripts]
odigos = "odigos.main:main"
```

**Step 3: Verify syntax**

```bash
uv run python -c "from odigos.main import app; print('OK')"
```
Expected: `OK`

**Step 4: Commit**

```bash
git add odigos/main.py pyproject.toml
git commit -m "feat: main entry point with FastAPI lifespan, health endpoint, wiring"
```

---

### Task 9: Run All Tests + Final Verification

**Step 1: Run the full test suite**

```bash
uv run pytest -v
```
Expected: All tests pass (at least 18 tests across 4 test files).

**Step 2: Run linter**

```bash
uv run ruff check odigos/ tests/
```
Expected: No errors (or fix any that appear).

**Step 3: Verify the health endpoint starts**

Create a temporary `.env` and `config.yaml` for testing:

```bash
cp .env.example .env
cp config.yaml.example config.yaml
# Edit .env with test values (the bot won't connect without real tokens,
# but we can verify the app loads)
```

Note: Full Telegram testing requires real credentials. The health endpoint test verifies the app wires together correctly.

**Step 4: Final commit**

```bash
git add -A
git commit -m "chore: verify full test suite passes, lint clean"
```

---

## Summary

| Task | What | Files | Tests |
|------|------|-------|-------|
| 1 | Project scaffolding | pyproject.toml, .gitignore, dirs, conftest | 0 |
| 2 | Configuration system | config.py | 2 |
| 3 | Database layer | db.py, 001_initial.sql | 5 |
| 4 | LLM provider | providers/base.py, providers/openrouter.py | 3 |
| 5 | Channel abstraction | channels/base.py | 1 |
| 6 | Agent core | core/agent.py, planner, executor, reflector, context | 7 |
| 7 | Telegram channel | channels/telegram.py | 1 |
| 8 | Main entry point | main.py + pyproject.toml script | 0 |
| 9 | Final verification | (all files) | 19 total |
