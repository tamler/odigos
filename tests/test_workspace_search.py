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
