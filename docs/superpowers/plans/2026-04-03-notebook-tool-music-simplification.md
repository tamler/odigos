# Notebook Tool + Music Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the agent write access to notebooks, simplify music generation to one tool, and add content search to workspace search.

**Architecture:** New `manage_notebook` tool using existing `ResourceStore` and DB schema. Music gen collapsed from two tools to one that takes lyrics directly. Workspace search extended with entry content matching.

**Tech Stack:** Python 3.12, FastAPI, aiosqlite, React 19, TypeScript

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `odigos/tools/notebook.py` | Create | `manage_notebook` tool — create/append/read/list notebooks |
| `tests/test_notebook_tool.py` | Create | Tests for notebook tool |
| `odigos/tools/workspace_search.py` | Modify | Add content search to existing title search |
| `tests/test_workspace_search.py` | Modify | Add content search tests |
| `odigos/tools/music_gen.py` | Rewrite | Single `GenerateMusicTool` taking lyrics directly |
| `tests/test_music_gen.py` | Create | Tests for simplified music tool |
| `odigos/main.py` | Modify | Register notebook tool, simplify music registration |
| `data/agent/capabilities.md` | Modify | Update music flow, add notebook capabilities |
| `dashboard/src/components/ArtifactPreview.tsx` | Modify | Remove SongEditor, SongData, .song.json handling |
| `dashboard/src/layouts/AppLayout.tsx` | Modify | Remove socketRef from ArtifactPreview props |

---

### Task 1: Notebook Tool — Core Implementation

**Files:**
- Create: `odigos/tools/notebook.py`
- Create: `tests/test_notebook_tool.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_notebook_tool.py
"""Tests for manage_notebook tool."""
import pytest
from odigos.db import Database
from odigos.tools.notebook import ManageNotebookTool


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    await d.initialize()
    return d


@pytest.fixture
def tool(db):
    return ManageNotebookTool(db=db)


class TestNotebookCreate:
    @pytest.mark.asyncio
    async def test_create_notebook(self, tool):
        result = await tool.execute({"action": "create", "title": "My Recipes"})
        assert result.success
        assert "My Recipes" in result.data
        assert "/notebooks/" in result.data

    @pytest.mark.asyncio
    async def test_create_with_initial_content(self, tool):
        result = await tool.execute({
            "action": "create",
            "title": "Cat Song Lyrics",
            "content": "Verse 1: My cat sits on the mat...",
            "mode": "creative",
        })
        assert result.success
        assert "Cat Song Lyrics" in result.data

        # Verify entry was created by reading back
        nb_id = result.side_effect["notebook_id"]
        read_result = await tool.execute({"action": "read", "notebook_id": nb_id})
        assert read_result.success
        assert "My cat sits on the mat" in read_result.data

    @pytest.mark.asyncio
    async def test_create_requires_title(self, tool):
        result = await tool.execute({"action": "create"})
        assert not result.success
        assert "title" in result.error.lower()


class TestNotebookAppend:
    @pytest.mark.asyncio
    async def test_append_entry(self, tool):
        create = await tool.execute({"action": "create", "title": "Notes"})
        nb_id = create.side_effect["notebook_id"]

        result = await tool.execute({
            "action": "append",
            "notebook_id": nb_id,
            "content": "Remember to buy milk",
        })
        assert result.success

    @pytest.mark.asyncio
    async def test_append_requires_notebook_id(self, tool):
        result = await tool.execute({"action": "append", "content": "Hello"})
        assert not result.success
        assert "notebook_id" in result.error.lower()

    @pytest.mark.asyncio
    async def test_append_to_nonexistent_notebook(self, tool):
        result = await tool.execute({
            "action": "append",
            "notebook_id": "nonexistent",
            "content": "Hello",
        })
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_append_respects_readonly(self, tool, db):
        # Create a read-only notebook directly in DB
        await db.execute(
            "INSERT INTO notebooks (id, title, collaboration, created_at, updated_at) "
            "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            ("ro-nb", "Read Only", "read"),
        )
        result = await tool.execute({
            "action": "append",
            "notebook_id": "ro-nb",
            "content": "Should fail",
        })
        assert not result.success
        assert "read" in result.error.lower()


class TestNotebookRead:
    @pytest.mark.asyncio
    async def test_read_entries(self, tool):
        create = await tool.execute({
            "action": "create",
            "title": "Test",
            "content": "Entry one",
        })
        nb_id = create.side_effect["notebook_id"]
        await tool.execute({"action": "append", "notebook_id": nb_id, "content": "Entry two"})

        result = await tool.execute({"action": "read", "notebook_id": nb_id})
        assert result.success
        assert "Entry one" in result.data
        assert "Entry two" in result.data

    @pytest.mark.asyncio
    async def test_read_nonexistent(self, tool):
        result = await tool.execute({"action": "read", "notebook_id": "nope"})
        assert not result.success


class TestNotebookList:
    @pytest.mark.asyncio
    async def test_list_notebooks(self, tool):
        await tool.execute({"action": "create", "title": "Notebook A"})
        await tool.execute({"action": "create", "title": "Notebook B"})

        result = await tool.execute({"action": "list"})
        assert result.success
        assert "Notebook A" in result.data
        assert "Notebook B" in result.data

    @pytest.mark.asyncio
    async def test_list_empty(self, tool):
        result = await tool.execute({"action": "list"})
        assert result.success
        assert "No notebooks" in result.data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_notebook_tool.py -v`
