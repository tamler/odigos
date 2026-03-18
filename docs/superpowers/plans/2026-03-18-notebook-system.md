# Notebook System V1 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Built-in markdown notebook with agent integration, starting with journal mode.

**Architecture:** Generic `ResourceStore` for CRUD, generic `require_feature()` dependency for gating, notebook-specific logic in API layer. BlockNote editor with contextual chat panel. Agent context flows via generic `context_metadata` dict.

**Tech Stack:** Python/FastAPI backend, SQLite, React/TypeScript/BlockNote frontend, Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-03-18-notebook-system-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `migrations/038_notebooks.sql` | notebooks + notebook_entries tables |
| `odigos/core/resource_store.py` | Generic async CRUD store over any SQLite table |
| `odigos/api/deps.py` | Add `require_feature()` factory |
| `odigos/api/notebooks.py` | REST endpoints, disk backup, validation |
| `odigos/config.py` | `NotebooksConfig` with `enabled` flag |
| `odigos/main.py` | Register router, no new state needed |
| `odigos/core/context.py` | Add `context_metadata` kwarg, notebook context injection |
| `odigos/core/executor.py` | Pass metadata through to context assembly |
| `odigos/core/agent.py` | Thread `context_metadata` through handle_message -> _run -> executor |
| `odigos/core/agent_service.py` | Extract context from message metadata, pass through |
| `odigos/personality/prompt_builder.py` | Add `notebook_context` parameter |
| `odigos/api/ws.py` | Copy `context` from WS payload into `message.metadata` |
| `tests/test_resource_store.py` | ResourceStore unit tests |
| `tests/test_notebooks_api.py` | Notebook API integration tests |
| `tests/test_notebook_context.py` | Context assembly with notebook metadata |
| `dashboard/src/pages/NotebookPage.tsx` | Split view: BlockNote + contextual chat |
| `dashboard/src/App.tsx` | Add `/notebooks` and `/notebooks/:id` routes |
| `dashboard/src/layouts/AppLayout.tsx` | Add notebook nav icon |
| `skills/journal.md` | Journal mode skill |
| `data/notebooks/` | Disk backup directory |

---

## Chunk 1: Backend Foundation

### Task 1: Migration

**Files:**
- Create: `migrations/038_notebooks.sql`

- [ ] **Step 1: Create migration file**

```sql
-- Notebook system: notebooks and entries tables.

CREATE TABLE IF NOT EXISTS notebooks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    mode TEXT DEFAULT 'general',
    collaboration TEXT DEFAULT 'read',
    share_with_agent INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notebook_entries (
    id TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    entry_type TEXT DEFAULT 'user',
    status TEXT DEFAULT 'active',
    mood TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notebook_entries_notebook ON notebook_entries(notebook_id);
CREATE INDEX IF NOT EXISTS idx_notebooks_mode ON notebooks(mode);
```

- [ ] **Step 2: Verify migration applies cleanly**

Run: `python -c "import asyncio; from odigos.db import Database; db = Database(':memory:', 'migrations'); asyncio.run(db.initialize()); print('OK')"`
Expected: `OK` with no errors

- [ ] **Step 3: Commit**

```bash
git add migrations/038_notebooks.sql
git commit -m "feat(notebooks): add migration 038 for notebooks and entries tables"
```

---

### Task 2: Generic ResourceStore

**Files:**
- Create: `odigos/core/resource_store.py`
- Create: `tests/test_resource_store.py`

- [ ] **Step 1: Write failing tests**

File: `tests/test_resource_store.py`

```python
import uuid
from datetime import datetime, timezone

import pytest

from odigos.core.resource_store import ResourceStore
from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def store(db: Database) -> ResourceStore:
    return ResourceStore(db, "notebooks")


@pytest.fixture
def entry_store(db: Database) -> ResourceStore:
    return ResourceStore(db, "notebook_entries", parent_key="notebook_id")


class TestResourceStoreCreate:
    async def test_create_returns_id(self, store):
        row_id = await store.create(
            title="Test Notebook",
            mode="journal",
            collaboration="read",
            share_with_agent=0,
        )
        assert isinstance(row_id, str)
        assert len(row_id) == 36  # UUID format with dashes

    async def test_create_sets_timestamps(self, store):
        row_id = await store.create(title="Test", mode="general")
        row = await store.get(row_id)
        assert row is not None
        assert row["created_at"] is not None
        assert row["updated_at"] is not None


class TestResourceStoreGet:
    async def test_get_existing(self, store):
        row_id = await store.create(title="My Notebook", mode="journal")
        row = await store.get(row_id)
        assert row is not None
        assert row["title"] == "My Notebook"
        assert row["mode"] == "journal"

    async def test_get_missing_returns_none(self, store):
        row = await store.get("nonexistent-id")
        assert row is None


class TestResourceStoreList:
    async def test_list_empty(self, store):
        rows = await store.list()
        assert rows == []

    async def test_list_with_filter(self, store):
        await store.create(title="Journal", mode="journal")
        await store.create(title="Research", mode="research")
        rows = await store.list(mode="journal")
        assert len(rows) == 1
        assert rows[0]["title"] == "Journal"

    async def test_list_with_limit(self, store):
        for i in range(5):
            await store.create(title=f"Notebook {i}", mode="general")
        rows = await store.list(limit=3)
        assert len(rows) == 3

    async def test_list_ordered_by_created_at_desc(self, store):
        id1 = await store.create(title="First", mode="general")
        id2 = await store.create(title="Second", mode="general")
        rows = await store.list()
        assert rows[0]["title"] == "Second"
        assert rows[1]["title"] == "First"


class TestResourceStoreUpdate:
    async def test_update_fields(self, store):
        row_id = await store.create(title="Old Title", mode="general")
        result = await store.update(row_id, title="New Title")
        assert result is True
        row = await store.get(row_id)
        assert row["title"] == "New Title"

    async def test_update_sets_updated_at(self, store):
        row_id = await store.create(title="Test", mode="general")
        row_before = await store.get(row_id)
        await store.update(row_id, title="Updated")
        row_after = await store.get(row_id)
        assert row_after["updated_at"] >= row_before["updated_at"]

    async def test_update_nonexistent_returns_false(self, store):
        result = await store.update("nonexistent", title="Nope")
        assert result is False


class TestResourceStoreDelete:
    async def test_delete_existing(self, store):
        row_id = await store.create(title="Delete Me", mode="general")
        result = await store.delete(row_id)
        assert result is True
        assert await store.get(row_id) is None

    async def test_delete_nonexistent_returns_false(self, store):
        result = await store.delete("nonexistent")
        assert result is False


class TestResourceStoreParentKey:
    async def test_list_by_parent(self, store, entry_store):
        nb_id = await store.create(title="NB", mode="general")
        await entry_store.create(
            notebook_id=nb_id, content="Entry 1", entry_type="user", status="active",
        )
        await entry_store.create(
            notebook_id=nb_id, content="Entry 2", entry_type="user", status="active",
        )
        entries = await entry_store.list(notebook_id=nb_id)
        assert len(entries) == 2

    async def test_cascade_delete(self, db, store, entry_store):
        nb_id = await store.create(title="NB", mode="general")
        await entry_store.create(
            notebook_id=nb_id, content="Entry", entry_type="user", status="active",
        )
        await store.delete(nb_id)
        entries = await entry_store.list(notebook_id=nb_id)
        assert entries == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_resource_store.py -v --no-header 2>&1 | head -30`
