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