Expected: ImportError — `odigos.tools.notebook` does not exist yet

- [ ] **Step 3: Implement the notebook tool**

```python
# odigos/tools/notebook.py
"""Notebook management tool — create, append, read, list notebooks."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.db import Database

logger = logging.getLogger(__name__)

BACKUP_DIR = Path("data/notebooks")


class ManageNotebookTool(BaseTool):
    name = "manage_notebook"
    category = "productivity"
    description = (
        "Create and write to notebooks. Use for notes, recipes, lyrics, "
        "meeting summaries, research, or any content the user might want to "
        "review and edit. Actions: create (new notebook), append (add entry), "
        "read (get entries), list (all notebooks)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "append", "read", "list"],
                "description": "Action to perform",
            },
            "notebook_id": {
                "type": "string",
                "description": "Notebook ID (required for append/read)",
            },
            "title": {
                "type": "string",
                "description": "Notebook title (required for create)",
            },
            "content": {
                "type": "string",
                "description": "Entry content (for create with initial entry, and append)",
            },
            "mode": {
                "type": "string",
                "enum": ["general", "journal", "research", "creative", "meetings"],
                "description": "Notebook mode (default: general)",
            },
            "limit": {
                "type": "integer",
                "description": "Max entries to return for read (default: 20)",
            },
        },
        "required": ["action"],
    }

    def __init__(self, db: Database) -> None:
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        action = params.get("action", "")
        if action == "create":
            return await self._create(params)
        elif action == "append":
            return await self._append(params)
        elif action == "read":
            return await self._read(params)
        elif action == "list":
            return await self._list()
        return ToolResult(success=False, data="", error=f"Unknown action: {action}")

    async def _create(self, params: dict) -> ToolResult:
        title = (params.get("title") or "").strip()
        if not title:
            return ToolResult(success=False, data="", error="Title is required for create")

        content = (params.get("content") or "").strip()
        mode = params.get("mode", "general")
        now = datetime.now(timezone.utc).isoformat()
        nb_id = uuid.uuid4().hex

        await self._db.execute(
            "INSERT INTO notebooks (id, title, mode, collaboration, share_with_agent, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (nb_id, title, mode, "active", 1, now, now),
        )

        if content:
            entry_id = uuid.uuid4().hex
            await self._db.execute(
                "INSERT INTO notebook_entries (id, notebook_id, content, entry_type, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (entry_id, nb_id, content, "agent", "active", now, now),
            )
            await self._backup(nb_id)

        logger.info("Created notebook %s: %s", nb_id[:8], title)
        return ToolResult(
            success=True,
            data=f"Created notebook \"{title}\" (path: /notebooks/{nb_id})",
            side_effect={"notebook_id": nb_id, "path": f"/notebooks/{nb_id}"},
        )

    async def _append(self, params: dict) -> ToolResult:
        nb_id = (params.get("notebook_id") or "").strip()
        content = (params.get("content") or "").strip()

        if not nb_id:
            return ToolResult(success=False, data="", error="notebook_id is required for append")
        if not content:
            return ToolResult(success=False, data="", error="content is required for append")

        nb = await self._db.fetchone("SELECT id, title, collaboration FROM notebooks WHERE id = ?", (nb_id,))
        if not nb:
            return ToolResult(success=False, data="", error=f"Notebook not found: {nb_id}")

        collab = nb["collaboration"] if isinstance(nb, dict) else nb[2]
        title = nb["title"] if isinstance(nb, dict) else nb[1]
        if collab == "read":
            return ToolResult(
                success=False, data="",
                error=f"Notebook \"{title}\" is read-only. Ask the user to change collaboration to 'active' or 'suggest'.",
            )

        now = datetime.now(timezone.utc).isoformat()
        entry_id = uuid.uuid4().hex
        await self._db.execute(
            "INSERT INTO notebook_entries (id, notebook_id, content, entry_type, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (entry_id, nb_id, content, "agent", "active", now, now),
        )
        await self._db.execute(
            "UPDATE notebooks SET updated_at = ? WHERE id = ?", (now, nb_id),
        )
        await self._backup(nb_id)

        logger.info("Appended entry to notebook %s", nb_id[:8])
        return ToolResult(
            success=True,
            data=f"Added entry to \"{title}\" (path: /notebooks/{nb_id})",
            side_effect={"notebook_id": nb_id, "entry_id": entry_id},
        )

    async def _read(self, params: dict) -> ToolResult:
        nb_id = (params.get("notebook_id") or "").strip()
        if not nb_id:
            return ToolResult(success=False, data="", error="notebook_id is required for read")

        nb = await self._db.fetchone("SELECT id, title, mode FROM notebooks WHERE id = ?", (nb_id,))
        if not nb:
            return ToolResult(success=False, data="", error=f"Notebook not found: {nb_id}")

        title = nb["title"] if isinstance(nb, dict) else nb[1]
        mode = nb["mode"] if isinstance(nb, dict) else nb[2]
        limit = min(params.get("limit", 20), 50)

        entries = await self._db.fetch_all(
            "SELECT content, entry_type, created_at FROM notebook_entries "
            "WHERE notebook_id = ? AND status != 'rejected' "
            "ORDER BY created_at ASC LIMIT ?",
            (nb_id, limit),
        )

        if not entries:
            return ToolResult(
                success=True,
                data=f"Notebook \"{title}\" ({mode}) — no entries yet.",
            )

        lines = [f"Notebook: \"{title}\" (mode: {mode})\n"]
        for entry in entries:
            content = entry["content"] if isinstance(entry, dict) else entry[0]
            entry_type = entry["entry_type"] if isinstance(entry, dict) else entry[1]
            created = entry["created_at"] if isinstance(entry, dict) else entry[2]
            # Truncate long entries to avoid bloating agent context
            if len(content) > 2000:
                content = content[:2000] + "... (truncated)"
            lines.append(f"[{entry_type}] ({created[:10]})")
            lines.append(content)
            lines.append("")

        return ToolResult(success=True, data="\n".join(lines))

    async def _list(self) -> ToolResult:
        notebooks = await self._db.fetch_all(
            "SELECT id, title, mode, updated_at FROM notebooks ORDER BY updated_at DESC LIMIT 20",
        )

        if not notebooks:
            return ToolResult(success=True, data="No notebooks yet.")

        lines = []
        for nb in notebooks:
            nb_id = nb["id"] if isinstance(nb, dict) else nb[0]
            title = nb["title"] if isinstance(nb, dict) else nb[1]
            mode = nb["mode"] if isinstance(nb, dict) else nb[2]
            updated = nb["updated_at"] if isinstance(nb, dict) else nb[3]
            lines.append(
                f"- \"{title}\" ({mode}, updated: {updated[:10]}, "
                f"id: {nb_id}, path: /notebooks/{nb_id})"
            )

        return ToolResult(success=True, data="\n".join(lines))

    async def _backup(self, notebook_id: str) -> None:
        """Export notebook + entries to markdown file."""
        try:
            nb = await self._db.fetchone("SELECT * FROM notebooks WHERE id = ?", (notebook_id,))
            if not nb:
                return

            title = nb["title"] if isinstance(nb, dict) else nb[1]
            mode = nb["mode"] if isinstance(nb, dict) else nb[2]
            collab = nb["collaboration"] if isinstance(nb, dict) else nb[3]
            share = nb["share_with_agent"] if isinstance(nb, dict) else nb[4]

            entries = await self._db.fetch_all(
                "SELECT * FROM notebook_entries WHERE notebook_id = ? AND status != 'rejected' "
                "ORDER BY created_at ASC",
                (notebook_id,),
            )

            share_label = "yes" if share else "no"
            lines = [
                f"# {title}",
                f"Mode: {mode} | Collaboration: {collab} | Share: {share_label}",
                "",
            ]

            for entry in entries:
                content = entry["content"] if isinstance(entry, dict) else entry[2]
                created = entry["created_at"] if isinstance(entry, dict) else entry[6]
                mood = (entry["mood"] if isinstance(entry, dict) else entry[5]) or ""
                lines.append("---")
                lines.append("")
                lines.append(f"## {created}")
                if mood:
                    lines.append(f"Mood: {mood}")
                lines.append("")
                lines.append(content)
                lines.append("")

            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            (BACKUP_DIR / f"{notebook_id}.md").write_text("\n".join(lines), encoding="utf-8")
        except Exception as exc:
            logger.warning("Notebook backup failed for %s: %s", notebook_id[:8], exc)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_notebook_tool.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add odigos/tools/notebook.py tests/test_notebook_tool.py
git commit -m "feat: manage_notebook tool — agent can create/write to notebooks"
```

