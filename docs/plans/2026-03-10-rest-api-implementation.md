# REST API Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add FastAPI REST endpoints for dashboard data, memory search, and programmatic message submission — all under `/api/` with Bearer token auth.

**Architecture:** Routes live in `odigos/api/` as separate router modules, mounted onto the existing FastAPI app in `main.py`. Each router receives dependencies (db, goal_store, etc.) via FastAPI's `Request.app.state`. Auth is a shared dependency that checks `Authorization: Bearer <key>` against `settings.api_key`. All endpoints are async and return JSON.

**Tech Stack:** FastAPI (already installed), Pydantic v2 response models, pytest + httpx for async test client.

---

## Context for the Implementer

**Existing FastAPI app:** `odigos/main.py` — creates `app = FastAPI(title="Odigos", lifespan=lifespan)` at line ~441. The lifespan stores services on `app.state`:
- `app.state.db` — `Database` (async SQLite)
- `app.state.goal_store` — `GoalStore`
- `app.state.agent` — `Agent`
- `app.state.channel_registry` — `ChannelRegistry`
- `app.state.vector_memory` — `VectorMemory`
- `app.state.budget_tracker` — `BudgetTracker`
- `app.state.tracer` — `Tracer`
- `app.state.settings` — `Settings`
- `app.state.plugin_manager` — `PluginManager`

**Database methods:** `db.fetch_all(sql, params)` returns `list[dict]`, `db.fetch_one(sql, params)` returns `dict | None`.

**Config:** `Settings` from `odigos/config.py`, loaded from YAML + env. Does NOT yet have `api_key` field.

**Test fixtures:** `tests/conftest.py` has `tmp_db_path` and `test_settings` fixtures.

---

### Task 1: Auth Dependency + API Key Config

**Files:**
- Modify: `odigos/config.py` — add `api_key` field to `Settings`
- Create: `odigos/api/__init__.py`
- Create: `odigos/api/deps.py` — auth dependency + state accessors
- Test: `tests/test_api_auth.py`

**Step 1: Write the failing test**

```python
# tests/test_api_auth.py
import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI
from odigos.api.deps import require_api_key


app = FastAPI()


@app.get("/test")
async def test_endpoint(api_key: str = require_api_key):
    return {"ok": True}


class TestApiKeyAuth:
    @pytest.fixture
    def api_key(self):
        return "test-secret-key"

    @pytest.fixture
    def client(self, api_key):
        app.state.settings = type("S", (), {"api_key": api_key})()
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def test_valid_key_passes(self, client, api_key):
        resp = await client.get("/test", headers={"Authorization": f"Bearer {api_key}"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    async def test_missing_header_returns_401(self, client):
        resp = await client.get("/test")
        assert resp.status_code == 401

    async def test_wrong_key_returns_403(self, client):
        resp = await client.get("/test", headers={"Authorization": "Bearer wrong-key"})
        assert resp.status_code == 403

    async def test_no_api_key_configured_allows_all(self):
        """When api_key is empty, auth is disabled (dev mode)."""
        app.state.settings = type("S", (), {"api_key": ""})()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/test")
            assert resp.status_code == 200
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_auth.py -v`
Expected: FAIL (ModuleNotFoundError: odigos.api.deps)

**Step 3: Write minimal implementation**

Add to `odigos/config.py` — find `class Settings` and add field:
```python
api_key: str = ""
```

Create `odigos/api/__init__.py`:
```python
```

Create `odigos/api/deps.py`:
```python
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


async def require_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Validate Bearer token against settings.api_key.

    If api_key is empty (dev mode), all requests pass through.
    """
    configured_key = request.app.state.settings.api_key
    if not configured_key:
        return ""

    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if credentials.credentials != configured_key:
        raise HTTPException(status_code=403, detail="Invalid API key")

    return credentials.credentials


def get_db(request: Request):
    return request.app.state.db


def get_goal_store(request: Request):
    return request.app.state.goal_store


def get_agent(request: Request):
    return request.app.state.agent


def get_vector_memory(request: Request):
    return request.app.state.vector_memory


def get_budget_tracker(request: Request):
    return request.app.state.budget_tracker


def get_settings(request: Request):
    return request.app.state.settings


def get_plugin_manager(request: Request):
    return request.app.state.plugin_manager


def get_channel_registry(request: Request):
    return request.app.state.channel_registry
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_auth.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add odigos/api/__init__.py odigos/api/deps.py odigos/config.py tests/test_api_auth.py
git commit -m "feat(api): add API key auth dependency and state accessors"
```

