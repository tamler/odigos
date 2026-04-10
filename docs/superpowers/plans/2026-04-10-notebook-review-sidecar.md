# Notebook Review Sidecar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the user an interactive sidebar panel showing agent-authored review comments on their notebooks. The agent reviews notebooks during heartbeat idle time and adds anchored observations referencing quoted text.

**Architecture:** Extends existing `notebook_entries` table with four new columns (quote, trigger_type, viewed_at, parent_id). Heartbeat Phase 9.6 runs a review pass on stale shared notebooks, calling the LLM with a review prompt that injects behavioral principles. Backup function splits output into user journal (`.md`) and agent sidecar (`.note.md`). Frontend NoteSidecar component polls via existing notebook entries endpoint with new query params.

**Tech Stack:** Python 3.12 + FastAPI + aiosqlite, React 19 + Tailwind 4, reuses existing ResourceStore + notebook entries infrastructure

**Spec:** `docs/superpowers/specs/2026-04-10-notebook-review-sidecar-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `migrations/008_notebook_notes_extension.sql` | Add quote/trigger_type/viewed_at/parent_id to notebook_entries, last_reviewed_at to notebooks |
| `odigos/core/heartbeat/notes_review.py` | `review_notebooks()` heartbeat phase + stale quote checker |
| `data/prompts/notebook_review.md` | LLM review prompt with behavioral principles placeholder |
| `dashboard/src/components/notes/NoteSidecar.tsx` | Main panel fetching + rendering agent entries |
| `dashboard/src/components/notes/NoteEntry.tsx` | Single agent entry card with quote + body + actions |
| `dashboard/src/components/notes/NoteTableOfContents.tsx` | Collapsible TOC at top of sidecar |
| `tests/test_notebooks_notes.py` | New fields, view endpoints, split backup |
| `tests/test_notebook_review.py` | Heartbeat review gating + LLM flow |

### Modified Files

| File | Change |
|------|--------|
| `schema.sql` | Add columns (idempotent ALTER-style) |
| `odigos/api/notebooks.py` | Extend CreateEntryRequest + UpdateEntryRequest with new fields; extend list query params; add view endpoints; split `_backup_to_disk` into user + sidecar writers; add per-notebook asyncio.Lock for backup serialization |
| `odigos/core/heartbeat/orchestrator.py` | Add Phase 9.6: notes review |
| `odigos/bootstrap.py` | Set `heartbeat.notes_review_enabled = True` |
| `dashboard/src/pages/NotebookPage.tsx` | Split-view toggle, NoteSidecar integration, text selection handler, reply prefill |
| `dashboard/src/components/AgentInputBar.tsx` | Accept optional `prefill` prop |
| `dashboard/src/stores/notificationStore.ts` | Handle `note_added` WebSocket message type |

---

### Task 1: Schema Migration

**Files:**
- Modify: `schema.sql`
- Create: `migrations/008_notebook_notes_extension.sql`
- Test: `tests/test_notebooks_notes.py`

- [ ] **Step 1: Write the failing schema test**

Create `tests/test_notebooks_notes.py`:

```python
"""Tests for notebook review sidecar extensions to notebook_entries."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


class TestSchemaExtensions:
    async def test_notebook_entries_has_quote_column(self, db):
        # Insert a notebook and entry with the new quote field
        nb_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO notebooks (id, title) VALUES (?, ?)",
            (nb_id, "Test"),
        )
        entry_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO notebook_entries (id, notebook_id, content, entry_type, quote, trigger_type) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (entry_id, nb_id, "Observation body", "agent", "original text", "heartbeat"),
        )
        row = await db.fetch_one(
            "SELECT quote, trigger_type FROM notebook_entries WHERE id = ?",
            (entry_id,),
        )
        assert row["quote"] == "original text"
        assert row["trigger_type"] == "heartbeat"

    async def test_notebook_entries_has_viewed_at_column(self, db):
        nb_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO notebooks (id, title) VALUES (?, ?)",
            (nb_id, "Test"),
        )
        entry_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO notebook_entries (id, notebook_id, content, entry_type) "
            "VALUES (?, ?, ?, ?)",
            (entry_id, nb_id, "body", "agent"),
        )
        # viewed_at should default to NULL
        row = await db.fetch_one(
            "SELECT viewed_at FROM notebook_entries WHERE id = ?",
            (entry_id,),
        )
        assert row["viewed_at"] is None

    async def test_notebook_entries_has_parent_id_column(self, db):
        nb_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO notebooks (id, title) VALUES (?, ?)",
            (nb_id, "Test"),
        )
        parent_id = str(uuid.uuid4())
        child_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO notebook_entries (id, notebook_id, content, entry_type) "
            "VALUES (?, ?, ?, ?)",
            (parent_id, nb_id, "agent observation", "agent"),
        )
        await db.execute(
            "INSERT INTO notebook_entries (id, notebook_id, content, entry_type, parent_id, trigger_type) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (child_id, nb_id, "user reply", "user", parent_id, "reply"),
        )
        row = await db.fetch_one(
            "SELECT parent_id FROM notebook_entries WHERE id = ?",
            (child_id,),
        )
        assert row["parent_id"] == parent_id

    async def test_notebooks_has_last_reviewed_at_column(self, db):
        nb_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO notebooks (id, title, last_reviewed_at) VALUES (?, ?, ?)",
            (nb_id, "Test", "2026-04-10T12:00:00Z"),
        )
        row = await db.fetch_one(
            "SELECT last_reviewed_at FROM notebooks WHERE id = ?",
            (nb_id,),
        )
        assert row["last_reviewed_at"] == "2026-04-10T12:00:00Z"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_notebooks_notes.py::TestSchemaExtensions -x -q`
Expected: FAIL — columns don't exist.

- [ ] **Step 3: Update schema.sql**

In `schema.sql`, find the `notebook_entries` table definition. Add four columns after the existing `metadata` column:

```sql
CREATE TABLE IF NOT EXISTS notebook_entries (
    id TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL,
    content TEXT NOT NULL,
    entry_type TEXT DEFAULT 'user',
    status TEXT DEFAULT 'active',
    mood TEXT,
    metadata TEXT,
    quote TEXT,
    trigger_type TEXT,
    viewed_at TEXT,
    parent_id TEXT REFERENCES notebook_entries(id),
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

In the `notebooks` table definition, add `last_reviewed_at TEXT` before `created_at`:

```sql
CREATE TABLE IF NOT EXISTS notebooks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    mode TEXT DEFAULT 'general',
    collaboration TEXT DEFAULT 'read',
    share_with_agent INTEGER DEFAULT 0,
    share_token TEXT,
    last_reviewed_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

- [ ] **Step 4: Create the migration**

Create `migrations/008_notebook_notes_extension.sql`:

```sql
-- Add review sidecar columns to notebook_entries
ALTER TABLE notebook_entries ADD COLUMN quote TEXT;
ALTER TABLE notebook_entries ADD COLUMN trigger_type TEXT;
ALTER TABLE notebook_entries ADD COLUMN viewed_at TEXT;
ALTER TABLE notebook_entries ADD COLUMN parent_id TEXT REFERENCES notebook_entries(id);

-- Add review tracking to notebooks
ALTER TABLE notebooks ADD COLUMN last_reviewed_at TEXT;
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_notebooks_notes.py::TestSchemaExtensions -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Run full notebook test suite**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/ -x -q -k "notebook"`
Expected: No new failures.

- [ ] **Step 7: Commit**

```bash
git add schema.sql migrations/008_notebook_notes_extension.sql tests/test_notebooks_notes.py
git commit -m "feat(notebooks): add quote/trigger_type/viewed_at/parent_id columns for review sidecar"
```

---

### Task 2: Extended API Request Models + List Filter

**Files:**
- Modify: `odigos/api/notebooks.py`
- Test: `tests/test_notebooks_notes.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_notebooks_notes.py`:

```python
from httpx import AsyncClient


class TestEntryFilters:
    async def test_create_entry_with_new_fields(self, client: AsyncClient, db):
        # Create a notebook first
        resp = await client.post("/api/notebooks", json={"title": "Test"})
        assert resp.status_code == 201
        nb_id = resp.json()["id"]

        # Create an agent entry with quote + trigger_type
        resp = await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={
                "content": "You mentioned deployment frustration before",
                "entry_type": "agent",
                "quote": "I'm spinning my wheels",
                "trigger_type": "heartbeat",
            },
        )
        assert resp.status_code == 201
        entry = resp.json()
        assert entry["quote"] == "I'm spinning my wheels"
        assert entry["trigger_type"] == "heartbeat"
        assert entry["entry_type"] == "agent"

    async def test_list_entries_filter_by_entry_type(self, client: AsyncClient):
        resp = await client.post("/api/notebooks", json={"title": "Test"})
        nb_id = resp.json()["id"]

        await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={"content": "User writing", "entry_type": "user"},
        )
        await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={"content": "Agent note", "entry_type": "agent", "trigger_type": "heartbeat"},
        )

        # Filter to only agent entries
        resp = await client.get(f"/api/notebooks/{nb_id}/entries?entry_type=agent")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entries"]) == 1
        assert data["entries"][0]["content"] == "Agent note"
        assert data["unread_count"] == 1

    async def test_list_entries_include_dead(self, client: AsyncClient, db):
        resp = await client.post("/api/notebooks", json={"title": "Test"})
        nb_id = resp.json()["id"]

        resp = await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={"content": "Dead note", "entry_type": "agent", "trigger_type": "heartbeat"},
        )
        entry_id = resp.json()["id"]
        await db.execute(
            "UPDATE notebook_entries SET status = 'dead' WHERE id = ?",
            (entry_id,),
        )

        # Default: dead entries excluded
        resp = await client.get(f"/api/notebooks/{nb_id}/entries?entry_type=agent")
        assert len(resp.json()["entries"]) == 0

        # include_dead=true: dead entries included
        resp = await client.get(
            f"/api/notebooks/{nb_id}/entries?entry_type=agent&include_dead=true"
        )
        assert len(resp.json()["entries"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_notebooks_notes.py::TestEntryFilters -x -q`
Expected: FAIL.

- [ ] **Step 3: Extend request models**

In `odigos/api/notebooks.py`, update `CreateEntryRequest` and `UpdateEntryRequest`:

```python
class CreateEntryRequest(BaseModel):
    content: str
    entry_type: str = "user"
    status: str = "active"
    mood: str | None = None
    metadata: str | None = None
    quote: str | None = None
    trigger_type: str | None = None
    parent_id: str | None = None


class UpdateEntryRequest(BaseModel):
    content: str | None = None
    status: str | None = None
    mood: str | None = None
    metadata: str | None = None
    quote: str | None = None
    viewed_at: str | None = None
```

- [ ] **Step 4: Pass new fields through create_entry**

Update `create_entry` handler in `odigos/api/notebooks.py`:

```python
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
        quote=body.quote,
        trigger_type=body.trigger_type,
        parent_id=body.parent_id,
    )
    await _backup_to_disk(db, notebook_id)
    return await entry_store.get(entry_id)
```

- [ ] **Step 5: Add entries list endpoint with query filters**

Add to `odigos/api/notebooks.py` (after the existing `get_notebook` handler):

```python
@router.get("/{notebook_id}/entries")
async def list_entries(
    notebook_id: str,
    entry_type: str | None = None,
    include_dead: bool = False,
    db=Depends(get_db),
):
    """List entries with optional type and status filters."""
    nb_store = _notebooks_store(db)
    nb = await nb_store.get(notebook_id)
    if not nb:
        raise HTTPException(status_code=404, detail="Notebook not found")

    filters = {"notebook_id": notebook_id}
    if entry_type:
        filters["entry_type"] = entry_type

    entry_store = _entries_store(db)
    entries = await entry_store.list(order_by="created_at DESC", **filters)

    if not include_dead:
        entries = [e for e in entries if e.get("status") != "dead"]
    # Always exclude rejected entries from this endpoint
    entries = [e for e in entries if e.get("status") != "rejected"]

    unread_count = 0
    if entry_type == "agent":
        unread_count = sum(
            1 for e in entries
            if e.get("entry_type") == "agent"
            and e.get("status") == "active"
            and not e.get("viewed_at")
        )

    return {"entries": entries, "unread_count": unread_count}
```

- [ ] **Step 6: Update CreateEntryRequest handler to allow agent_suggestion -> agent**

No change needed — the existing accept_suggestion endpoint already uses `entry_type='agent'` after acceptance.

- [ ] **Step 7: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_notebooks_notes.py::TestEntryFilters -v`
Expected: PASS (3 tests).

- [ ] **Step 8: Commit**

```bash
git add odigos/api/notebooks.py tests/test_notebooks_notes.py
git commit -m "feat(notebooks): extend entry create + add typed list endpoint with unread count"
```

---

### Task 3: View Tracking Endpoints

**Files:**
- Modify: `odigos/api/notebooks.py`
- Test: `tests/test_notebooks_notes.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_notebooks_notes.py`:

```python
class TestViewTracking:
    async def test_mark_entry_viewed(self, client: AsyncClient):
        resp = await client.post("/api/notebooks", json={"title": "Test"})
        nb_id = resp.json()["id"]

        resp = await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={"content": "Agent note", "entry_type": "agent", "trigger_type": "heartbeat"},
        )
        entry_id = resp.json()["id"]

        resp = await client.post(
            f"/api/notebooks/{nb_id}/entries/{entry_id}/view"
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        # Verify viewed_at is now set
        resp = await client.get(f"/api/notebooks/{nb_id}/entries?entry_type=agent")
        entry = resp.json()["entries"][0]
        assert entry["viewed_at"] is not None
        assert resp.json()["unread_count"] == 0

    async def test_mark_all_viewed(self, client: AsyncClient):
        resp = await client.post("/api/notebooks", json={"title": "Test"})
        nb_id = resp.json()["id"]

        for i in range(3):
            await client.post(
                f"/api/notebooks/{nb_id}/entries",
                json={
                    "content": f"Note {i}",
                    "entry_type": "agent",
                    "trigger_type": "heartbeat",
                },
            )

        resp = await client.post(
            f"/api/notebooks/{nb_id}/mark-all-viewed?entry_type=agent"
        )
        assert resp.status_code == 200
        assert resp.json()["marked"] == 3

        resp = await client.get(f"/api/notebooks/{nb_id}/entries?entry_type=agent")
        assert resp.json()["unread_count"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_notebooks_notes.py::TestViewTracking -x -q`
Expected: FAIL — endpoints don't exist.

- [ ] **Step 3: Add view endpoints**

Add to `odigos/api/notebooks.py` after the existing entry endpoints:

```python
@router.post("/{notebook_id}/entries/{entry_id}/view")
async def mark_entry_viewed(
    notebook_id: str, entry_id: str, db=Depends(get_db),
):
    """Mark an entry as viewed by the user."""
    entry_store = _entries_store(db)
    await _get_entry_or_404(entry_store, notebook_id, entry_id)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    await entry_store.update(entry_id, viewed_at=now)
    return {"ok": True}


@router.post("/{notebook_id}/mark-all-viewed")
async def mark_all_entries_viewed(
    notebook_id: str,
    entry_type: str | None = None,
    db=Depends(get_db),
):
    """Mark all unviewed entries (optionally filtered by type) as viewed."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    params = [now, notebook_id]
    sql = (
        "UPDATE notebook_entries SET viewed_at = ? "
        "WHERE notebook_id = ? AND viewed_at IS NULL AND status = 'active'"
    )
    if entry_type:
        sql += " AND entry_type = ?"
        params.append(entry_type)

    cursor = await db.execute(sql, tuple(params))
    return {"ok": True, "marked": cursor.rowcount if hasattr(cursor, "rowcount") else 0}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_notebooks_notes.py::TestViewTracking -v`
Expected: PASS (2 tests). If the `marked` count is 0 despite the update working, the cursor might not expose rowcount — in that case, do a SELECT COUNT(*) before the UPDATE instead:

```python
# Alternative if rowcount unavailable:
count_row = await db.fetch_one(
    sql.replace("UPDATE notebook_entries SET viewed_at = ?", "SELECT COUNT(*) as c FROM notebook_entries").replace("? AND", "AND"),
    tuple(params[1:]),
)
marked = count_row["c"] if count_row else 0
await db.execute(sql, tuple(params))
return {"ok": True, "marked": marked}
```

- [ ] **Step 5: Commit**

```bash
git add odigos/api/notebooks.py tests/test_notebooks_notes.py
git commit -m "feat(notebooks): add view tracking endpoints for review sidecar"
```

---

### Task 4: Split Backup Function

**Files:**
- Modify: `odigos/api/notebooks.py`
- Test: `tests/test_notebooks_notes.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_notebooks_notes.py`:

```python
from pathlib import Path