Expected: FAIL with `ModuleNotFoundError: No module named 'odigos.core.resource_store'`

- [ ] **Step 3: Write ResourceStore implementation**

File: `odigos/core/resource_store.py`

```python
"""Generic async CRUD store over any SQLite table.

Usage:
    notebooks = ResourceStore(db, "notebooks")
    entries = ResourceStore(db, "notebook_entries", parent_key="notebook_id")
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

from odigos.db import Database

logger = logging.getLogger(__name__)

_SAFE_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_identifier(name: str) -> str:
    """Ensure a column/table name is a safe SQL identifier."""
    if not _SAFE_IDENTIFIER.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return name


class ResourceStore:
    """Generic CRUD store for any SQLite-backed resource.

    Handles id generation, timestamps, filtering, and ordering.
    Feature-specific logic (validation, side effects) belongs in the API layer.
    """

    def __init__(self, db: Database, table: str, *, parent_key: str | None = None) -> None:
        self.db = db
        self.table = _validate_identifier(table)
        self.parent_key = parent_key

    async def create(self, **fields) -> str:
        """Insert a row with auto-generated id and timestamps. Returns the id."""
        row_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        fields["id"] = row_id
        fields["created_at"] = now
        fields["updated_at"] = now

        columns = ", ".join(_validate_identifier(k) for k in fields)
        placeholders = ", ".join("?" for _ in fields)
        values = tuple(fields.values())

        await self.db.execute(
            f"INSERT INTO {self.table} ({columns}) VALUES ({placeholders})",
            values,
        )
        logger.debug("Created %s row %s", self.table, row_id[:8])
        return row_id

    async def get(self, row_id: str) -> dict | None:
        """Fetch a single row by id."""
        return await self.db.fetch_one(
            f"SELECT * FROM {self.table} WHERE id = ?",
            (row_id,),
        )

    async def list(
        self,
        *,
        order_by: str = "created_at DESC",
        limit: int | None = None,
        **filters,
    ) -> list[dict]:
        """List rows with optional exact-match filters."""
        query = f"SELECT * FROM {self.table}"
        params: list = []

        if filters:
            clauses = []
            for col, val in filters.items():
                clauses.append(f"{_validate_identifier(col)} = ?")
                params.append(val)
            query += " WHERE " + " AND ".join(clauses)

        query += f" ORDER BY {order_by}"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        return await self.db.fetch_all(query, tuple(params))

    async def update(self, row_id: str, **fields) -> bool:
        """Update specific fields, auto-set updated_at. Returns True if row existed."""
        existing = await self.get(row_id)
        if not existing:
            return False

        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        set_clause = ", ".join(f"{_validate_identifier(col)} = ?" for col in fields)
        values = tuple(fields.values()) + (row_id,)

        await self.db.execute(
            f"UPDATE {self.table} SET {set_clause} WHERE id = ?",
            values,
        )
        logger.debug("Updated %s row %s", self.table, row_id[:8])
        return True

    async def delete(self, row_id: str) -> bool:
        """Delete a row by id. Returns True if row existed."""
        existing = await self.get(row_id)
        if not existing:
            return False

        await self.db.execute(
            f"DELETE FROM {self.table} WHERE id = ?",
            (row_id,),
        )
        logger.debug("Deleted %s row %s", self.table, row_id[:8])
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_resource_store.py -v --no-header`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add odigos/core/resource_store.py tests/test_resource_store.py
git commit -m "feat: add generic ResourceStore for CRUD over any SQLite table"
```

---

### Task 3: require_feature() dependency + NotebooksConfig

**Files:**
- Modify: `odigos/api/deps.py` (add `require_feature`)
- Modify: `odigos/config.py` (add `NotebooksConfig`)
- Create: `tests/test_require_feature.py`

- [ ] **Step 1: Write failing test for require_feature**

File: `tests/test_require_feature.py`

```python
import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from odigos.api.deps import require_feature
from odigos.config import Settings, NotebooksConfig


def _make_app(notebooks_enabled: bool) -> FastAPI:
    """Create a minimal FastAPI app with a gated endpoint."""
    app = FastAPI()
    settings = Settings(notebooks=NotebooksConfig(enabled=notebooks_enabled))
    app.state.settings = settings

    @app.get("/api/notebooks", dependencies=[Depends(require_feature("notebooks"))])
    async def list_notebooks():
        return {"notebooks": []}

    return app


class TestRequireFeature:
    def test_enabled_allows_access(self):
        app = _make_app(notebooks_enabled=True)
        client = TestClient(app)
        resp = client.get("/api/notebooks")
        assert resp.status_code == 200

    def test_disabled_returns_404(self):
        app = _make_app(notebooks_enabled=False)
        client = TestClient(app)
        resp = client.get("/api/notebooks")
        assert resp.status_code == 404

    def test_missing_config_allows_access(self):
        """If the feature config doesn't exist on Settings, allow access (safe default)."""
        app = FastAPI()
        app.state.settings = Settings()

        @app.get("/api/unknown", dependencies=[Depends(require_feature("nonexistent_feature"))])
        async def endpoint():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/api/unknown")
        assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_require_feature.py -v --no-header 2>&1 | head -20`
Expected: FAIL (missing `require_feature` and `NotebooksConfig`)

- [ ] **Step 3: Add NotebooksConfig to config.py**

Add after the existing `ApprovalConfig` class (around line 126 in `odigos/config.py`):

```python
class NotebooksConfig(BaseModel):
    enabled: bool = True