---

### Task 2: Workspace Search — Content Search

**Files:**
- Modify: `odigos/tools/workspace_search.py`
- Modify: `tests/test_workspace_search.py`

- [ ] **Step 1: Add failing tests for content search**

Append to `tests/test_workspace_search.py`:

```python
    @pytest.mark.asyncio
    async def test_find_notebook_by_content(self, db):
        """Search should find notebooks by entry content, not just title."""
        await db.execute(
            "INSERT INTO notebooks (id, title, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("nb-content", "Creative Ideas"),
        )
        await db.execute(
            "INSERT INTO notebook_entries (id, notebook_id, content, entry_type, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("e1", "nb-content", "Lyrics about a cat who travels the world", "user", "active"),
        )
        tool = WorkspaceSearchTool(db=db)
        result = await tool.execute({"query": "cat travels"})
        assert result.success
        assert "Creative Ideas" in result.data
        assert "cat" in result.data.lower()

    @pytest.mark.asyncio
    async def test_title_match_preferred_over_content(self, db):
        """Title matches should appear; content search fills gaps."""
        await db.execute(
            "INSERT INTO notebooks (id, title, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("nb-title", "Cat Songs"),
        )
        await db.execute(
            "INSERT INTO notebooks (id, title, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("nb-other", "Random Notes"),
        )
        await db.execute(
            "INSERT INTO notebook_entries (id, notebook_id, content, entry_type, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("e2", "nb-other", "I saw a cat today", "user", "active"),
        )
        tool = WorkspaceSearchTool(db=db)
        result = await tool.execute({"query": "cat"})
        assert result.success
        assert "Cat Songs" in result.data
        assert "Random Notes" in result.data
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `pytest tests/test_workspace_search.py -v`
Expected: The two new tests FAIL (content search not implemented)

- [ ] **Step 3: Implement content search**

Replace the full `execute` method in `odigos/tools/workspace_search.py`:

```python
    async def execute(self, params: dict) -> ToolResult:
        query = params.get("query", "").strip()
        search_type = params.get("type", "all")

        if not query:
            return ToolResult(success=False, data="", error="Query is required")

        results = []
        pattern = f"%{query}%"
        title_matched_nb_ids: set[str] = set()

        if search_type in ("notebook", "all"):
            # Title search first
            notebooks = await self.db.fetch_all(
                "SELECT id, title, updated_at FROM notebooks "
                "WHERE title LIKE ? ORDER BY updated_at DESC LIMIT 5",
                (pattern,),
            )
            for nb in notebooks:
                title_matched_nb_ids.add(nb["id"])
                results.append(
                    f"Notebook: \"{nb['title']}\" (id: {nb['id']}, "
                    f"updated: {nb['updated_at'][:10]}, "
                    f"path: /notebooks/{nb['id']})"
                )

            # Content search for notebooks not already matched by title
            if len(results) < 5:
                remaining = 5 - len(results)
                placeholders = ",".join("?" for _ in title_matched_nb_ids) if title_matched_nb_ids else "''"
                exclude_ids = list(title_matched_nb_ids) if title_matched_nb_ids else []

                content_query = (
                    "SELECT DISTINCT n.id, n.title, n.updated_at, "
                    "SUBSTR(e.content, MAX(1, INSTR(LOWER(e.content), LOWER(?)) - 40), 100) AS snippet "
                    "FROM notebook_entries e "
                    "JOIN notebooks n ON n.id = e.notebook_id "
                    "WHERE e.content LIKE ? AND e.status != 'rejected'"
                )
                query_params: list = [query, pattern]

                if exclude_ids:
                    content_query += f" AND n.id NOT IN ({placeholders})"
                    query_params.extend(exclude_ids)

                content_query += " ORDER BY e.updated_at DESC LIMIT ?"
                query_params.append(remaining)

                content_matches = await self.db.fetch_all(content_query, tuple(query_params))
                for row in content_matches:
                    snippet = row["snippet"] if isinstance(row, dict) else row[3]
                    title = row["title"] if isinstance(row, dict) else row[1]
                    nb_id = row["id"] if isinstance(row, dict) else row[0]
                    updated = row["updated_at"] if isinstance(row, dict) else row[2]
                    results.append(
                        f"Notebook: \"{title}\" (id: {nb_id}, "
                        f"updated: {updated[:10]}, "
                        f"path: /notebooks/{nb_id})\n"
                        f"  Match: \"...{snippet.strip()}...\""
                    )

        if search_type in ("board", "all"):
            boards = await self.db.fetch_all(
                "SELECT id, title, updated_at FROM kanban_boards "
                "WHERE title LIKE ? ORDER BY updated_at DESC LIMIT 5",
                (pattern,),
            )
            for b in boards:
                results.append(
                    f"Board: \"{b['title']}\" (id: {b['id']}, "
                    f"updated: {b['updated_at'][:10]}, "
                    f"path: /kanban/{b['id']})"
                )

        if not results:
            return ToolResult(
                success=True,
                data=f"No notebooks or boards found matching \"{query}\".",
            )

        return ToolResult(
            success=True,
            data="\n".join(results),
        )