class TestSplitBackup:
    async def test_backup_writes_user_file_only_when_no_agent_notes(
        self, client: AsyncClient, tmp_path, monkeypatch
    ):
        # Monkeypatch the backup dir to a temp location
        from odigos.api import notebooks as notebooks_module
        monkeypatch.setattr(notebooks_module, "BACKUP_DIR", tmp_path)

        resp = await client.post("/api/notebooks", json={"title": "Test"})
        nb_id = resp.json()["id"]

        await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={"content": "User writing here", "entry_type": "user"},
        )

        # Main file should exist, sidecar should not
        main_file = tmp_path / f"{nb_id}.md"
        sidecar = tmp_path / f"{nb_id}.note.md"
        assert main_file.exists()
        assert not sidecar.exists()
        assert "User writing here" in main_file.read_text()

    async def test_backup_writes_both_files_when_agent_notes_exist(
        self, client: AsyncClient, tmp_path, monkeypatch
    ):
        from odigos.api import notebooks as notebooks_module
        monkeypatch.setattr(notebooks_module, "BACKUP_DIR", tmp_path)

        resp = await client.post("/api/notebooks", json={"title": "Test"})
        nb_id = resp.json()["id"]

        await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={"content": "My journal entry", "entry_type": "user"},
        )
        await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={
                "content": "Pattern observed",
                "entry_type": "agent",
                "quote": "my journal",
                "trigger_type": "heartbeat",
            },
        )

        main_file = tmp_path / f"{nb_id}.md"
        sidecar = tmp_path / f"{nb_id}.note.md"
        assert main_file.exists()
        assert sidecar.exists()

        # User entries only in main file
        main_content = main_file.read_text()
        assert "My journal entry" in main_content
        assert "Pattern observed" not in main_content

        # Agent entries only in sidecar
        sidecar_content = sidecar.read_text()
        assert "Pattern observed" in sidecar_content
        assert "My journal entry" not in sidecar_content
        assert "heartbeat" in sidecar_content
        assert '"my journal"' in sidecar_content or "> my journal" in sidecar_content

    async def test_backup_sidecar_contains_toc(
        self, client: AsyncClient, tmp_path, monkeypatch
    ):
        from odigos.api import notebooks as notebooks_module
        monkeypatch.setattr(notebooks_module, "BACKUP_DIR", tmp_path)

        resp = await client.post("/api/notebooks", json={"title": "Test"})
        nb_id = resp.json()["id"]

        await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={"content": "First observation", "entry_type": "agent", "trigger_type": "heartbeat"},
        )
        await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={"content": "Second observation", "entry_type": "agent", "trigger_type": "heartbeat"},
        )

        sidecar = tmp_path / f"{nb_id}.note.md"
        content = sidecar.read_text()
        assert "## Contents" in content
        assert "entries: 2" in content
        assert "active: 2" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_notebooks_notes.py::TestSplitBackup -x -q`
Expected: FAIL — sidecar file not written, or only one file exists.

- [ ] **Step 3: Rewrite `_backup_to_disk`**

In `odigos/api/notebooks.py`, replace the existing `_backup_to_disk` function with:

```python
# Module-level lock map for per-notebook backup serialization
_backup_locks: dict[str, asyncio.Lock] = {}
_backup_locks_guard = asyncio.Lock()