---

### Task 2: Conversations Router

**Files:**
- Create: `odigos/api/conversations.py`
- Test: `tests/test_api_conversations.py`

**Step 1: Write the failing test**

```python
# tests/test_api_conversations.py
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from odigos.api.conversations import router
from odigos.db import Database


@pytest.fixture
def app(db):
    a = FastAPI()
    a.state.db = db
    a.state.settings = type("S", (), {"api_key": ""})()
    a.include_router(router)
    return a


@pytest.fixture
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def db(tmp_db_path):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


async def _seed(db):
    await db.execute(
        "INSERT INTO conversations (id, channel, started_at, last_message_at, message_count) "
        "VALUES (?, ?, ?, ?, ?)",
        ("telegram:42", "telegram", "2026-03-10T00:00:00", "2026-03-10T01:00:00", 5),
    )
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        ("m1", "telegram:42", "user", "Hello", "2026-03-10T00:00:00"),
    )
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        ("m2", "telegram:42", "assistant", "Hi there!", "2026-03-10T00:00:01"),
    )


class TestConversationsList:
    async def test_list_empty(self, client):
        resp = await client.get("/api/conversations")
        assert resp.status_code == 200
        assert resp.json() == {"conversations": [], "total": 0}

    async def test_list_with_data(self, client, db):
        await _seed(db)
        resp = await client.get("/api/conversations")
        data = resp.json()
        assert data["total"] == 1
        assert data["conversations"][0]["id"] == "telegram:42"

    async def test_list_pagination(self, client, db):
        for i in range(5):
            await db.execute(
                "INSERT INTO conversations (id, channel, started_at) VALUES (?, ?, ?)",
                (f"api:{i}", "api", f"2026-03-10T0{i}:00:00"),
            )
        resp = await client.get("/api/conversations?limit=2&offset=0")
        data = resp.json()
        assert len(data["conversations"]) == 2
        assert data["total"] == 5


class TestConversationDetail:
    async def test_get_by_id(self, client, db):
        await _seed(db)
        resp = await client.get("/api/conversations/telegram:42")
        assert resp.status_code == 200
        assert resp.json()["id"] == "telegram:42"

    async def test_not_found(self, client):
        resp = await client.get("/api/conversations/nonexistent")
        assert resp.status_code == 404


class TestConversationMessages:
    async def test_get_messages(self, client, db):
        await _seed(db)
        resp = await client.get("/api/conversations/telegram:42/messages")
        assert resp.status_code == 200
        msgs = resp.json()["messages"]
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"

    async def test_messages_not_found(self, client):
        resp = await client.get("/api/conversations/nonexistent/messages")
        assert resp.status_code == 404
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_conversations.py -v`
Expected: FAIL (ModuleNotFoundError: odigos.api.conversations)

**Step 3: Write minimal implementation**

```python
# odigos/api/conversations.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from odigos.api.deps import get_db, require_api_key

router = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])


@router.get("/conversations")
async def list_conversations(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db=Depends(get_db),
):
    total_row = await db.fetch_one("SELECT COUNT(*) as cnt FROM conversations")
    total = total_row["cnt"] if total_row else 0

    rows = await db.fetch_all(
        "SELECT * FROM conversations ORDER BY last_message_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    return {"conversations": rows, "total": total}


@router.get("/conversations/{conversation_id:path}")
async def get_conversation(conversation_id: str, db=Depends(get_db)):
    row = await db.fetch_one(
        "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return dict(row)


@router.get("/conversations/{conversation_id:path}/messages")
async def get_messages(
    conversation_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db=Depends(get_db),
):
    conv = await db.fetch_one(
        "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    rows = await db.fetch_all(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC LIMIT ? OFFSET ?",
        (conversation_id, limit, offset),
    )
    return {"messages": rows}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_conversations.py -v`
Expected: PASS (7 tests)

