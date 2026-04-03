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