async def _get_backup_lock(notebook_id: str) -> asyncio.Lock:
    """Get or create a lock for the given notebook_id."""
    async with _backup_locks_guard:
        if notebook_id not in _backup_locks:
            _backup_locks[notebook_id] = asyncio.Lock()
        return _backup_locks[notebook_id]


async def _backup_to_disk(db, notebook_id: str) -> None:
    """Export notebook + entries to markdown files in data/notebooks/.

    Writes TWO files:
    - {notebook_id}.md        : user's journal (user + agent_suggestion entries)
    - {notebook_id}.note.md   : agent review sidecar (agent entries, active + dead)

    Serialized per-notebook via asyncio.Lock to prevent concurrent file write collisions.
    """
    lock = await _get_backup_lock(notebook_id)
    async with lock:
        await _write_backup_files(db, notebook_id)


async def _write_backup_files(db, notebook_id: str) -> None:
    """Render and write both backup files. Must be called under the per-notebook lock."""
    store = _notebooks_store(db)
    entry_store = _entries_store(db)
    nb = await store.get(notebook_id)
    if not nb:
        return

    all_entries = await entry_store.list(
        notebook_id=notebook_id, order_by="created_at ASC",
    )

    user_entries = [
        e for e in all_entries
        if e.get("entry_type") in ("user", "agent_suggestion")
        and e.get("status") not in ("rejected",)
    ]

    agent_entries = [
        e for e in all_entries
        if e.get("entry_type") == "agent"
        and e.get("status") in ("active", "dead", "stale")
    ]

    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Backup dir create failed for %s: %s", notebook_id[:8], exc)
        return

    # Write user journal file
    try:
        main_content = _render_user_journal(nb, user_entries)
        (BACKUP_DIR / f"{notebook_id}.md").write_text(main_content, encoding="utf-8")
    except OSError as exc:
        logger.warning("Notebook backup failed for %s: %s", notebook_id[:8], exc)

    # Write or delete agent sidecar file
    sidecar_path = BACKUP_DIR / f"{notebook_id}.note.md"
    try:
        if agent_entries:
            sidecar_content = _render_agent_sidecar(nb, notebook_id, agent_entries)
            sidecar_path.write_text(sidecar_content, encoding="utf-8")
        else:
            if sidecar_path.exists():
                sidecar_path.unlink()
    except OSError as exc:
        logger.warning("Notebook sidecar backup failed for %s: %s", notebook_id[:8], exc)


def _render_user_journal(nb: dict, user_entries: list[dict]) -> str:
    """Render the user's journal entries as markdown."""
    share_label = "yes" if nb["share_with_agent"] else "no"
    lines = [
        f"# {nb['title']}",
        f"Mode: {nb['mode']} | Collaboration: {nb['collaboration']} | Share: {share_label}",
        "",
    ]
    for entry in user_entries:
        lines.append("---")
        lines.append("")
        lines.append(f"## {entry['created_at']}")
        if entry.get("mood"):
            lines.append(f"Mood: {entry['mood']}")
        lines.append("")
        lines.append(entry["content"])
        lines.append("")
    return "\n".join(lines)