**Step 5: Commit**

```bash
git add odigos/api/conversations.py tests/test_api_conversations.py
git commit -m "feat(api): add conversation list, detail, and messages endpoints"
```

---

### Task 3: Goals, Todos, Reminders Router

**Files:**
- Create: `odigos/api/goals.py`
- Test: `tests/test_api_goals.py`

**Step 1: Write the failing test**

```python
# tests/test_api_goals.py
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from odigos.api.goals import router
from odigos.core.goal_store import GoalStore
from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def store(db):
    return GoalStore(db=db)


@pytest.fixture
def app(db, store):
    a = FastAPI()
    a.state.db = db
    a.state.goal_store = store
    a.state.settings = type("S", (), {"api_key": ""})()
    a.include_router(router)
    return a


@pytest.fixture
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestGoalsEndpoint:
    async def test_list_empty(self, client):
        resp = await client.get("/api/goals")
        assert resp.status_code == 200
        assert resp.json()["goals"] == []

    async def test_list_with_data(self, client, store):
        await store.create_goal("Learn Python")
        resp = await client.get("/api/goals")
        goals = resp.json()["goals"]
        assert len(goals) == 1
        assert goals[0]["description"] == "Learn Python"


class TestTodosEndpoint:
    async def test_list_empty(self, client):
        resp = await client.get("/api/todos")
        assert resp.status_code == 200
        assert resp.json()["todos"] == []

    async def test_list_with_data(self, client, store):
        await store.create_todo("Buy milk")
        resp = await client.get("/api/todos")
        todos = resp.json()["todos"]
        assert len(todos) == 1
        assert todos[0]["description"] == "Buy milk"


class TestRemindersEndpoint:
    async def test_list_empty(self, client):
        resp = await client.get("/api/reminders")
        assert resp.status_code == 200
        assert resp.json()["reminders"] == []

    async def test_list_with_data(self, client, store):
        await store.create_reminder("Call dentist", due_seconds=3600)
        resp = await client.get("/api/reminders")
        reminders = resp.json()["reminders"]
        assert len(reminders) == 1
        assert reminders[0]["description"] == "Call dentist"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_goals.py -v`
Expected: FAIL (ModuleNotFoundError: odigos.api.goals)

**Step 3: Write minimal implementation**

```python
# odigos/api/goals.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from odigos.api.deps import get_goal_store, require_api_key

router = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])


@router.get("/goals")
async def list_goals(
    status: str = Query("active"),
    goal_store=Depends(get_goal_store),
):
    goals = await goal_store.list_goals(status=status)
    return {"goals": goals}


@router.get("/todos")
async def list_todos(
    status: str = Query("pending"),
    goal_store=Depends(get_goal_store),
):
    todos = await goal_store.list_todos(status=status)
    return {"todos": todos}


@router.get("/reminders")
async def list_reminders(
    status: str = Query("pending"),
    goal_store=Depends(get_goal_store),
):
    reminders = await goal_store.list_reminders(status=status)
    return {"reminders": reminders}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_goals.py -v`
Expected: PASS (6 tests)

**Step 5: Commit**

```bash
git add odigos/api/goals.py tests/test_api_goals.py
git commit -m "feat(api): add goals, todos, and reminders endpoints"
```

---

### Task 4: Memory Endpoints (Entities + Search)

**Files:**
- Create: `odigos/api/memory.py`
- Test: `tests/test_api_memory.py`

**Step 1: Write the failing test**

