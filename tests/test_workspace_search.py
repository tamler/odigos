"""Tests for workspace search tool."""
import pytest
from odigos.db import Database
from odigos.tools.workspace_search import WorkspaceSearchTool


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    await d.initialize()
    return d


class TestWorkspaceSearch:
    @pytest.mark.asyncio
    async def test_find_notebook_by_name(self, db):
        await db.execute(
            "INSERT INTO notebooks (id, title, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("nb-1", "Daily Journal"),
        )
        tool = WorkspaceSearchTool(db=db)
        result = await tool.execute({"query": "journal"})
        assert result.success
        assert "Daily Journal" in result.data
        assert "/notebooks/nb-1" in result.data

    @pytest.mark.asyncio
    async def test_find_board_by_name(self, db):
        await db.execute(
            "INSERT INTO kanban_boards (id, title, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("b-1", "Project Roadmap"),
        )
        tool = WorkspaceSearchTool(db=db)
        result = await tool.execute({"query": "roadmap"})
        assert result.success
        assert "Project Roadmap" in result.data
        assert "/kanban/b-1" in result.data

    @pytest.mark.asyncio
    async def test_no_results(self, db):
        tool = WorkspaceSearchTool(db=db)
        result = await tool.execute({"query": "nonexistent"})
        assert result.success
        assert "No notebooks or boards found" in result.data

    @pytest.mark.asyncio
    async def test_filter_by_type(self, db):
        await db.execute(
            "INSERT INTO notebooks (id, title, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("nb-2", "My Notes"),
        )
        await db.execute(
            "INSERT INTO kanban_boards (id, title, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("b-2", "My Board"),
        )
        tool = WorkspaceSearchTool(db=db)

        # Search only notebooks
        result = await tool.execute({"query": "my", "type": "notebook"})
        assert "My Notes" in result.data
        assert "My Board" not in result.data

        # Search only boards
        result = await tool.execute({"query": "my", "type": "board"})
        assert "My Board" in result.data
        assert "My Notes" not in result.data

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