def _render_agent_sidecar(nb: dict, notebook_id: str, agent_entries: list[dict]) -> str:
    """Render the agent review sidecar with TOC + entries newest-first."""
    # Newest first
    sorted_entries = sorted(
        agent_entries, key=lambda e: e["created_at"], reverse=True
    )
    active_count = sum(1 for e in sorted_entries if e.get("status") == "active")
    dead_count = sum(1 for e in sorted_entries if e.get("status") == "dead")
    stale_count = sum(1 for e in sorted_entries if e.get("status") == "stale")
    latest_updated = sorted_entries[0]["created_at"] if sorted_entries else ""

    lines = [
        "---",
        f"file: data/notebooks/{notebook_id}.md",
        f"title: {nb['title']}",
        f"updated: {latest_updated}",
        f"entries: {len(sorted_entries)}",
        f"active: {active_count}",
        f"dead: {dead_count}",
    ]
    if stale_count:
        lines.append(f"stale: {stale_count}")
    lines.append("---")
    lines.append("")
    lines.append("## Contents")
    lines.append("")

    for i, entry in enumerate(sorted_entries, start=1):
        preview = (entry.get("content") or "")[:60].replace("\n", " ")
        time_str = entry["created_at"][:16].replace("T", " ")
        label = f"[{time_str} · agent] {preview}"
        if entry.get("status") == "dead":
            lines.append(f"{i}. ~~{label}~~ (dead)")
        elif entry.get("status") == "stale":
            lines.append(f"{i}. {label} _(stale)_")
        else:
            lines.append(f"{i}. {label}")
    lines.append("")

    for entry in sorted_entries:
        lines.append("---")
        lines.append("")
        trigger = entry.get("trigger_type") or "unknown"
        header = f"## {entry['created_at']} · agent · {trigger}"
        if entry.get("status") == "dead":
            header += " <dead/>"
        elif entry.get("status") == "stale":
            header += " <stale/>"
        lines.append(header)
        lines.append("")
        if entry.get("quote"):
            for quote_line in entry["quote"].splitlines():
                lines.append(f"> {quote_line}")
            lines.append("")
        lines.append(entry["content"])
        lines.append("")

    return "\n".join(lines)
```

Also add the asyncio import at the top of the file:

```python
import asyncio
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_notebooks_notes.py::TestSplitBackup -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run full notebook tests for regressions**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/ -x -q -k "notebook"`
Expected: No new failures. Any pre-existing failures should be documented as such.

- [ ] **Step 6: Commit**

```bash
git add odigos/api/notebooks.py tests/test_notebooks_notes.py
git commit -m "feat(notebooks): split backup into user journal + agent sidecar files"
```

---

### Task 5: Notebook Review Prompt + Heartbeat Phase

**Files:**
- Create: `data/prompts/notebook_review.md`
- Create: `odigos/core/heartbeat/notes_review.py`
- Test: `tests/test_notebook_review.py`

- [ ] **Step 1: Create the review prompt**

Create `data/prompts/notebook_review.md`:

```markdown
You are a thoughtful reviewer for a user's personal notebook. Read the notebook content and surface observations that might be useful to the user.

## Agent principles

{agent_principles}

## Rules

- Focus on patterns, contradictions, and connections to things you know about the user
- Quote specific text when commenting. Never make a comment without anchoring.
- Maximum 3 observations per review. Quality over quantity.
- Do NOT comment on typos, style, grammar, or spelling.
- Do NOT repeat observations you've already made (listed below).
- Do NOT make judgmental comments. Be a helpful peer, not a critic.
- Follow the agent principles above — they define your voice and behavior across all surfaces.
- If nothing is worth saying, return an empty list.

## Existing agent notes on this notebook

{existing_notes_summary}

## Notebook content

{notebook_content}

## Output

Return valid JSON only, no markdown fences:

{{"observations": [{{"quote": "exact text from the notebook", "comment": "your observation"}}]}}