```python
# tests/test_api_memory.py
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from odigos.api.memory import router
from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def mock_vector_memory():
    vm = AsyncMock()
    vm.search = AsyncMock(return_value=[])
    return vm


@pytest.fixture
def app(db, mock_vector_memory):
    a = FastAPI()
    a.state.db = db
    a.state.vector_memory = mock_vector_memory
    a.state.settings = type("S", (), {"api_key": ""})()
    a.include_router(router)
    return a


@pytest.fixture
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestEntitiesEndpoint:
    async def test_empty(self, client):
        resp = await client.get("/api/memory/entities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entities"] == []
        assert data["edges"] == []

    async def test_with_data(self, client, db):
        await db.execute(
            "INSERT INTO entities (id, type, name, confidence, status) VALUES (?, ?, ?, ?, ?)",
            ("e1", "person", "Alice", 0.9, "active"),
        )
        await db.execute(
            "INSERT INTO entities (id, type, name, confidence, status) VALUES (?, ?, ?, ?, ?)",
            ("e2", "place", "Paris", 0.8, "active"),
        )
        await db.execute(
            "INSERT INTO edges (id, source_id, relationship, target_id, strength) "
            "VALUES (?, ?, ?, ?, ?)",
            ("edge1", "e1", "lives_in", "e2", 0.7),
        )
        resp = await client.get("/api/memory/entities")
        data = resp.json()
        assert len(data["entities"]) == 2
        assert len(data["edges"]) == 1


class TestMemorySearchEndpoint:
    async def test_search_requires_query(self, client):
        resp = await client.get("/api/memory/search")
        assert resp.status_code == 422  # missing required param

    async def test_search_returns_results(self, client, mock_vector_memory):
        mock_vector_memory.search = AsyncMock(return_value=[
            MagicMock(content_preview="Found memory", source_type="user_message",
                      source_id="conv-1", distance=0.1),
        ])
        resp = await client.get("/api/memory/search?q=test+query")
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["content_preview"] == "Found memory"

    async def test_search_empty(self, client, mock_vector_memory):
        resp = await client.get("/api/memory/search?q=nothing")
        assert resp.status_code == 200
        assert resp.json()["results"] == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_memory.py -v`
Expected: FAIL (ModuleNotFoundError: odigos.api.memory)

**Step 3: Write minimal implementation**

```python
# odigos/api/memory.py
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query

from odigos.api.deps import get_db, get_vector_memory, require_api_key

router = APIRouter(prefix="/api/memory", dependencies=[Depends(require_api_key)])


@router.get("/entities")
async def list_entities(db=Depends(get_db)):
    entities = await db.fetch_all(
        "SELECT * FROM entities WHERE status = 'active' ORDER BY name"
    )
    edges = await db.fetch_all("SELECT * FROM edges ORDER BY created_at DESC")
    return {"entities": entities, "edges": edges}


@router.get("/search")
async def search_memory(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    vector_memory=Depends(get_vector_memory),
):
    results = await vector_memory.search(q, limit=limit)
    return {
        "results": [
            {
                "content_preview": r.content_preview,
                "source_type": r.source_type,
                "source_id": r.source_id,
                "distance": r.distance,
            }
            for r in results
        ]
    }
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_memory.py -v`
Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add odigos/api/memory.py tests/test_api_memory.py
git commit -m "feat(api): add entity graph and semantic memory search endpoints"
```

---

### Task 5: Budget Endpoint

**Files:**
- Create: `odigos/api/budget.py`
- Test: `tests/test_api_budget.py`

**Step 1: Write the failing test**

```python
# tests/test_api_budget.py
import pytest
from unittest.mock import AsyncMock
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from odigos.api.budget import router


@pytest.fixture
def mock_budget_tracker():
    bt = AsyncMock()
    bt.check_budget = AsyncMock(return_value=AsyncMock(
        within_budget=True,
        warning=False,
        daily_spend=0.50,
        monthly_spend=12.00,
        daily_limit=5.00,
        monthly_limit=100.00,
    ))
    return bt


@pytest.fixture
def app(mock_budget_tracker):
    a = FastAPI()
    a.state.budget_tracker = mock_budget_tracker
    a.state.settings = type("S", (), {"api_key": ""})()
    a.include_router(router)
    return a


@pytest.fixture
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestBudgetEndpoint:
    async def test_returns_budget_status(self, client):
        resp = await client.get("/api/budget")
        assert resp.status_code == 200
        data = resp.json()
        assert data["within_budget"] is True
        assert data["daily_spend"] == 0.50
        assert data["monthly_spend"] == 12.00
        assert data["daily_limit"] == 5.00
        assert data["monthly_limit"] == 100.00
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_budget.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# odigos/api/budget.py
from __future__ import annotations

from fastapi import APIRouter, Depends

from odigos.api.deps import get_budget_tracker, require_api_key

router = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])