```

Update the tool description:

```python
    description = (
        "Search for notebooks and kanban boards by name or content. "
        "Use when the user refers to a workspace item by name or topic "
        '(e.g., "open my journal", "find my cat lyrics", "the recipe I saved"). '
        "Searches titles first, then entry content. Returns matching items with IDs."
    )
```

- [ ] **Step 4: Run all workspace search tests**

Run: `pytest tests/test_workspace_search.py -v`
Expected: All 6 tests PASS (4 existing + 2 new)

- [ ] **Step 5: Commit**

```bash
git add odigos/tools/workspace_search.py tests/test_workspace_search.py
git commit -m "feat: workspace search — find notebooks by content, not just title"
```

---

### Task 3: Simplify Music Tool — Rewrite music_gen.py

**Files:**
- Rewrite: `odigos/tools/music_gen.py`
- Create: `tests/test_music_gen.py`

- [ ] **Step 1: Write failing tests for the new single-tool interface**

```python
# tests/test_music_gen.py
"""Tests for simplified GenerateMusicTool (single tool, no draft step)."""
import pytest
from unittest.mock import AsyncMock, patch
from odigos.tools.music_gen import GenerateMusicTool


@pytest.fixture
def tool(tmp_path):
    return GenerateMusicTool(
        api_key="test-key",
        provider="suno",
        task_type="suno_music",
        model="V5",
        max_poll_seconds=10,
        output_dir=str(tmp_path),
        db=None,
    )