If nothing is worth noting, return {{"observations": []}}.
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_notebook_review.py`:

```python
"""Tests for notebook review heartbeat phase."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from odigos.db import Database


def _make_llm_response(content: str):
    from odigos.providers.base import LLMResponse
    return LLMResponse(
        content=content, model="test/model",
        tokens_in=100, tokens_out=200, cost_usd=0.001,
    )


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


async def _seed_shared_notebook(db, title: str = "Journal", content: str = "My entry") -> str:
    nb_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO notebooks (id, title, share_with_agent) VALUES (?, ?, 1)",
        (nb_id, title),
    )
    entry_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO notebook_entries (id, notebook_id, content, entry_type) "
        "VALUES (?, ?, ?, 'user')",
        (entry_id, nb_id, content),
    )
    return nb_id


def _make_hb(db, llm_response, tmp_path: Path):
    hb = MagicMock()
    hb.db = db
    hb.llm_provider = AsyncMock()
    hb.llm_provider.complete = AsyncMock(return_value=llm_response)
    hb.background_model = "test/model"
    hb.current_phase = None
    hb.current_activity = None
    hb.notifier = MagicMock()
    hb.notifier.create = AsyncMock()
    hb.message_bus = MagicMock()
    hb.message_bus.publish = AsyncMock()
    return hb


class TestReviewGating:
    async def test_skips_short_notebook(self, db, tmp_path, monkeypatch):
        from odigos.api import notebooks as nb_module
        monkeypatch.setattr(nb_module, "BACKUP_DIR", tmp_path)
        from odigos.core.heartbeat import notes_review

        # 100 chars, well under MIN_CONTENT_CHARS
        await _seed_shared_notebook(db, content="Too short to review")
        hb = _make_hb(db, _make_llm_response('{"observations":[]}'), tmp_path)

        reviewed = await notes_review.review_notebooks(hb)
        assert reviewed == 0
        hb.llm_provider.complete.assert_not_called()

    async def test_skips_non_shared_notebook(self, db, tmp_path, monkeypatch):
        from odigos.api import notebooks as nb_module
        monkeypatch.setattr(nb_module, "BACKUP_DIR", tmp_path)
        from odigos.core.heartbeat import notes_review

        # Create a non-shared notebook with lots of content
        nb_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO notebooks (id, title, share_with_agent) VALUES (?, ?, 0)",
            (nb_id, "Private"),
        )
        await db.execute(
            "INSERT INTO notebook_entries (id, notebook_id, content, entry_type) "
            "VALUES (?, ?, ?, 'user')",
            (str(uuid.uuid4()), nb_id, "A" * 1000),
        )

        hb = _make_hb(db, _make_llm_response('{"observations":[]}'), tmp_path)
        reviewed = await notes_review.review_notebooks(hb)
        assert reviewed == 0

    async def test_skips_recently_reviewed(self, db, tmp_path, monkeypatch):
        from odigos.api import notebooks as nb_module
        monkeypatch.setattr(nb_module, "BACKUP_DIR", tmp_path)
        from odigos.core.heartbeat import notes_review

        nb_id = await _seed_shared_notebook(db, content="A" * 1000)
        await db.execute(
            "UPDATE notebooks SET last_reviewed_at = datetime('now') WHERE id = ?",
            (nb_id,),
        )

        hb = _make_hb(db, _make_llm_response('{"observations":[]}'), tmp_path)
        reviewed = await notes_review.review_notebooks(hb)
        assert reviewed == 0

    async def test_skips_notebook_with_max_notes(self, db, tmp_path, monkeypatch):
        from odigos.api import notebooks as nb_module
        monkeypatch.setattr(nb_module, "BACKUP_DIR", tmp_path)
        from odigos.core.heartbeat import notes_review

        nb_id = await _seed_shared_notebook(db, content="A" * 1000)
        for i in range(10):
            await db.execute(
                "INSERT INTO notebook_entries (id, notebook_id, content, entry_type, status, trigger_type) "
                "VALUES (?, ?, ?, 'agent', 'active', 'heartbeat')",
                (str(uuid.uuid4()), nb_id, f"Note {i}"),
            )

        hb = _make_hb(db, _make_llm_response('{"observations":[]}'), tmp_path)
        reviewed = await notes_review.review_notebooks(hb)
        assert reviewed == 0


class TestReviewExecution:
    async def test_review_inserts_entries_and_updates_timestamp(
        self, db, tmp_path, monkeypatch
    ):
        from odigos.api import notebooks as nb_module
        monkeypatch.setattr(nb_module, "BACKUP_DIR", tmp_path)
        from odigos.core.heartbeat import notes_review

        content = "I am really struggling with the deployment process. " * 20
        nb_id = await _seed_shared_notebook(db, content=content)

        response = json.dumps({
            "observations": [
                {
                    "quote": "struggling with the deployment",
                    "comment": "You've mentioned this before — consider breaking it down into smaller steps.",
                }
            ]
        })
        hb = _make_hb(db, _make_llm_response(response), tmp_path)

        reviewed = await notes_review.review_notebooks(hb)
        assert reviewed == 1

        # Agent entry was created
        rows = await db.fetch_all(
            "SELECT * FROM notebook_entries WHERE notebook_id = ? AND entry_type = 'agent'",
            (nb_id,),
        )
        assert len(rows) == 1
        assert "smaller steps" in rows[0]["content"]
        assert rows[0]["quote"] == "struggling with the deployment"
        assert rows[0]["trigger_type"] == "heartbeat"

        # last_reviewed_at was updated
        nb_row = await db.fetch_one(
            "SELECT last_reviewed_at FROM notebooks WHERE id = ?", (nb_id,),
        )
        assert nb_row["last_reviewed_at"] is not None

    async def test_review_skips_hallucinated_quotes(
        self, db, tmp_path, monkeypatch
    ):
        from odigos.api import notebooks as nb_module
        monkeypatch.setattr(nb_module, "BACKUP_DIR", tmp_path)
        from odigos.core.heartbeat import notes_review

        content = "A real sentence in the notebook. " * 30
        nb_id = await _seed_shared_notebook(db, content=content)

        response = json.dumps({
            "observations": [
                {
                    "quote": "This text is not in the notebook at all",
                    "comment": "Hallucinated comment.",
                },
                {
                    "quote": "A real sentence",
                    "comment": "Valid comment.",
                },
            ]
        })
        hb = _make_hb(db, _make_llm_response(response), tmp_path)

        await notes_review.review_notebooks(hb)

        rows = await db.fetch_all(
            "SELECT * FROM notebook_entries WHERE notebook_id = ? AND entry_type = 'agent'",
            (nb_id,),
        )
        assert len(rows) == 1  # Only the valid one inserted
        assert "Valid comment" in rows[0]["content"]

    async def test_review_marks_stale_quotes(self, db, tmp_path, monkeypatch):
        from odigos.api import notebooks as nb_module
        monkeypatch.setattr(nb_module, "BACKUP_DIR", tmp_path)
        from odigos.core.heartbeat import notes_review

        content = "Current notebook content that says nothing important. " * 20
        nb_id = await _seed_shared_notebook(db, content=content)

        # Pre-seed an existing agent note with a quote that's NOT in the current content
        stale_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO notebook_entries "
            "(id, notebook_id, content, entry_type, trigger_type, quote, status) "
            "VALUES (?, ?, ?, 'agent', 'heartbeat', ?, 'active')",
            (stale_id, nb_id, "Old observation", "this text is gone now"),
        )

        hb = _make_hb(db, _make_llm_response('{"observations":[]}'), tmp_path)
        await notes_review.review_notebooks(hb)

        # Stale note should be marked status='stale'
        row = await db.fetch_one(
            "SELECT status FROM notebook_entries WHERE id = ?", (stale_id,),
        )
        assert row["status"] == "stale"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_notebook_review.py -x -q`
Expected: FAIL — `odigos.core.heartbeat.notes_review` module does not exist.

- [ ] **Step 4: Implement `notes_review.py`**

Create `odigos/core/heartbeat/notes_review.py`:

```python
"""Heartbeat phase: review shared notebooks and add anchored observations."""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.core.heartbeat.orchestrator import Heartbeat

logger = logging.getLogger(__name__)

REVIEW_INTERVAL_HOURS = 24
MAX_NOTEBOOKS_PER_CYCLE = 1
MIN_CONTENT_CHARS = 500
MAX_ACTIVE_NOTES_PER_NOTEBOOK = 10
MAX_REVIEW_CONTENT_CHARS = 8000


async def review_notebooks(hb: "Heartbeat") -> int:
    """Review the oldest stale shared notebook. Returns 0 or 1."""
    try:
        notebook = await _pick_notebook(hb.db)
        if not notebook:
            return 0

        nb_id = notebook["id"]
        nb_title = notebook["title"]

        user_content = await _load_user_content(hb.db, nb_id)
        if len(user_content) < MIN_CONTENT_CHARS:
            logger.debug("Skipping review: notebook %s content too short", nb_id[:8])
            return 0

        existing_notes = await _load_existing_agent_notes(hb.db, nb_id)
        active_notes = [n for n in existing_notes if n.get("status") == "active"]
        if len(active_notes) >= MAX_ACTIVE_NOTES_PER_NOTEBOOK:
            logger.debug("Skipping review: notebook %s has %d active notes", nb_id[:8], len(active_notes))
            return 0

        # Mark stale quotes before adding new notes
        await _mark_stale_quotes(hb.db, active_notes, user_content)

        # Truncate content window
        if len(user_content) > MAX_REVIEW_CONTENT_CHARS:
            user_content = user_content[-MAX_REVIEW_CONTENT_CHARS:]
            logger.debug("Truncated review content for notebook %s", nb_id[:8])

        # Build review prompt
        prompt = await _build_review_prompt(user_content, active_notes)
        model = getattr(hb, "background_model", None) or "test/model"

        response = await hb.llm_provider.complete(
            messages=[{"role": "system", "content": prompt}],
            temperature=0.4,
            max_tokens=1500,
            model=model,
        )

        parsed = _parse_observations(response.content)
        observations = parsed.get("observations", [])

        # Insert valid observations
        inserted_ids = []
        for obs in observations:
            quote = obs.get("quote", "").strip()
            comment = obs.get("comment", "").strip()
            if not quote or not comment:
                continue
            if quote.lower() not in user_content.lower():
                logger.debug("Skipping hallucinated quote: %r", quote[:60])
                continue

            entry_id = str(uuid.uuid4())
            await hb.db.execute(
                "INSERT INTO notebook_entries "
                "(id, notebook_id, content, entry_type, status, quote, trigger_type) "
                "VALUES (?, ?, ?, 'agent', 'active', ?, 'heartbeat')",
                (entry_id, nb_id, comment, quote),
            )
            inserted_ids.append(entry_id)

        # Update last_reviewed_at regardless of whether observations were found
        now_iso = datetime.now(timezone.utc).isoformat()
        await hb.db.execute(
            "UPDATE notebooks SET last_reviewed_at = ? WHERE id = ?",
            (now_iso, nb_id),
        )

        # Regenerate backup files
        if inserted_ids:
            try:
                from odigos.api.notebooks import _backup_to_disk
                await _backup_to_disk(hb.db, nb_id)
            except Exception:
                logger.debug("Backup after review failed", exc_info=True)

            # Publish WebSocket + notifications
            for entry_id in inserted_ids:
                try:
                    if hasattr(hb, "message_bus") and hb.message_bus:
                        await hb.message_bus.publish(
                            {"type": "note_added", "notebook_id": nb_id, "entry_id": entry_id},
                        )
                except Exception:
                    logger.debug("message_bus publish failed", exc_info=True)

                try:
                    if hasattr(hb, "notifier") and hb.notifier:
                        await hb.notifier.create(
                            type="suggestion",
                            title=f"Agent reviewed {nb_title}",
                            body=comment[:200],
                            metadata={"notebook_id": nb_id, "entry_id": entry_id},
                        )
                except Exception:
                    logger.debug("notifier.create failed", exc_info=True)

        logger.info(
            "Notebook review: %s (%d observations added)", nb_title, len(inserted_ids),
        )
        return 1

    except Exception:
        logger.debug("Notebook review failed", exc_info=True)
        return 0


async def _pick_notebook(db) -> dict | None:
    """Find the oldest share_with_agent=true notebook not reviewed recently."""
    cutoff = (
        datetime.now(timezone.utc) - _hours(REVIEW_INTERVAL_HOURS)
    ).isoformat()
    row = await db.fetch_one(
        "SELECT id, title, last_reviewed_at FROM notebooks "
        "WHERE share_with_agent = 1 "
        "AND (last_reviewed_at IS NULL OR last_reviewed_at < ?) "
        "ORDER BY COALESCE(last_reviewed_at, '1970-01-01') ASC LIMIT 1",
        (cutoff,),
    )
    return dict(row) if row else None


def _hours(n: int):
    from datetime import timedelta
    return timedelta(hours=n)


async def _load_user_content(db, notebook_id: str) -> str:
    """Concatenate all user entries into a single string."""
    rows = await db.fetch_all(
        "SELECT content FROM notebook_entries "
        "WHERE notebook_id = ? AND entry_type = 'user' AND status = 'active' "
        "ORDER BY created_at ASC",
        (notebook_id,),
    )
    return "\n\n".join(r["content"] for r in rows if r.get("content"))


async def _load_existing_agent_notes(db, notebook_id: str) -> list[dict]:
    rows = await db.fetch_all(
        "SELECT id, content, quote, status FROM notebook_entries "
        "WHERE notebook_id = ? AND entry_type = 'agent' "
        "ORDER BY created_at DESC",
        (notebook_id,),
    )
    return [dict(r) for r in rows]


async def _mark_stale_quotes(db, active_notes: list[dict], content: str) -> None:
    """Mark active agent notes whose quotes no longer exist in the content."""
    content_lower = content.lower()
    for note in active_notes:
        quote = note.get("quote")
        if not quote:
            continue
        if quote.lower() not in content_lower:
            await db.execute(
                "UPDATE notebook_entries SET status = 'stale' WHERE id = ?",
                (note["id"],),
            )
            logger.debug("Marked note %s as stale", note["id"][:8])


async def _build_review_prompt(user_content: str, existing_notes: list[dict]) -> str:
    """Build the review prompt from the template."""
    prompt_path = Path("data/prompts/notebook_review.md")
    if prompt_path.exists():
        template = prompt_path.read_text()
    else:
        template = "Review the notebook and return observations as JSON.\n\n{notebook_content}"

    principles_path = Path("data/agent/behavioral_principles.md")
    principles = ""
    if principles_path.exists():
        raw = principles_path.read_text()
        # Strip frontmatter
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                raw = parts[2]
        principles = raw.strip() or "(none defined)"
    else:
        principles = "(none defined)"

    existing_summary = "\n".join(
        f"- {(n.get('content') or '')[:100]}" for n in existing_notes[:5]
    ) or "(none)"

    return template.format(
        agent_principles=principles,
        existing_notes_summary=existing_summary,
        notebook_content=user_content,
    )


def _parse_observations(text: str) -> dict:
    """Parse JSON response, handling markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text, count=1)
        text = re.sub(r"\n?```\s*$", "", text.rstrip())
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse review JSON: %s", text[:200])
        return {"observations": []}