@router.get("/budget")
async def get_budget(budget_tracker=Depends(get_budget_tracker)):
    status = await budget_tracker.check_budget()
    return {
        "within_budget": status.within_budget,
        "warning": status.warning,
        "daily_spend": status.daily_spend,
        "monthly_spend": status.monthly_spend,
        "daily_limit": status.daily_limit,
        "monthly_limit": status.monthly_limit,
    }
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_budget.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/api/budget.py tests/test_api_budget.py
git commit -m "feat(api): add budget status endpoint"
```

---

### Task 6: Metrics Endpoint

**Files:**
- Create: `odigos/api/metrics.py`
- Test: `tests/test_api_metrics.py`

**Step 1: Write the failing test**

```python
# tests/test_api_metrics.py
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from odigos.api.metrics import router
from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def app(db):
    a = FastAPI()
    a.state.db = db
    a.state.settings = type("S", (), {"api_key": ""})()
    a.include_router(router)
    return a


@pytest.fixture
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestMetricsEndpoint:
    async def test_empty_db(self, client):
        resp = await client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["conversation_count"] == 0
        assert data["message_count"] == 0
        assert data["total_cost_usd"] == 0.0

    async def test_with_data(self, client, db):
        await db.execute(
            "INSERT INTO conversations (id, channel, started_at) VALUES (?, ?, ?)",
            ("c1", "telegram", "2026-03-10T00:00:00"),
        )
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, cost_usd, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("m1", "c1", "assistant", "Hi", 0.005, "2026-03-10T00:00:01"),
        )
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, cost_usd, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("m2", "c1", "assistant", "Bye", 0.003, "2026-03-10T00:00:02"),
        )
        resp = await client.get("/api/metrics")
        data = resp.json()
        assert data["conversation_count"] == 1
        assert data["message_count"] == 2
        assert data["total_cost_usd"] == pytest.approx(0.008)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_metrics.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# odigos/api/metrics.py
from __future__ import annotations

from fastapi import APIRouter, Depends

from odigos.api.deps import get_db, require_api_key

router = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])


@router.get("/metrics")
async def get_metrics(db=Depends(get_db)):
    conv_row = await db.fetch_one("SELECT COUNT(*) as cnt FROM conversations")
    msg_row = await db.fetch_one("SELECT COUNT(*) as cnt FROM messages")
    cost_row = await db.fetch_one(
        "SELECT COALESCE(SUM(cost_usd), 0.0) as total FROM messages"
    )

    return {
        "conversation_count": conv_row["cnt"] if conv_row else 0,
        "message_count": msg_row["cnt"] if msg_row else 0,
        "total_cost_usd": cost_row["total"] if cost_row else 0.0,
    }
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_metrics.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/api/metrics.py tests/test_api_metrics.py
git commit -m "feat(api): add system metrics endpoint"
```

---

### Task 7: Plugins Endpoint

**Files:**
- Create: `odigos/api/plugins.py`
- Test: `tests/test_api_plugins.py`

**Step 1: Write the failing test**

```python
# tests/test_api_plugins.py
import pytest
from unittest.mock import MagicMock
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from odigos.api.plugins import router


@pytest.fixture
def mock_plugin_manager():
    pm = MagicMock()
    pm.loaded = {"docling": MagicMock(name="docling"), "custom": MagicMock(name="custom")}
    return pm


@pytest.fixture
def app(mock_plugin_manager):
    a = FastAPI()
    a.state.plugin_manager = mock_plugin_manager
    a.state.settings = type("S", (), {"api_key": ""})()
    a.include_router(router)
    return a


@pytest.fixture
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestPluginsEndpoint:
    async def test_lists_plugins(self, client):
        resp = await client.get("/api/plugins")
        assert resp.status_code == 200
        plugins = resp.json()["plugins"]
        assert len(plugins) == 2
        names = [p["name"] for p in plugins]
        assert "docling" in names
        assert "custom" in names
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_plugins.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

First check what `PluginManager.loaded` looks like — it's a dict of name -> module. We need to expose just the names and status.