```

Add to `Settings` class (after the `templates` line, around line 178):

```python
    notebooks: NotebooksConfig = NotebooksConfig()
```

- [ ] **Step 4: Add require_feature to deps.py**

Add at the end of `odigos/api/deps.py`:

```python
def require_feature(feature_name: str):
    """FastAPI dependency that gates endpoints behind a config flag.

    Checks settings.{feature_name}.enabled. If the feature config doesn't
    exist or has no 'enabled' attribute, access is allowed (safe default).

    Usage: router = APIRouter(dependencies=[Depends(require_feature("notebooks"))])
    """
    def check(request: Request):
        settings = request.app.state.settings
        feature_config = getattr(settings, feature_name, None)
        if feature_config is not None and not getattr(feature_config, "enabled", True):
            raise HTTPException(status_code=404, detail=f"{feature_name} is not enabled")
    return check
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_require_feature.py -v --no-header`
Expected: All tests PASS

- [ ] **Step 6: Run existing test suite to verify no regressions**

Run: `python -m pytest tests/ -x -q --no-header 2>&1 | tail -5`
Expected: All existing tests still pass

- [ ] **Step 7: Commit**

```bash
git add odigos/config.py odigos/api/deps.py tests/test_require_feature.py
git commit -m "feat: add require_feature() dependency and NotebooksConfig"
```

---

### Task 4: Notebook API endpoints

**Files:**
- Create: `odigos/api/notebooks.py`
- Modify: `odigos/main.py` (register router)
- Create: `tests/test_notebooks_api.py`

- [ ] **Step 1: Write failing tests**

File: `tests/test_notebooks_api.py`

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from odigos.api.notebooks import router
from odigos.config import Settings, NotebooksConfig
from odigos.core.resource_store import ResourceStore
from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def app(db: Database) -> FastAPI:
    app = FastAPI()
    settings = Settings(notebooks=NotebooksConfig(enabled=True))
    app.state.settings = settings
    app.state.db = db
    app.include_router(router)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


class TestNotebooksCRUD:
    def test_list_empty(self, client):
        resp = client.get("/api/notebooks")
        assert resp.status_code == 200
        assert resp.json()["notebooks"] == []

    def test_create_notebook(self, client):
        resp = client.post("/api/notebooks", json={"title": "My Journal", "mode": "journal"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "My Journal"
        assert data["mode"] == "journal"
        assert "id" in data

    def test_get_notebook(self, client):
        create = client.post("/api/notebooks", json={"title": "Test"})
        nb_id = create.json()["id"]
        resp = client.get(f"/api/notebooks/{nb_id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Test"
        assert "entries" in resp.json()

    def test_get_missing_returns_404(self, client):
        resp = client.get("/api/notebooks/nonexistent")
        assert resp.status_code == 404

    def test_update_notebook(self, client):
        create = client.post("/api/notebooks", json={"title": "Old"})
        nb_id = create.json()["id"]
        resp = client.patch(f"/api/notebooks/{nb_id}", json={"title": "New"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "New"

    def test_delete_notebook(self, client):
        create = client.post("/api/notebooks", json={"title": "Delete Me"})
        nb_id = create.json()["id"]
        resp = client.delete(f"/api/notebooks/{nb_id}")
        assert resp.status_code == 200
        assert client.get(f"/api/notebooks/{nb_id}").status_code == 404


class TestNotebookEntries:
    def test_add_entry(self, client):
        create = client.post("/api/notebooks", json={"title": "NB"})
        nb_id = create.json()["id"]
        resp = client.post(f"/api/notebooks/{nb_id}/entries", json={
            "content": "What went well today?",
            "entry_type": "user",
        })
        assert resp.status_code == 201
        assert resp.json()["content"] == "What went well today?"

    def test_update_entry(self, client):
        create = client.post("/api/notebooks", json={"title": "NB"})
        nb_id = create.json()["id"]
        entry = client.post(f"/api/notebooks/{nb_id}/entries", json={
            "content": "Original",
        })
        entry_id = entry.json()["id"]
        resp = client.patch(f"/api/notebooks/{nb_id}/entries/{entry_id}", json={
            "content": "Updated",
        })
        assert resp.status_code == 200
        assert resp.json()["content"] == "Updated"

    def test_delete_entry(self, client):
        create = client.post("/api/notebooks", json={"title": "NB"})
        nb_id = create.json()["id"]
        entry = client.post(f"/api/notebooks/{nb_id}/entries", json={
            "content": "Delete me",
        })
        entry_id = entry.json()["id"]
        resp = client.delete(f"/api/notebooks/{nb_id}/entries/{entry_id}")
        assert resp.status_code == 200

    def test_accept_suggestion(self, client):
        create = client.post("/api/notebooks", json={"title": "NB"})
        nb_id = create.json()["id"]
        entry = client.post(f"/api/notebooks/{nb_id}/entries", json={
            "content": "Agent suggestion",
            "entry_type": "agent_suggestion",
            "status": "pending",
        })
        entry_id = entry.json()["id"]
        resp = client.post(f"/api/notebooks/{nb_id}/entries/{entry_id}/accept")
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"
        assert resp.json()["entry_type"] == "agent"

    def test_reject_suggestion(self, client):
        create = client.post("/api/notebooks", json={"title": "NB"})
        nb_id = create.json()["id"]
        entry = client.post(f"/api/notebooks/{nb_id}/entries", json={
            "content": "Agent suggestion",
            "entry_type": "agent_suggestion",
            "status": "pending",
        })
        entry_id = entry.json()["id"]
        resp = client.post(f"/api/notebooks/{nb_id}/entries/{entry_id}/reject")
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"


class TestDisabledFeature:
    def test_disabled_returns_404(self, db):
        app = FastAPI()
        app.state.settings = Settings(notebooks=NotebooksConfig(enabled=False))
        app.state.db = db
        app.include_router(router)
        client = TestClient(app)
        resp = client.get("/api/notebooks")
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_notebooks_api.py -v --no-header 2>&1 | head -20`
Expected: FAIL with `ModuleNotFoundError: No module named 'odigos.api.notebooks'`