```

- [ ] **Step 5: Run the review tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_notebook_review.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add data/prompts/notebook_review.md odigos/core/heartbeat/notes_review.py tests/test_notebook_review.py
git commit -m "feat(heartbeat): add notebook review phase with LLM + stale quote detection"
```

---

### Task 6: Wire Review Phase into Heartbeat

**Files:**
- Modify: `odigos/core/heartbeat/orchestrator.py`
- Modify: `odigos/bootstrap.py`

- [ ] **Step 1: Add Phase 9.6 in orchestrator**

In `odigos/core/heartbeat/orchestrator.py`, find Phase 9.5 (memory evolution). After it, before Phase 10, add:

```python
            # Phase 9.6: Notebook review
            if getattr(self, "notes_review_enabled", False):
                try:
                    self.current_phase = "notebook_review"
                    self.current_activity = "Reviewing shared notebooks"
                    from odigos.core.heartbeat import notes_review
                    reviewed = await notes_review.review_notebooks(self)
                    if reviewed > 0:
                        logger.info("Notebook review: %d notebook(s) reviewed", reviewed)
                except Exception:
                    logger.debug("Notebook review phase failed", exc_info=True)
                finally:
                    self.current_phase = None
                    self.current_activity = None
```

- [ ] **Step 2: Enable in bootstrap**

In `odigos/bootstrap.py`, find where the heartbeat is constructed and its other flags are set (e.g., `heartbeat.memory_evolution = ...`). Add:

```python
heartbeat.notes_review_enabled = True
```

If there's a configuration flag pattern, follow it. Otherwise set it unconditionally.

- [ ] **Step 3: Verify imports work**

Run: `cd /Users/jacob/Projects/odigos && python3 -c "from odigos.core.heartbeat.orchestrator import Heartbeat; from odigos.core.heartbeat import notes_review"`
Expected: no errors.

- [ ] **Step 4: Run the review tests again**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_notebook_review.py -v`
Expected: still PASS.

- [ ] **Step 5: Commit**

```bash
git add odigos/core/heartbeat/orchestrator.py odigos/bootstrap.py
git commit -m "feat(heartbeat): wire notebook review phase into orchestrator Phase 9.6"
```

---

### Task 7: Frontend — NoteEntry + NoteTableOfContents Components

**Files:**
- Create: `dashboard/src/components/notes/NoteEntry.tsx`
- Create: `dashboard/src/components/notes/NoteTableOfContents.tsx`

- [ ] **Step 1: Create NoteEntry.tsx**

Create `dashboard/src/components/notes/NoteEntry.tsx`:

```typescript
import { useState } from 'react'
import Markdown from 'react-markdown'
import { cn } from '@/lib/utils'

export interface NotebookEntry {
  id: string
  notebook_id: string
  content: string
  entry_type: 'user' | 'agent' | 'agent_suggestion'
  status: 'active' | 'rejected' | 'dead' | 'stale'
  quote: string | null
  trigger_type: string | null
  viewed_at: string | null
  created_at: string
  parent_id: string | null
}