```python
# odigos/api/plugins.py
from __future__ import annotations

from fastapi import APIRouter, Depends

from odigos.api.deps import get_plugin_manager, require_api_key

router = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])


@router.get("/plugins")
async def list_plugins(plugin_manager=Depends(get_plugin_manager)):
    plugins = []
    for name in plugin_manager.loaded:
        plugins.append({"name": name, "status": "loaded"})
    return {"plugins": plugins}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_plugins.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/api/plugins.py tests/test_api_plugins.py
git commit -m "feat(api): add plugins list endpoint"
```

---

### Task 8: POST /api/message — Programmatic Message Submission

**Files:**
- Create: `odigos/api/message.py`
- Test: `tests/test_api_message.py`

**Step 1: Write the failing test**

```python
# tests/test_api_message.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from odigos.api.message import router


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.handle_message = AsyncMock(return_value="Agent response here")
    return agent


@pytest.fixture
def app(mock_agent):
    a = FastAPI()
    a.state.agent = mock_agent
    a.state.settings = type("S", (), {"api_key": ""})()
    a.include_router(router)
    return a


@pytest.fixture
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestMessageEndpoint:
    async def test_submit_message(self, client, mock_agent):
        resp = await client.post("/api/message", json={
            "content": "Hello agent",
            "conversation_id": "api:user-1",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["response"] == "Agent response here"
        assert data["conversation_id"] == "api:user-1"
        mock_agent.handle_message.assert_called_once()
        msg = mock_agent.handle_message.call_args[0][0]
        assert msg.content == "Hello agent"
        assert msg.channel == "api"

    async def test_auto_generates_conversation_id(self, client, mock_agent):
        resp = await client.post("/api/message", json={"content": "Hi"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["conversation_id"].startswith("api:")

    async def test_missing_content_returns_422(self, client):
        resp = await client.post("/api/message", json={})
        assert resp.status_code == 422

    async def test_empty_content_returns_422(self, client):
        resp = await client.post("/api/message", json={"content": ""})
        assert resp.status_code == 422
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_message.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# odigos/api/message.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from odigos.api.deps import get_agent, require_api_key
from odigos.channels.base import UniversalMessage

router = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])


class MessageRequest(BaseModel):
    content: str = Field(..., min_length=1)
    conversation_id: str | None = None


@router.post("/message")
async def submit_message(body: MessageRequest, agent=Depends(get_agent)):
    conversation_id = body.conversation_id or f"api:{uuid.uuid4().hex[:12]}"

    msg = UniversalMessage(
        id=str(uuid.uuid4()),
        channel="api",
        sender="api",
        content=body.content,
        timestamp=datetime.now(timezone.utc),
        metadata={"source": "rest_api"},
    )
    # Override conversation routing to use provided ID
    msg.metadata["conversation_id"] = conversation_id

    response = await agent.handle_message(msg)

    return {
        "response": response,
        "conversation_id": conversation_id,
    }
```

**Important implementation note:** Check how `agent.handle_message` determines conversation_id. If it uses `f"{message.channel}:{some_id}"` internally, you may need to pass the full conversation_id differently. Look at the agent code — if it constructs the ID from the message, ensure the `api:user-1` format is preserved. If the agent uses `message.metadata["conversation_id"]`, this approach works. Otherwise, adjust `msg.channel` and `msg.sender` to produce the correct conversation_id.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_message.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add odigos/api/message.py tests/test_api_message.py
git commit -m "feat(api): add programmatic message submission endpoint"
```

---

### Task 9: Mount All Routers in main.py

**Files:**
- Modify: `odigos/main.py`
- Test: `tests/test_api_integration.py`

**Step 1: Write the failing test**

```python
# tests/test_api_integration.py
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient


class TestRoutersMounted:
    """Verify all API routers are accessible on the main app."""

    @pytest.fixture
    def client(self):
        """Import the real app and stub out state for routing checks."""
        from odigos.main import app

        # Stub minimal state so endpoints don't crash
        app.state.db = AsyncMock()
        app.state.db.fetch_one = AsyncMock(return_value={"cnt": 0})
        app.state.db.fetch_all = AsyncMock(return_value=[])
        app.state.goal_store = AsyncMock()
        app.state.goal_store.list_goals = AsyncMock(return_value=[])
        app.state.goal_store.list_todos = AsyncMock(return_value=[])
        app.state.goal_store.list_reminders = AsyncMock(return_value=[])
        app.state.agent = AsyncMock()
        app.state.vector_memory = AsyncMock()
        app.state.vector_memory.search = AsyncMock(return_value=[])
        app.state.budget_tracker = AsyncMock()
        app.state.budget_tracker.check_budget = AsyncMock(return_value=AsyncMock(
            within_budget=True, warning=False,
            daily_spend=0.0, monthly_spend=0.0, daily_limit=5.0, monthly_limit=100.0,
        ))
        app.state.plugin_manager = MagicMock()
        app.state.plugin_manager.loaded = {}
        app.state.settings = type("S", (), {"api_key": ""})()
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def test_conversations_mounted(self, client):
        resp = await client.get("/api/conversations")
        assert resp.status_code == 200

    async def test_goals_mounted(self, client):
        resp = await client.get("/api/goals")
        assert resp.status_code == 200

    async def test_budget_mounted(self, client):
        resp = await client.get("/api/budget")
        assert resp.status_code == 200

    async def test_metrics_mounted(self, client):
        resp = await client.get("/api/metrics")
        assert resp.status_code == 200

    async def test_plugins_mounted(self, client):
        resp = await client.get("/api/plugins")
        assert resp.status_code == 200

    async def test_memory_entities_mounted(self, client):
        resp = await client.get("/api/memory/entities")
        assert resp.status_code == 200

    async def test_memory_search_mounted(self, client):
        resp = await client.get("/api/memory/search?q=test")
        assert resp.status_code == 200
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_integration.py -v`
Expected: FAIL (404 on all /api/ routes since routers aren't mounted yet)

**Step 3: Mount routers in main.py**

Add these lines in `odigos/main.py` right after `app = FastAPI(...)`:

```python
from odigos.api.conversations import router as conversations_router
from odigos.api.goals import router as goals_router
from odigos.api.memory import router as memory_router
from odigos.api.budget import router as budget_router
from odigos.api.metrics import router as metrics_router
from odigos.api.plugins import router as plugins_router
from odigos.api.message import router as message_router

app.include_router(conversations_router)
app.include_router(goals_router)
app.include_router(memory_router)
app.include_router(budget_router)
app.include_router(metrics_router)
app.include_router(plugins_router)
app.include_router(message_router)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_integration.py -v`
Expected: PASS (7 tests)

**Step 5: Commit**

```bash
git add odigos/main.py tests/test_api_integration.py
git commit -m "feat(api): mount all REST API routers in main app"
```

---

### Task 10: Add httpx Test Dependency

**Files:**
- Modify: `pyproject.toml` — add httpx to dev dependencies

**Step 1: Check current dev deps**

Run: `grep -A 10 'dev' pyproject.toml` to find the dev dependency section.

**Step 2: Add httpx**

Add `"httpx>=0.27.0"` to the dev dependencies list (or test extras). If there is no dev section, add it as a regular dependency since FastAPI's TestClient uses it.

Run: `uv add httpx` or manually edit pyproject.toml.

**Step 3: Verify**

Run: `uv sync && pytest tests/test_api_auth.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add httpx dependency for API testing"
```

**Note:** This task should be done FIRST if httpx isn't already installed. Check with `python -c "import httpx"` before starting Task 1. If it's already available, skip this task.

---

## Execution Order

1. **Task 10** first — ensure httpx is available
2. **Task 1** — auth dependency (all other tasks depend on this)
3. **Tasks 2-8** — can be done in order (each is independent, but doing them sequentially keeps commits clean)
4. **Task 9** last — mount everything and verify integration

## Summary of Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/conversations` | List conversations (paginated) |
| GET | `/api/conversations/:id` | Conversation detail |
| GET | `/api/conversations/:id/messages` | Message history |
| GET | `/api/goals` | Active goals |
| GET | `/api/todos` | Pending todos |
| GET | `/api/reminders` | Pending reminders |
| GET | `/api/memory/entities` | Entity graph (nodes + edges) |
| GET | `/api/memory/search?q=` | Semantic memory search |
| GET | `/api/budget` | Spend summary |
| GET | `/api/metrics` | System health |
| GET | `/api/plugins` | Loaded plugins |
| POST | `/api/message` | Programmatic message submission |