- [ ] **Step 3: Write notebooks API**

File: `odigos/api/notebooks.py`

```python
"""REST API for notebook CRUD and entry management."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from odigos.api.deps import get_db, require_feature
from odigos.core.resource_store import ResourceStore

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/notebooks",
    tags=["notebooks"],
    dependencies=[Depends(require_feature("notebooks"))],
)

BACKUP_DIR = Path("data/notebooks")


# -- Request models --

class CreateNotebookRequest(BaseModel):
    title: str
    mode: str = "general"
    collaboration: str = "read"
    share_with_agent: int = 0


class UpdateNotebookRequest(BaseModel):
    title: str | None = None
    mode: str | None = None
    collaboration: str | None = None
    share_with_agent: int | None = None


class CreateEntryRequest(BaseModel):
    content: str
    entry_type: str = "user"
    status: str = "active"
    mood: str | None = None
    metadata: str | None = None


class UpdateEntryRequest(BaseModel):
    content: str | None = None
    status: str | None = None
    mood: str | None = None
    metadata: str | None = None


# -- Helpers --

def _notebooks_store(db) -> ResourceStore:
    return ResourceStore(db, "notebooks")


def _entries_store(db) -> ResourceStore:
    return ResourceStore(db, "notebook_entries", parent_key="notebook_id")


async def _backup_to_disk(db, notebook_id: str) -> None:
    """Export notebook + entries to a markdown file in data/notebooks/."""
    store = _notebooks_store(db)
    entry_store = _entries_store(db)
    nb = await store.get(notebook_id)
    if not nb:
        return

    entries = await entry_store.list(
        notebook_id=notebook_id, order_by="created_at ASC",
    )

    share_label = "yes" if nb["share_with_agent"] else "no"
    lines = [
        f"# {nb['title']}",
        f"Mode: {nb['mode']} | Collaboration: {nb['collaboration']} | Share: {share_label}",
        "",
    ]

    for entry in entries:
        if entry["status"] in ("rejected",):
            continue
        lines.append("---")
        lines.append("")
        lines.append(f"## {entry['created_at']}")
        if entry.get("mood"):
            lines.append(f"Mood: {entry['mood']}")
        lines.append("")
        lines.append(entry["content"])
        lines.append("")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    (BACKUP_DIR / f"{notebook_id}.md").write_text("\n".join(lines), encoding="utf-8")
    logger.debug("Backed up notebook %s to disk", notebook_id[:8])


# -- Endpoints --

@router.get("")
async def list_notebooks(db=Depends(get_db)):
    store = _notebooks_store(db)
    notebooks = await store.list()
    return {"notebooks": notebooks}


@router.post("", status_code=201)
async def create_notebook(body: CreateNotebookRequest, db=Depends(get_db)):
    store = _notebooks_store(db)
    nb_id = await store.create(
        title=body.title,
        mode=body.mode,
        collaboration=body.collaboration,
        share_with_agent=body.share_with_agent,
    )
    return await store.get(nb_id)


@router.get("/{notebook_id}")
async def get_notebook(notebook_id: str, db=Depends(get_db)):
    store = _notebooks_store(db)
    nb = await store.get(notebook_id)
    if not nb:
        raise HTTPException(status_code=404, detail="Notebook not found")
    entry_store = _entries_store(db)
    entries = await entry_store.list(
        notebook_id=notebook_id, order_by="created_at DESC",
    )
    return {**nb, "entries": entries}


@router.patch("/{notebook_id}")
async def update_notebook(
    notebook_id: str, body: UpdateNotebookRequest, db=Depends(get_db),
):
    store = _notebooks_store(db)
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    updated = await store.update(notebook_id, **fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Notebook not found")
    return await store.get(notebook_id)


@router.delete("/{notebook_id}")
async def delete_notebook(notebook_id: str, db=Depends(get_db)):
    store = _notebooks_store(db)
    deleted = await store.delete(notebook_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Notebook not found")
    # Clean up backup file
    backup_file = BACKUP_DIR / f"{notebook_id}.md"
    if backup_file.exists():
        backup_file.unlink()
    return {"deleted": True}


# -- Entry endpoints --

@router.post("/{notebook_id}/entries", status_code=201)
async def create_entry(
    notebook_id: str, body: CreateEntryRequest, db=Depends(get_db),
):
    nb_store = _notebooks_store(db)
    nb = await nb_store.get(notebook_id)
    if not nb:
        raise HTTPException(status_code=404, detail="Notebook not found")

    entry_store = _entries_store(db)
    entry_id = await entry_store.create(
        notebook_id=notebook_id,
        content=body.content,
        entry_type=body.entry_type,
        status=body.status,
        mood=body.mood,
        metadata=body.metadata,
    )
    await _backup_to_disk(db, notebook_id)
    return await entry_store.get(entry_id)


@router.patch("/{notebook_id}/entries/{entry_id}")
async def update_entry(
    notebook_id: str, entry_id: str, body: UpdateEntryRequest, db=Depends(get_db),
):
    entry_store = _entries_store(db)
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    updated = await entry_store.update(entry_id, **fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Entry not found")
    await _backup_to_disk(db, notebook_id)
    return await entry_store.get(entry_id)


@router.delete("/{notebook_id}/entries/{entry_id}")
async def delete_entry(notebook_id: str, entry_id: str, db=Depends(get_db)):
    entry_store = _entries_store(db)
    deleted = await entry_store.delete(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Entry not found")
    await _backup_to_disk(db, notebook_id)
    return {"deleted": True}


@router.post("/{notebook_id}/entries/{entry_id}/accept")
async def accept_suggestion(notebook_id: str, entry_id: str, db=Depends(get_db)):
    entry_store = _entries_store(db)
    entry = await entry_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry["entry_type"] != "agent_suggestion":
        raise HTTPException(status_code=400, detail="Entry is not an agent suggestion")
    await entry_store.update(entry_id, status="accepted", entry_type="agent")
    await _backup_to_disk(db, notebook_id)
    return await entry_store.get(entry_id)


@router.post("/{notebook_id}/entries/{entry_id}/reject")
async def reject_suggestion(notebook_id: str, entry_id: str, db=Depends(get_db)):
    entry_store = _entries_store(db)
    entry = await entry_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry["entry_type"] != "agent_suggestion":
        raise HTTPException(status_code=400, detail="Entry is not an agent suggestion")
    await entry_store.update(entry_id, status="rejected")
    await _backup_to_disk(db, notebook_id)
    return await entry_store.get(entry_id)
```