interface NoteEntryProps {
  entry: NotebookEntry
  onQuoteClick?: (quote: string) => void
  onReplyClick?: (entry: NotebookEntry) => void
  onToggleDead?: (entry: NotebookEntry) => void
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  const now = Date.now()
  const diff = now - then
  const min = Math.floor(diff / 60000)
  if (min < 1) return 'just now'
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h ago`
  const day = Math.floor(hr / 24)
  return `${day}d ago`
}

export function NoteEntry({ entry, onQuoteClick, onReplyClick, onToggleDead }: NoteEntryProps) {
  const isUnread = !entry.viewed_at && entry.status === 'active'
  const isDead = entry.status === 'dead'
  const isStale = entry.status === 'stale'
  const [expanded, setExpanded] = useState(!isDead)

  return (
    <div
      data-note-id={entry.id}
      className={cn(
        'rounded-xl p-3 mb-2 border-l-2 border border-border bg-card transition-opacity',
        'border-l-purple-400',
        isDead && 'opacity-50',
        isStale && 'opacity-70',
      )}
    >
      <div className="flex items-center gap-2 mb-1">
        {isUnread && <div className="size-1.5 rounded-full bg-purple-400" aria-label="unread" />}
        <span className="text-[10px] font-semibold text-muted-foreground tracking-wider uppercase">
          AGENT
        </span>
        {entry.trigger_type && (
          <span className="text-[10px] text-muted-foreground">
            · {entry.trigger_type}
          </span>
        )}
        <span className="text-[10px] text-muted-foreground">
          · {relativeTime(entry.created_at)}
        </span>
        {isDead && (
          <span className="text-[10px] text-muted-foreground">· dead</span>
        )}
        {isStale && (
          <span className="text-[10px] text-muted-foreground">· stale quote</span>
        )}
        {isDead && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="ml-auto text-[10px] text-muted-foreground hover:text-foreground"
          >
            {expanded ? 'collapse' : 'expand'}
          </button>
        )}
      </div>

      {expanded && (
        <>
          {entry.quote && (
            <button
              onClick={() => onQuoteClick?.(entry.quote!)}
              className={cn(
                'block w-full text-left border-l-2 border-muted-foreground/40 pl-2 my-2',
                'text-xs italic text-muted-foreground hover:text-foreground transition-colors',
                isStale && 'line-through',
              )}
              disabled={isStale}
            >
              "{entry.quote}"
              {isStale && <span className="ml-2 not-italic">[quote no longer in document]</span>}
            </button>
          )}
          <div className="text-sm prose prose-invert prose-sm max-w-none">
            <Markdown>{entry.content}</Markdown>
          </div>
          <div className="flex gap-3 mt-2 text-xs">
            {!isDead && onReplyClick && (
              <button
                onClick={() => onReplyClick(entry)}
                className="text-primary hover:underline"
              >
                Reply
              </button>
            )}
            {onToggleDead && (
              <button
                onClick={() => onToggleDead(entry)}
                className="text-muted-foreground hover:text-foreground"
              >
                {isDead ? 'Mark active' : 'Mark dead'}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Create NoteTableOfContents.tsx**

Create `dashboard/src/components/notes/NoteTableOfContents.tsx`:

```typescript
import { useState } from 'react'
import { cn } from '@/lib/utils'
import type { NotebookEntry } from './NoteEntry'

interface NoteTableOfContentsProps {
  entries: NotebookEntry[]
  onJumpTo?: (entryId: string) => void
}

export function NoteTableOfContents({ entries, onJumpTo }: NoteTableOfContentsProps) {
  const [expanded, setExpanded] = useState(false)
  const active = entries.filter((e) => e.status === 'active').length
  const dead = entries.filter((e) => e.status === 'dead').length
  const stale = entries.filter((e) => e.status === 'stale').length

  if (entries.length === 0) return null

  return (
    <div className="mb-3 rounded-xl bg-muted/20 border border-border">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-3 py-2 text-left flex items-center justify-between"
      >
        <span className="text-[10px] font-semibold text-muted-foreground tracking-wider uppercase">
          Contents · {entries.length} {entries.length === 1 ? 'note' : 'notes'}
          {dead > 0 && ` · ${dead} dead`}
          {stale > 0 && ` · ${stale} stale`}
        </span>
        <span className="text-xs text-muted-foreground">{expanded ? '−' : '+'}</span>
      </button>
      {expanded && (
        <div className="px-3 pb-2 space-y-1">
          {entries.map((entry, i) => {
            const preview = entry.content.slice(0, 60).replace(/\n/g, ' ')
            const time = new Date(entry.created_at).toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            })
            return (
              <button
                key={entry.id}
                onClick={() => onJumpTo?.(entry.id)}
                className={cn(
                  'block w-full text-left text-xs text-muted-foreground hover:text-foreground',
                  entry.status === 'dead' && 'line-through',
                )}
              >
                {i + 1}. [{time} · agent] {preview}
                {entry.status === 'dead' && ' (dead)'}
                {entry.status === 'stale' && ' (stale)'}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Type check**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/notes/NoteEntry.tsx dashboard/src/components/notes/NoteTableOfContents.tsx
git commit -m "feat(dashboard): add NoteEntry and NoteTableOfContents components"
```

---

### Task 8: Frontend — NoteSidecar Main Panel

**Files:**
- Create: `dashboard/src/components/notes/NoteSidecar.tsx`

- [ ] **Step 1: Create NoteSidecar.tsx**

Create `dashboard/src/components/notes/NoteSidecar.tsx`:

```typescript
import { useCallback, useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { NoteEntry, type NotebookEntry } from './NoteEntry'
import { NoteTableOfContents } from './NoteTableOfContents'

interface NoteSidecarProps {
  notebookId: string
  onQuoteClick?: (quote: string) => void
  onReplyClick?: (quote: string) => void
}

export function NoteSidecar({ notebookId, onQuoteClick, onReplyClick }: NoteSidecarProps) {
  const [entries, setEntries] = useState<NotebookEntry[]>([])
  const [showDead, setShowDead] = useState(false)
  const [loading, setLoading] = useState(true)
  const [unreadCount, setUnreadCount] = useState(0)
  const observersRef = useRef<Map<string, IntersectionObserver>>(new Map())

  const fetchEntries = useCallback(async () => {
    try {
      const url = `/api/notebooks/${notebookId}/entries?entry_type=agent&include_dead=${showDead}`
      const resp = await fetch(url)
      if (!resp.ok) {
        setLoading(false)
        return
      }
      const data = await resp.json()
      setEntries(data.entries || [])
      setUnreadCount(data.unread_count || 0)
      setLoading(false)
    } catch {
      setLoading(false)
    }
  }, [notebookId, showDead])

  useEffect(() => {
    void fetchEntries()
  }, [fetchEntries])

  // WebSocket subscription would go here — for now, we refetch on focus
  useEffect(() => {
    const handleFocus = () => void fetchEntries()
    window.addEventListener('focus', handleFocus)
    return () => window.removeEventListener('focus', handleFocus)
  }, [fetchEntries])

  const markViewed = useCallback(
    async (entryId: string) => {
      try {
        await fetch(
          `/api/notebooks/${notebookId}/entries/${entryId}/view`,
          { method: 'POST' },
        )
      } catch {
        // Non-critical
      }
    },
    [notebookId],
  )

  const markReadRef = useCallback(
    (node: HTMLDivElement | null) => {
      if (!node) return
      const id = node.dataset.noteId
      if (!id) return
      const prev = observersRef.current.get(id)
      if (prev) prev.disconnect()

      const observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            const el = entry.target as HTMLDivElement & {
              _readTimer?: ReturnType<typeof setTimeout>
            }
            if (entry.isIntersecting) {
              el._readTimer = setTimeout(() => void markViewed(id), 500)
            } else if (el._readTimer) {
              clearTimeout(el._readTimer)
            }
          })
        },
        { threshold: 0.5 },
      )
      observer.observe(node)
      observersRef.current.set(id, observer)
    },
    [markViewed],
  )

  useEffect(() => {
    return () => {
      observersRef.current.forEach((obs) => obs.disconnect())
      observersRef.current.clear()
    }
  }, [])

  const handleMarkAllViewed = async () => {
    try {
      await fetch(
        `/api/notebooks/${notebookId}/mark-all-viewed?entry_type=agent`,
        { method: 'POST' },
      )
      void fetchEntries()
    } catch {
      // Non-critical
    }
  }

  const handleToggleDead = async (entry: NotebookEntry) => {
    const newStatus = entry.status === 'dead' ? 'active' : 'dead'
    try {
      await fetch(
        `/api/notebooks/${notebookId}/entries/${entry.id}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: newStatus }),
        },
      )
      void fetchEntries()
    } catch {
      // Non-critical
    }
  }

  const handleReply = (entry: NotebookEntry) => {
    if (!entry.quote) return
    onReplyClick?.(entry.quote)
  }

  const handleJumpTo = (entryId: string) => {
    const el = document.querySelector(`[data-note-id="${entryId}"]`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      el.classList.add('ring-2', 'ring-primary', 'ring-offset-2')
      setTimeout(() => {
        el.classList.remove('ring-2', 'ring-primary', 'ring-offset-2')
      }, 1500)
    }
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between p-3 border-b border-border">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold">Notes</h2>
          {unreadCount > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-sm bg-purple-500/10 text-purple-400">
              {unreadCount} new
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs">
          <button
            onClick={() => setShowDead(!showDead)}
            className="text-muted-foreground hover:text-foreground"
          >
            {showDead ? 'hide dead' : 'show dead'}
          </button>
          {unreadCount > 0 && (
            <button
              onClick={handleMarkAllViewed}
              className="text-muted-foreground hover:text-foreground"
            >
              mark all read
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {loading ? (
          <div className="text-sm text-muted-foreground">Loading...</div>
        ) : entries.length === 0 ? (
          <div className="text-sm text-muted-foreground">
            The agent hasn't reviewed this notebook yet. Share with agent and it will review during idle time.
          </div>
        ) : (
          <>
            <NoteTableOfContents entries={entries} onJumpTo={handleJumpTo} />
            {entries.map((entry) => (
              <div
                key={entry.id}
                ref={!entry.viewed_at ? markReadRef : undefined}
                data-note-id={entry.id}
              >
                <NoteEntry
                  entry={entry}
                  onQuoteClick={onQuoteClick}
                  onReplyClick={handleReply}
                  onToggleDead={handleToggleDead}
                />
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Type check**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/notes/NoteSidecar.tsx
git commit -m "feat(dashboard): add NoteSidecar main panel with fetch, view tracking, actions"
```

---

### Task 9: Integrate NoteSidecar into NotebookPage

**Files:**
- Modify: `dashboard/src/pages/NotebookPage.tsx`
- Modify: `dashboard/src/components/AgentInputBar.tsx` (add prefill prop)

- [ ] **Step 1: Add prefill prop to AgentInputBar**

In `dashboard/src/components/AgentInputBar.tsx`, add an optional `prefill` prop. Find the component's props interface and add:

```typescript
interface AgentInputBarProps {
  // ... existing props ...
  prefill?: string | null
  onPrefillConsumed?: () => void
}
```

In the component body, when `prefill` changes and is non-null, set the input value:

```typescript
useEffect(() => {
  if (prefill) {
    setInputValue(prefill)
    onPrefillConsumed?.()
    // Focus the input
    inputRef.current?.focus()
  }
}, [prefill, onPrefillConsumed])
```

(The exact field names depend on the existing component structure — read the file first to adapt.)

- [ ] **Step 2: Integrate NoteSidecar into NotebookPage**

In `dashboard/src/pages/NotebookPage.tsx`, add these changes at the top:

```typescript
import { NoteSidecar } from '@/components/notes/NoteSidecar'
```

Add state inside the component:

```typescript
const [showNotes, setShowNotes] = useState(false)
const [replyPrefill, setReplyPrefill] = useState<string | null>(null)
const [unreadNoteCount, setUnreadNoteCount] = useState(0)
```

Add an effect that checks unread count on load and opens the panel if there are unread notes:

```typescript
useEffect(() => {
  async function checkUnread() {
    try {
      const resp = await fetch(
        `/api/notebooks/${notebookId}/entries?entry_type=agent`,
      )
      if (resp.ok) {
        const data = await resp.json()
        setUnreadNoteCount(data.unread_count || 0)
        if (data.unread_count > 0) {
          setShowNotes(true)
        }
      }
    } catch {
      // Non-critical
    }
  }
  if (notebookId) void checkUnread()
}, [notebookId])
```

Add the handlers:

```typescript
const handleQuoteClick = useCallback((quote: string) => {
  // Best-effort: find the quote in the editor content and scroll to it
  // For now, just show a toast if not found
  const content = document.querySelector('.ProseMirror')?.textContent || ''
  const idx = content.toLowerCase().indexOf(quote.toLowerCase())
  if (idx === -1) {
    // Could integrate with existing toast system here
    console.warn('Quoted text no longer in document')
  }
  // The actual scroll/highlight integration depends on the editor ref — deferred
}, [])

const handleReplyClick = useCallback((quote: string) => {
  setReplyPrefill(`> ${quote}\n\n`)
}, [])
```

Add the Notes toggle button in the header. Find the existing header/toolbar area and add:

```tsx
<button
  onClick={() => setShowNotes(!showNotes)}
  className="text-xs text-muted-foreground hover:text-foreground px-2 py-1"
>
  Notes{unreadNoteCount > 0 && ` (${unreadNoteCount})`}
</button>
```

Add the layout wrapper around the editor + notes. Find where the main editor is rendered and wrap it:

```tsx
<div className="flex h-full relative">
  <div className={showNotes ? "flex-1 min-w-0 md:pr-0" : "w-full"}>
    {/* existing editor goes here */}
  </div>

  {/* Desktop split view */}
  {showNotes && (
    <div className="hidden md:block md:w-[40%] border-l border-border overflow-y-auto">
      <NoteSidecar
        notebookId={notebookId}
        onQuoteClick={handleQuoteClick}
        onReplyClick={handleReplyClick}
      />
    </div>
  )}

  {/* Mobile bottom sheet */}
  {showNotes && (
    <div
      className="md:hidden fixed inset-x-0 bottom-0 top-16 z-40 bg-background border-t border-border overflow-y-auto rounded-t-2xl shadow-lg"
      onClick={(e) => e.target === e.currentTarget && setShowNotes(false)}
    >
      <NoteSidecar
        notebookId={notebookId}
        onQuoteClick={handleQuoteClick}
        onReplyClick={handleReplyClick}
      />
    </div>
  )}
</div>
```

Pass the prefill to the existing AgentInputBar:

```tsx
<AgentInputBar
  // ... existing props ...
  prefill={replyPrefill}
  onPrefillConsumed={() => setReplyPrefill(null)}
/>
```

- [ ] **Step 3: Type check + build**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx tsc --noEmit && npm run build 2>&1 | tail -10`
Expected: type check clean, build succeeds.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/pages/NotebookPage.tsx dashboard/src/components/AgentInputBar.tsx
git commit -m "feat(dashboard): integrate NoteSidecar into NotebookPage with split view"
```

---

### Task 10: Final Smoke Test

- [ ] **Step 1: Run all new backend tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_notebooks_notes.py tests/test_notebook_review.py -v`
Expected: All pass.

- [ ] **Step 2: Run full backend test suite for regressions**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/ -x -q`
Expected: No new failures compared to baseline.

- [ ] **Step 3: Dashboard type check + build**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx tsc --noEmit && npm run build 2>&1 | tail -10`
Expected: clean.

- [ ] **Step 4: Docker smoke test**

Run: `cd /Users/jacob/Projects/odigos && make build && make up && sleep 5 && make logs 2>&1 | tail -20`
Expected: Container starts cleanly, no import errors.

- [ ] **Step 5: Manual verification**

Open the dashboard, navigate to a notebook with `share_with_agent=true`. Verify:
- The Notes button appears in the notebook header
- If agent has added notes, panel opens automatically with unread indicator
- Clicking a quote attempts to jump (or logs a warning if not found)
- Clicking Reply fills the AgentInputBar with a quote block
- Clicking Mark dead updates the entry status
- "show dead" toggle works
- "mark all read" clears unread badges

- [ ] **Step 6: Commit any final fixes**

```bash
git add -A && git commit -m "fix: polish and cleanup for notebook review sidecar"
```