class TestGenerateMusicParams:
    @pytest.mark.asyncio
    async def test_requires_prompt(self, tool):
        result = await tool.execute({"prompt": ""})
        assert not result.success
        assert "prompt" in result.error.lower()

    def test_tool_name(self, tool):
        assert tool.name == "generate_music"

    def test_no_artifact_id_param(self, tool):
        """The old submit_music required artifact_id. The new tool should not."""
        props = tool.parameters_schema["properties"]
        assert "artifact_id" not in props
        assert "prompt" in props

    def test_has_style_and_title_params(self, tool):
        props = tool.parameters_schema["properties"]
        assert "style" in props
        assert "title" in props
        assert "instrumental" in props
        assert "vocal_gender" in props


class TestVocalGenderMapping:
    def test_male_maps_to_m(self):
        assert GenerateMusicTool._map_vocal_gender("male") == "m"

    def test_female_maps_to_f(self):
        assert GenerateMusicTool._map_vocal_gender("female") == "f"

    def test_m_passes_through(self):
        assert GenerateMusicTool._map_vocal_gender("m") == "m"

    def test_empty_stays_empty(self):
        assert GenerateMusicTool._map_vocal_gender("") == ""


class TestExtractTracks:
    def test_dict_with_sunoData(self):
        response = {"sunoData": [{"audioUrl": "http://example.com/a.mp3", "title": "Song"}]}
        tracks = GenerateMusicTool._extract_tracks(response)
        assert len(tracks) == 1
        assert tracks[0]["audioUrl"] == "http://example.com/a.mp3"

    def test_dict_with_arbitrary_key(self):
        """Provider-agnostic: finds tracks under any key."""
        response = {"udioTracks": [{"audioUrl": "http://example.com/b.mp3"}]}
        tracks = GenerateMusicTool._extract_tracks(response)
        assert len(tracks) == 1

    def test_direct_list(self):
        response = [{"audioUrl": "http://example.com/c.mp3"}]
        tracks = GenerateMusicTool._extract_tracks(response)
        assert len(tracks) == 1

    def test_empty_response(self):
        assert GenerateMusicTool._extract_tracks({}) == []
        assert GenerateMusicTool._extract_tracks([]) == []
        assert GenerateMusicTool._extract_tracks("unexpected") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_music_gen.py -v`
Expected: Failures — the current `music_gen.py` has a different class structure (two tools, `SubmitMusicTool`, etc.)

- [ ] **Step 3: Rewrite music_gen.py as a single tool**

Replace the entire file `odigos/tools/music_gen.py`:

```python
"""Music generation via Kie.ai API (single tool, takes lyrics directly)."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

import httpx

from odigos.tools.base import BaseTool, ToolContract, ToolResult

logger = logging.getLogger(__name__)

KIE_BASE = "https://api.kie.ai/api/v1"


class GenerateMusicTool(BaseTool):
    name = "generate_music"
    category = "create"
    contract = ToolContract(
        timeout_seconds=240,
        max_retries={"transient": 2, "input": 0, "permission": 0, "unavailable": 0, "unknown": 1},
    )
    description = (
        "Generate a music track from lyrics or a description. "
        "Returns playable audio. For lyrics review before generating, "
        "write them to a notebook first and let the user edit."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Lyrics or description of the music to generate",
            },
            "style": {
                "type": "string",
                "description": "Musical style/genre (e.g., 'indie folk, acoustic')",
            },
            "title": {
                "type": "string",
                "description": "Song title",
            },
            "instrumental": {
                "type": "boolean",
                "description": "Instrumental only, no vocals (default false)",
            },
            "vocal_gender": {
                "type": "string",
                "enum": ["", "m", "f", "male", "female"],
                "description": "Preferred vocal gender (m=male, f=female)",
            },
        },
        "required": ["prompt"],
    }

    def __init__(
        self,
        api_key: str,
        provider: str = "suno",
        task_type: str = "suno_music",
        model: str = "V5",
        max_poll_seconds: int = 180,
        output_dir: str = "",
        db=None,
    ):
        self._api_key = api_key
        self._provider = provider
        self._task_type = task_type
        self._model = model
        self._max_poll = max_poll_seconds
        from odigos.storage import FILES_DIR
        self._output_dir = output_dir or str(FILES_DIR)
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        conversation_id = params.pop("_conversation_id", None)
        prompt = (params.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(success=False, data="", error="No prompt provided")

        style = (params.get("style") or "").strip()
        title = (params.get("title") or "").strip()
        instrumental = params.get("instrumental", False)
        vocal_gender = self._map_vocal_gender(params.get("vocal_gender", ""))

        try:
            task_id = await self._create_task(
                prompt=prompt,
                style=style,
                title=title,
                instrumental=instrumental,
                vocal_gender=vocal_gender,
            )
            if not task_id:
                return ToolResult(
                    success=False, data="",
                    error="Failed to create music generation task",
                )

            tracks = await self._poll_result(task_id)
            if not tracks:
                return ToolResult(
                    success=False, data="",
                    error="Music generation timed out or failed",
                )

            artifacts = []
            for i, track in enumerate(tracks):
                audio_url = track.get("audioUrl", "")
                if not audio_url:
                    continue

                track_id = uuid.uuid4().hex
                track_title = track.get("title", f"track_{i + 1}")
                safe_title = "".join(
                    c if c.isalnum() or c in "-_ " else ""
                    for c in track_title
                ).strip().replace(" ", "_")
                filename = f"{safe_title}_{track_id[:12]}.mp3"

                filepath = await self._download_audio(audio_url, filename)
                file_size = os.path.getsize(filepath)

                if self._db:
                    now = datetime.now(timezone.utc).isoformat()
                    await self._db.execute(
                        "INSERT INTO artifacts "
                        "(id, conversation_id, filename, content_type, "
                        "file_size, file_path, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (track_id, conversation_id, filename,
                         "audio/mpeg", file_size, filepath, now),
                    )

                artifacts.append({
                    "id": track_id,
                    "filename": filename,
                    "content_type": "audio/mpeg",
                    "file_size": file_size,
                    "download_url": f"/api/artifacts/{track_id}/download",
                    "path": filepath,
                    "title": track.get("title", ""),
                    "duration": track.get("duration", 0),
                })

            if not artifacts:
                return ToolResult(
                    success=False, data="",
                    error="No audio tracks returned from generation",
                )

            summary_parts = []
            for art in artifacts:
                duration = art.get("duration", 0)
                dur_str = f" ({duration:.0f}s)" if duration else ""
                summary_parts.append(f"{art['filename']}{dur_str}")
            summary = "Generated tracks: " + ", ".join(summary_parts)

            return ToolResult(
                success=True,
                data=summary,
                side_effect={"artifacts": artifacts},
            )
        except Exception as e:
            logger.error("Music generation failed: %s", e)
            return ToolResult(success=False, data="", error=str(e))

    @staticmethod
    def _map_vocal_gender(value: str) -> str:
        """Map vocal_gender to API values: 'm' or 'f'."""
        mapping = {"male": "m", "female": "f", "m": "m", "f": "f"}
        return mapping.get(value.lower(), "") if value else ""

    @staticmethod
    def _extract_tracks(response: object) -> list[dict]:
        """Extract audio tracks from API response, provider-agnostic.

        Looks for any list of dicts containing 'audioUrl' rather than
        hardcoding provider-specific keys.
        """
        if isinstance(response, list):
            if response and isinstance(response[0], dict) and "audioUrl" in response[0]:
                return response
            return []

        if not isinstance(response, dict):
            return []

        for value in response.values():
            if (
                isinstance(value, list)
                and value
                and isinstance(value[0], dict)
                and "audioUrl" in value[0]
            ):
                return value

        return []

    async def _create_task(
        self,
        prompt: str,
        style: str = "",
        title: str = "",
        instrumental: bool = False,
        vocal_gender: str = "",
    ) -> str | None:
        """Submit music generation task to Kie.ai API."""
        custom_mode = bool(style or title)

        payload = {
            "model": self._provider,
            "taskType": self._task_type,
            "input": {
                "prompt": prompt,
                "style": style,
                "title": title,
                "model": self._model,
                "customMode": custom_mode,
                "instrumental": instrumental,
                "negativeTags": "",
                "vocalGender": vocal_gender,
            },
        }

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(
                    f"{KIE_BASE}/generate",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "Kie.ai HTTP %d: %s",
                    e.response.status_code, e.response.text[:200],
                )
                return None
            except Exception as e:
                logger.error("Kie.ai request failed: %s", e)
                return None

            if data.get("code") == 200:
                return data["data"]["taskId"]
            logger.error(
                "Kie.ai create failed (code %s): %s",
                data.get("code"), data.get("msg"),
            )
            return None

    async def _poll_result(self, task_id: str) -> list[dict] | None:
        """Poll for music generation completion with exponential backoff."""
        async with httpx.AsyncClient(timeout=30) as client:
            delay = 3.0
            elapsed = 0.0
            while elapsed < self._max_poll:
                await asyncio.sleep(delay)
                elapsed += delay

                try:
                    resp = await client.get(
                        f"{KIE_BASE}/generate/record-info",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        params={"taskId": task_id},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.HTTPStatusError as e:
                    logger.warning("Poll HTTP %d: %s", e.response.status_code, e)
                    delay = min(delay * 1.5, 15.0)
                    continue
                except Exception as e:
                    logger.warning("Poll request failed: %s", e)
                    delay = min(delay * 1.5, 15.0)
                    continue

                if data.get("code") != 200:
                    logger.debug("Poll non-200 code: %s", data.get("msg"))
                    delay = min(delay * 1.5, 15.0)
                    continue

                info = data.get("data", {})
                state = info.get("status") or info.get("state", "")

                if state == "SUCCESS":
                    return self._extract_tracks(info.get("response", {}))
                elif state in (
                    "CREATE_TASK_FAILED",
                    "GENERATE_AUDIO_FAILED",
                    "SENSITIVE_WORD_ERROR",
                    "CALLBACK_EXCEPTION",
                ):
                    error_msg = info.get("errorMessage", state)
                    logger.error("Music gen failed: %s", error_msg)
                    return None

                delay = min(delay * 1.5, 15.0)

        return None

    async def _download_audio(self, url: str, filename: str) -> str:
        """Download audio file and save to output directory."""
        os.makedirs(self._output_dir, exist_ok=True)
        filepath = os.path.join(self._output_dir, filename)

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(resp.content)

        logger.info("Downloaded audio: %s (%d bytes)", filepath, os.path.getsize(filepath))
        return filepath
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_music_gen.py -v`
Expected: All 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add odigos/tools/music_gen.py tests/test_music_gen.py
git commit -m "feat: simplify music gen to single tool — takes lyrics directly, no draft step"
```

---

### Task 4: Update Registration and Capabilities

**Files:**
- Modify: `odigos/main.py:387-410`
- Modify: `data/agent/capabilities.md:13-19,55-56`

- [ ] **Step 1: Update main.py — register notebook tool and simplify music registration**

In `odigos/main.py`, add the notebook tool registration near other productivity tools (around line 293 where workspace_search is registered):

```python
        from odigos.tools.notebook import ManageNotebookTool
        tool_registry.register(ManageNotebookTool(db=db))
```

Replace the music registration block (lines 387-410) with:

```python
    # Music generation (only if configured)
    if settings.music_generation.enabled:
        music_api_key = (
            settings.music_generation.api_key
            or settings.image_generation.api_key
        )
        if music_api_key:
            from odigos.tools.music_gen import GenerateMusicTool
            tool_registry.register(GenerateMusicTool(
                api_key=music_api_key,
                provider=settings.music_generation.provider,
                task_type=settings.music_generation.task_type,
                model=settings.music_generation.model,
                max_poll_seconds=settings.music_generation.max_poll_seconds,
                db=_db,
            ))
            logger.info(
                "Music generation tool registered (%s)",
                settings.music_generation.provider,
            )
```

- [ ] **Step 2: Update capabilities.md**

Replace lines 13-19 (the music section) with:

```markdown
When the user asks you to create a song, music, or soundtrack:
- If they provide lyrics or a clear description, call generate_music directly.
- If they want to review/edit lyrics first, create a notebook with the lyrics
  using manage_notebook, tell them to edit it, and generate when they say go.
- You can read lyrics from any notebook the user points you to via manage_notebook.
Never just write lyrics and chords -- use generate_music to produce actual audio.
```

Replace lines 55-56 (the Music tools summary) with:

```markdown
**Music:** Generate songs with generate_music (lyrics/style/title → MP3 via Suno AI). For lyrics review, write to a notebook first.

**Notebooks:** Create and write to notebooks with manage_notebook. Use for notes, recipes, lyrics, meeting summaries, or any content the user might want to review and edit.

**Audio:** Convert, trim, normalize, or concatenate audio with process_audio. Extract audio from video. All local via FFmpeg -- free and instant.
```

- [ ] **Step 3: Verify Python syntax**

Run: `python3 -c "import ast; ast.parse(open('odigos/main.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add odigos/main.py data/agent/capabilities.md
git commit -m "feat: register notebook tool, update music registration and capabilities"
```

---

### Task 5: Remove SongEditor from Frontend

**Files:**
- Modify: `dashboard/src/components/ArtifactPreview.tsx`
- Modify: `dashboard/src/layouts/AppLayout.tsx:681,685`

- [ ] **Step 1: Remove SongEditor and related code from ArtifactPreview.tsx**

Remove these sections:
1. The `type MutableRefObject` import and `ChatSocket` type import (line 1, 4)
2. The `useChatStore` import (line 5)
3. The `SongData` interface (lines 29-36)
4. The entire `SongEditor` function (lines 38-176)
5. The `isSongJson` detection (line 285) and its usage in the render block where `SongEditor` is rendered (lines 498-508)
6. The `socketRef` prop from `ArtifactPreviewProps` interface (line 188) and function signature (line 193)

The imports should go back to:
```typescript
import { useState, useEffect } from 'react'
import { useOutletContext, useSearchParams } from 'react-router-dom'
import { get, put } from '@/lib/api'
```

The `ArtifactPreviewProps` should go back to:
```typescript
interface ArtifactPreviewProps {
  artifactId: string
  onClose: () => void
}
```

The isSongJson conditional rendering block (where `SongEditor` was rendered in the preview tab) should be removed — `.song.json` files will just render as plain JSON in the code editor, which is fine since we won't be creating them anymore.

- [ ] **Step 2: Remove socketRef from ArtifactPreview in AppLayout.tsx**

Lines 681 and 685, change back to:
```typescript
<ArtifactPreview artifactId={activeArtifactId} onClose={() => setArtifactPanelOpen(false)} />
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd dashboard && npx tsc --noEmit --pretty`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/ArtifactPreview.tsx dashboard/src/layouts/AppLayout.tsx
git commit -m "fix: remove SongEditor — notebooks handle lyrics editing now"
```

---

### Task 6: Run Full Test Suite and Verify

**Files:** None (verification only)

- [ ] **Step 1: Run all tests**

Run: `pytest tests/ -x -q`
Expected: All tests pass

- [ ] **Step 2: Run TypeScript check**

Run: `cd dashboard && npx tsc --noEmit --pretty`
Expected: No errors

- [ ] **Step 3: Verify Python linting**

Run: `ruff check odigos/tools/notebook.py odigos/tools/music_gen.py odigos/tools/workspace_search.py`
Expected: No errors (or only existing pre-existing warnings)

- [ ] **Step 4: Final commit if any linting fixes**

```bash
git add -A && git commit -m "fix: lint cleanup"
```