- [ ] **Step 4: Register router in main.py**

Add import after line 63 (`from odigos.api.analytics import router as analytics_router`):
```python
from odigos.api.notebooks import router as notebooks_router
```

Add router registration after line 825 (`app.include_router(analytics_router)`):
```python
app.include_router(notebooks_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_notebooks_api.py -v --no-header`
Expected: All tests PASS

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest tests/ -x -q --no-header 2>&1 | tail -5`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add odigos/api/notebooks.py odigos/main.py tests/test_notebooks_api.py
git commit -m "feat(notebooks): add REST API endpoints with ResourceStore and require_feature"
```

---

## Chunk 2: Agent Integration

### Task 5: Generic context_metadata threading

This task threads a generic `context_metadata` dict from the WebSocket payload through the entire agent chain: `ws.py` -> `agent_service.py` -> `agent.py` -> `executor.py` -> `context.py` -> `prompt_builder.py`. Six files touched, one change per file.

**Files:**
- Modify: `odigos/api/ws.py:131-139` (copy context from WS payload into message metadata)
- Modify: `odigos/core/agent_service.py:35-42` (extract context, pass through)
- Modify: `odigos/core/agent.py:92-104,106-153` (thread context_metadata through handle_message -> _run -> executor)
- Modify: `odigos/core/executor.py:79-103` (accept context_metadata, pass to build())
- Modify: `odigos/core/context.py:59-66,269-286` (accept context_metadata, build notebook context)
- Modify: `odigos/personality/prompt_builder.py:6-56` (accept and include notebook_context)
- Create: `tests/test_notebook_context.py`

- [ ] **Step 1: Write failing tests**

File: `tests/test_notebook_context.py`

```python
import pytest

from odigos.core.context import ContextAssembler
from odigos.core.resource_store import ResourceStore
from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


class TestNotebookContext:
    async def test_context_metadata_parameter_accepted(self, db):
        """build() should accept context_metadata without error."""
        assembler = ContextAssembler(db=db, agent_name="TestBot")
        messages = await assembler.build(
            "conv-1", "Hello",
            context_metadata={"notebook_id": "nb-123"},
        )
        assert messages[0]["role"] == "system"

    async def test_notebook_context_injected(self, db):
        """When notebook_id is in context_metadata, notebook content appears in system prompt."""
        nb_store = ResourceStore(db, "notebooks")
        entry_store = ResourceStore(db, "notebook_entries", parent_key="notebook_id")
        nb_id = await nb_store.create(title="Evening Journal", mode="journal", collaboration="suggest")
        await entry_store.create(
            notebook_id=nb_id, content="Today was productive", entry_type="user", status="active",
        )

        assembler = ContextAssembler(db=db, agent_name="TestBot")
        messages = await assembler.build(
            "conv-1", "How am I doing?",
            context_metadata={"notebook_id": nb_id},
        )

        system = messages[0]["content"]
        assert "Evening Journal" in system
        assert "journal" in system
        assert "Today was productive" in system

    async def test_no_context_metadata_no_notebook(self, db):
        """Without context_metadata, no notebook content in system prompt."""
        assembler = ContextAssembler(db=db, agent_name="TestBot")
        messages = await assembler.build("conv-1", "Hello")
        system = messages[0]["content"]
        assert "Active notebook" not in system

    async def test_missing_notebook_id_ignored(self, db):
        """If notebook_id in metadata points to nonexistent notebook, no crash."""
        assembler = ContextAssembler(db=db, agent_name="TestBot")
        messages = await assembler.build(
            "conv-1", "Hello",
            context_metadata={"notebook_id": "nonexistent"},
        )
        assert "Active notebook" not in messages[0]["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_notebook_context.py -v --no-header 2>&1 | head -20`
Expected: FAIL (build() doesn't accept context_metadata yet)

- [ ] **Step 3: Modify prompt_builder.py -- add notebook_context parameter**

In `odigos/personality/prompt_builder.py`, add `notebook_context: str = ""` parameter and include it in the output. Current signature ends with `recovery_briefing: str = ""`. New signature:

```python
def build_system_prompt(
    sections: list[PromptSection],
    memory_context: str = "",
    memory_index: str = "",
    skill_catalog: str = "",
    corrections_context: str = "",
    doc_listing: str = "",
    agent_name: str = "",
    skill_hints: str = "",
    active_plan: str = "",
    error_hints: str = "",
    experiences: str = "",
    user_profile: str = "",
    user_facts: str = "",
    recovery_briefing: str = "",
    notebook_context: str = "",
) -> str:
```

Add after `corrections_context` inclusion (after `if corrections_context:` block, before `return`):

```python
    if notebook_context:
        parts.append(notebook_context)
```

- [ ] **Step 4: Modify context.py -- add context_metadata parameter and notebook context assembly**

In `odigos/core/context.py`, change `build()` signature to:

```python
    async def build(
        self,
        conversation_id: str,
        message_content: str,
        max_tokens: int = 0,
        *,
        query_analysis: QueryAnalysis | None = None,
        context_metadata: dict | None = None,
    ) -> list[dict]:
```

Add notebook context assembly after the user_facts section (after the `user_facts` block around line 269) and before the `build_system_prompt()` call:

```python
        # Notebook context (when user is on a notebook page)
        notebook_context = ""
        if context_metadata and context_metadata.get("notebook_id") and self.db:
            try:
                nb_id = context_metadata["notebook_id"]
                nb_row = await self.db.fetch_one(
                    "SELECT title, mode, collaboration FROM notebooks WHERE id = ?",
                    (nb_id,),
                )
                if nb_row:
                    lines = [
                        f"## Active notebook: \"{nb_row['title']}\" (mode: {nb_row['mode']}, collaboration: {nb_row['collaboration']})",
                        "Recent entries:",
                    ]
                    entry_rows = await self.db.fetch_all(
                        "SELECT content, entry_type, mood, created_at FROM notebook_entries "
                        "WHERE notebook_id = ? AND status = 'active' "
                        "ORDER BY created_at DESC LIMIT 10",
                        (nb_id,),
                    )
                    for row in reversed(entry_rows):  # chronological order
                        prefix = f"[{row['entry_type']}]"
                        if row.get("mood"):
                            prefix += f" ({row['mood']})"
                        lines.append(f"- {prefix} {row['content'][:200]}")
                    notebook_context = "\n".join(lines)
            except Exception:
                logger.debug("Could not load notebook context", exc_info=True)
```

Then add `notebook_context=notebook_context` to the `build_system_prompt()` call:

```python
        system_prompt = build_system_prompt(
            sections=sections,
            memory_context=memory_context,
            memory_index=memory_index,
            skill_catalog=skill_catalog,
            corrections_context=corrections_context,
            doc_listing=doc_listing,
            agent_name=self.agent_name,
            skill_hints=skill_hints,
            active_plan=active_plan,
            error_hints=error_hints,
            experiences=experiences_section,
            user_profile=user_profile,
            user_facts=user_facts,
            recovery_briefing=recovery_briefing,
            notebook_context=notebook_context,
        )
```

- [ ] **Step 5: Modify executor.py -- accept and pass context_metadata**

In `odigos/core/executor.py`, change `execute()` signature (line 79-87):

```python
    async def execute(
        self,
        conversation_id: str,
        message_content: str,
        abort_event: asyncio.Event | None = None,
        *,
        query_analysis: QueryAnalysis | None = None,
        status_callback: Callable[[str], Awaitable[None]] | None = None,
        context_metadata: dict | None = None,
    ) -> ExecuteResult:
```

Change the `context_assembler.build()` call (line 101-103):

```python
        messages = await self.context_assembler.build(
            conversation_id, message_content,
            query_analysis=query_analysis,
            context_metadata=context_metadata,
        )
```

- [ ] **Step 6: Modify agent.py -- thread context_metadata through handle_message and _run**

In `odigos/core/agent.py`, change `handle_message()` (line 92-104):

```python
    async def handle_message(
        self,
        message: UniversalMessage,
        *,
        status_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Process an incoming message through the ReAct loop."""
        conversation_id = await self._get_or_create_conversation(message)

        # Extract context_metadata from message metadata (set by ws.py)
        context_metadata = message.metadata.get("context") if message.metadata else None

        # Session serialization -- one turn at a time per session
        lock = self._get_session_lock(conversation_id)
        async with lock:
            return await self._run(
                conversation_id, message,
                status_callback=status_callback,
                context_metadata=context_metadata,
            )
```

Change `_run()` (line 106-112):

```python
    async def _run(
        self,
        conversation_id: str,
        message: UniversalMessage,
        *,
        status_callback: Callable[[str], Awaitable[None]] | None = None,
        context_metadata: dict | None = None,
    ) -> str:
```

Change the `executor.execute()` call (line 150-153):

```python
                result = await self.executor.execute(
                    conversation_id, message.content, query_analysis=analysis,
                    status_callback=status_callback,
                    context_metadata=context_metadata,
                )
```

- [ ] **Step 7: Modify ws.py -- copy context from WS payload into message metadata**

In `odigos/api/ws.py`, replace the message creation block (lines 131-139):

```python
                chat_id = conversation_id.split(":", 1)[1] if ":" in conversation_id else conversation_id
                msg_metadata = {"chat_id": chat_id}
                if data.get("context"):
                    msg_metadata["context"] = data["context"]
                msg = UniversalMessage(
                    id=uuid.uuid4().hex,
                    channel="web",
                    sender=session_id,
                    content=data.get("content", ""),
                    timestamp=datetime.now(timezone.utc),
                    metadata=msg_metadata,
                )
```

- [ ] **Step 8: Run tests**

Run: `python -m pytest tests/test_notebook_context.py -v --no-header`
Expected: All tests PASS

- [ ] **Step 9: Run full test suite**

Run: `python -m pytest tests/ -x -q --no-header 2>&1 | tail -5`
Expected: All tests pass

- [ ] **Step 10: Commit**

```bash
git add odigos/core/context.py odigos/core/executor.py odigos/core/agent.py odigos/core/agent_service.py odigos/personality/prompt_builder.py odigos/api/ws.py tests/test_notebook_context.py
git commit -m "feat(notebooks): thread context_metadata through full agent chain for notebook context"
```

---

### Task 6: Journal mode skill

**Files:**
- Create: `skills/journal.md`

- [ ] **Step 1: Create journal skill file**

File: `skills/journal.md`

```markdown
---
name: journal
description: Guide reflective journaling with prompts, mood tracking, and pattern recognition
---

# Journal Mode

When the user is working in a journal notebook, guide their reflection:

## Prompts
Offer one of these prompts when the user starts a new entry (rotate, don't repeat recently used):
- What went well today?
- What's on your mind right now?
- What challenged you today and how did you handle it?
- What are you grateful for?
- What would you do differently if you could redo today?
- What are you looking forward to?

## Mood
Ask about mood at the start of each entry. Accept emoji or text. Store in the entry's mood field.

## Behavior
- Be warm and non-judgmental
- Ask follow-up questions that deepen reflection
- Don't offer unsolicited advice unless asked
- Summarize patterns when asked ("how has my mood been this week?")
- Respect privacy -- journal content is personal

## Boundaries
- Don't use journal content outside the journal context unless the user has enabled sharing
- Don't reference journal entries in other conversations
- If the user seems distressed, be supportive but suggest professional help for serious concerns
```

- [ ] **Step 2: Verify skill loads**

Run: `python -c "from odigos.skills.registry import SkillRegistry; r = SkillRegistry(); r.load_all('skills'); print([s.name for s in r.list()])"`
Expected: Output includes `'journal'`

- [ ] **Step 3: Commit**

```bash
git add skills/journal.md
git commit -m "feat(notebooks): add journal mode skill"
```

---

## Chunk 3: Frontend

### Task 7: Create NotebookPage

V1 uses plain text entries (not BlockNote). BlockNote editor integration is deferred to the cowork layout phase (Phase 3) when the full editor experience is designed. V1 contextual chat uses POST `/api/agent` -- WebSocket-based chat is a fast follow-up.

**Files:**
- Create: `dashboard/src/pages/NotebookPage.tsx`
- Modify: `dashboard/src/App.tsx` (add routes)
- Modify: `dashboard/src/layouts/AppLayout.tsx` (add nav icon)

- [ ] **Step 1: Create NotebookPage component**

File: `dashboard/src/pages/NotebookPage.tsx`

This is the main notebook page. It has two modes:
1. **List view** (`/notebooks`): Shows all notebooks with create button
2. **Editor view** (`/notebooks/:id`): Split view with BlockNote editor (70%) and contextual chat (30%)

```tsx
import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Plus, ArrowLeft, Send, Trash2 } from 'lucide-react'
import { get, post, patch, del } from '@/lib/api'
import { toast } from 'sonner'

interface Notebook {
  id: string
  title: string
  mode: string
  collaboration: string
  share_with_agent: number
  created_at: string
  updated_at: string
}

interface Entry {
  id: string
  notebook_id: string
  content: string
  entry_type: string
  status: string
  mood: string | null
  created_at: string
}

// -- List View --

function NotebookList() {
  const [notebooks, setNotebooks] = useState<Notebook[]>([])
  const [title, setTitle] = useState('')
  const navigate = useNavigate()

  const load = useCallback(() => {
    get<{ notebooks: Notebook[] }>('/api/notebooks')
      .then((data) => setNotebooks(data.notebooks))
      .catch(() => toast.error('Failed to load notebooks'))
  }, [])

  useEffect(() => { load() }, [load])

  const create = async () => {
    if (!title.trim()) return
    try {
      const nb = await post<Notebook>('/api/notebooks', { title: title.trim(), mode: 'journal' })
      setTitle('')
      navigate(`/notebooks/${nb.id}`)
    } catch {
      toast.error('Failed to create notebook')
    }
  }

  return (
    <div className="flex flex-col gap-4 p-4 md:p-6 max-w-2xl mx-auto">
      <h1 className="text-xl font-semibold">Notebooks</h1>
      <div className="flex gap-2">
        <Input
          placeholder="New notebook title..."
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && create()}
        />
        <Button onClick={create} size="icon" variant="outline">
          <Plus className="h-4 w-4" />
        </Button>
      </div>
      <div className="flex flex-col gap-2">
        {notebooks.map((nb) => (
          <button
            key={nb.id}
            onClick={() => navigate(`/notebooks/${nb.id}`)}
            className="flex items-center justify-between p-3 rounded-lg border hover:bg-muted/50 text-left"
          >
            <div>
              <div className="font-medium">{nb.title}</div>
              <div className="text-xs text-muted-foreground">
                {nb.mode} &middot; {nb.collaboration}
              </div>
            </div>
            <div className="text-xs text-muted-foreground">
              {new Date(nb.updated_at).toLocaleDateString()}
            </div>
          </button>
        ))}
        {notebooks.length === 0 && (
          <p className="text-sm text-muted-foreground text-center py-8">
            No notebooks yet. Create one to get started.
          </p>
        )}
      </div>
    </div>
  )
}

// -- Editor View --

function NotebookEditor() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [notebook, setNotebook] = useState<Notebook | null>(null)
  const [entries, setEntries] = useState<Entry[]>([])
  const [newContent, setNewContent] = useState('')
  const [chatInput, setChatInput] = useState('')
  const [chatMessages, setChatMessages] = useState<{ role: string; content: string }[]>([])
  const chatEndRef = useRef<HTMLDivElement>(null)

  const load = useCallback(() => {
    if (!id) return
    get<Notebook & { entries: Entry[] }>(`/api/notebooks/${id}`)
      .then((data) => {
        const { entries: e, ...nb } = data
        setNotebook(nb)
        setEntries(e)
      })
      .catch(() => toast.error('Failed to load notebook'))
  }, [id])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  const addEntry = async () => {
    if (!newContent.trim() || !id) return
    try {
      await post(`/api/notebooks/${id}/entries`, { content: newContent.trim() })
      setNewContent('')
      load()
    } catch {
      toast.error('Failed to add entry')
    }
  }

  const deleteEntry = async (entryId: string) => {
    if (!id) return
    try {
      await del(`/api/notebooks/${id}/entries/${entryId}`)
      load()
    } catch {
      toast.error('Failed to delete entry')
    }
  }

  const acceptSuggestion = async (entryId: string) => {
    if (!id) return
    try {
      await post(`/api/notebooks/${id}/entries/${entryId}/accept`, {})
      load()
    } catch {
      toast.error('Failed to accept suggestion')
    }
  }

  const rejectSuggestion = async (entryId: string) => {
    if (!id) return
    try {
      await post(`/api/notebooks/${id}/entries/${entryId}/reject`, {})
      load()
    } catch {
      toast.error('Failed to reject suggestion')
    }
  }

  const sendChat = async () => {
    if (!chatInput.trim()) return
    const userMsg = chatInput.trim()
    setChatInput('')
    setChatMessages((prev) => [...prev, { role: 'user', content: userMsg }])

    // Send via the existing chat API with notebook context
    try {
      // Use the WebSocket for contextual chat -- for now, use POST to /api/agent
      const resp = await post<{ response: string }>('/api/agent', {
        message: userMsg,
        context: { notebook_id: id },
      })
      setChatMessages((prev) => [...prev, { role: 'assistant', content: resp.response }])
    } catch {
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Failed to get response.' },
      ])
    }
  }

  if (!notebook) {
    return <div className="flex items-center justify-center h-full text-muted-foreground">Loading...</div>
  }

  return (
    <div className="flex h-full">
      {/* Left: Notebook content (70%) */}
      <div className="flex-1 flex flex-col min-w-0 border-r md:w-[70%]">
        <div className="flex items-center gap-2 p-3 border-b">
          <Button variant="ghost" size="icon" onClick={() => navigate('/notebooks')}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <h2 className="font-semibold truncate">{notebook.title}</h2>
          <span className="text-xs text-muted-foreground ml-auto">
            {notebook.mode} &middot; {notebook.collaboration}
          </span>
        </div>

        <ScrollArea className="flex-1 p-4">
          <div className="flex flex-col gap-3 max-w-2xl">
            {entries.map((entry) => (
              <div
                key={entry.id}
                className={`p-3 rounded-lg border ${
                  entry.entry_type === 'agent_suggestion'
                    ? 'border-dashed opacity-70 bg-muted/30'
                    : entry.entry_type === 'agent'
                    ? 'bg-primary/5 border-primary/20'
                    : ''
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1">
                    {entry.mood && (
                      <span className="text-sm mr-2">{entry.mood}</span>
                    )}
                    <p className="text-sm whitespace-pre-wrap">{entry.content}</p>
                  </div>
                  <div className="flex gap-1 shrink-0">
                    {entry.entry_type === 'agent_suggestion' && entry.status === 'pending' ? (
                      <>
                        <Button size="sm" variant="outline" onClick={() => acceptSuggestion(entry.id)}>
                          Accept
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => rejectSuggestion(entry.id)}>
                          Reject
                        </Button>
                      </>
                    ) : (
                      <Button size="icon" variant="ghost" className="h-6 w-6" onClick={() => deleteEntry(entry.id)}>
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    )}
                  </div>
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  {new Date(entry.created_at).toLocaleString()}
                  {entry.entry_type !== 'user' && ` (${entry.entry_type})`}
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>

        <div className="p-3 border-t">
          <div className="flex gap-2 max-w-2xl">
            <Input
              placeholder="Write an entry..."
              value={newContent}
              onChange={(e) => setNewContent(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && addEntry()}
            />
            <Button onClick={addEntry} size="icon">
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>

      {/* Right: Contextual chat (30%) */}
      <div className="hidden md:flex flex-col w-[30%] min-w-[280px]">
        <div className="p-3 border-b">
          <h3 className="text-sm font-medium">Chat</h3>
          <p className="text-xs text-muted-foreground">Agent sees this notebook's context</p>
        </div>

        <ScrollArea className="flex-1 p-3">
          <div className="flex flex-col gap-2">
            {chatMessages.map((msg, i) => (
              <div
                key={i}
                className={`p-2 rounded-lg text-sm ${
                  msg.role === 'user'
                    ? 'bg-primary text-primary-foreground ml-4'
                    : 'bg-muted mr-4'
                }`}
              >
                {msg.content}
              </div>
            ))}
            <div ref={chatEndRef} />
          </div>
        </ScrollArea>

        <div className="p-3 border-t">
          <div className="flex gap-2">
            <Input
              placeholder="Ask about this notebook..."
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && sendChat()}
              className="text-sm"
            />
            <Button onClick={sendChat} size="icon" variant="outline">
              <Send className="h-3 w-3" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

// -- Page Router --

export default function NotebookPage() {
  const { id } = useParams<{ id: string }>()
  return id ? <NotebookEditor /> : <NotebookList />
}
```

- [ ] **Step 4: Add routes to App.tsx**

Add import:
```tsx
import NotebookPage from './pages/NotebookPage'
```

Add routes inside the `<Route element={<AppLayout />}>` block:
```tsx
<Route path="/notebooks" element={<NotebookPage />} />
<Route path="/notebooks/:id" element={<NotebookPage />} />
```

- [ ] **Step 5: Add notebook nav icon to AppLayout.tsx**

In the sidebar navigation area, add a notebook icon button alongside the existing Chat and Settings buttons. Import `BookOpen` from lucide-react and add a navigation button:

```tsx
import { BookOpen } from 'lucide-react'
```

Add a button that navigates to `/notebooks`:
```tsx
<Button
  variant={location.pathname.startsWith('/notebooks') ? 'secondary' : 'ghost'}
  size="icon"
  onClick={() => navigate('/notebooks')}
  title="Notebooks"
>
  <BookOpen className="h-4 w-4" />
</Button>
```

- [ ] **Step 6: Build dashboard**

Run: `cd dashboard && npx tsc --noEmit 2>&1 | head -20`
Run: `cd dashboard && npm run build 2>&1 | tail -10`
Expected: No TypeScript errors, build succeeds

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/pages/NotebookPage.tsx dashboard/src/App.tsx dashboard/src/layouts/AppLayout.tsx
git commit -m "feat(notebooks): add NotebookPage with list view, editor, and contextual chat panel"
```

---

### Task 8: Create data/notebooks directory and final integration

**Files:**
- Create: `data/notebooks/.gitkeep`

- [ ] **Step 1: Create backup directory**

```bash
mkdir -p data/notebooks && touch data/notebooks/.gitkeep
```

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -x -q --no-header 2>&1 | tail -10`
Expected: All tests pass

- [ ] **Step 3: Verify the API works end-to-end**

Run a quick manual smoke test:
```bash
python -c "
import asyncio
from odigos.core.resource_store import ResourceStore
from odigos.db import Database

async def test():
    db = Database(':memory:', 'migrations')
    await db.initialize()
    store = ResourceStore(db, 'notebooks')
    nb_id = await store.create(title='Test Journal', mode='journal', collaboration='suggest', share_with_agent=0)
    nb = await store.get(nb_id)
    print(f'Created: {nb[\"title\"]} (mode={nb[\"mode\"]})')
    entries = ResourceStore(db, 'notebook_entries', parent_key='notebook_id')
    eid = await entries.create(notebook_id=nb_id, content='What went well today?', entry_type='user', status='active')
    all_entries = await entries.list(notebook_id=nb_id)
    print(f'Entries: {len(all_entries)}')
    await db.close()
    print('OK')

asyncio.run(test())
"
```
Expected: `Created: Test Journal (mode=journal)`, `Entries: 1`, `OK`

- [ ] **Step 4: Commit**

```bash
git add data/notebooks/.gitkeep
git commit -m "feat(notebooks): add data/notebooks backup directory and verify integration"
```
