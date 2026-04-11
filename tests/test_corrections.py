import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from odigos.core.reflector import Reflector
from odigos.db import Database
from odigos.memory.corrections import CorrectionsManager
from odigos.providers.base import LLMResponse


@pytest.fixture
async def db(tmp_db_path: str):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


async def _seed_conversation(db: Database, conversation_id: str) -> None:
    """Insert a conversation row so the FK on messages is satisfied."""
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        (conversation_id, "test"),
    )


class TestCorrectionsMigration:
    async def test_corrections_table_exists_and_stores_rows(self, db):
        """The corrections table is created by migration and can store/retrieve rows."""
        await _seed_conversation(db, "conv-1")
        correction_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO corrections (id, conversation_id, original_response, correction, context, category) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (correction_id, "conv-1", "I said X", "Actually Y", "some context", "accuracy"),
        )
        row = await db.fetch_one("SELECT * FROM corrections WHERE id = ?", (correction_id,))
        assert row is not None
        assert row["conversation_id"] == "conv-1"
        assert row["original_response"] == "I said X"
        assert row["correction"] == "Actually Y"
        assert row["context"] == "some context"
        assert row["category"] == "accuracy"
        assert row["applied_count"] == 0
        assert row["created_at"] is not None


class TestCorrectionsManager:
    async def test_store_inserts_row(self, db):
        """store() inserts a DB row."""
        await _seed_conversation(db, "conv-1")
        manager = CorrectionsManager(db)

        correction_id = await manager.store(
            conversation_id="conv-1",
            original_response="I said X",
            correction="Actually Y",
            context="some context",
            category="accuracy",
        )

        row = await db.fetch_one("SELECT * FROM corrections WHERE id = ?", (correction_id,))
        assert row is not None
        assert row["conversation_id"] == "conv-1"
        assert row["original_response"] == "I said X"
        assert row["correction"] == "Actually Y"

    async def test_relevant_returns_formatted_corrections(self, db):
        """relevant() returns formatted output when unconsolidated corrections exist."""
        await _seed_conversation(db, "conv-1")
        manager = CorrectionsManager(db)

        await manager.store(
            conversation_id="conv-1",
            original_response="I said X",
            correction="Actually Y",
            context="some context",
            category="accuracy",
        )

        result = await manager.relevant("scheduling query")

        assert "## Recent corrections" in result
        assert "Actually Y" in result

    async def test_relevant_returns_empty_when_no_corrections(self, db):
        """relevant() returns empty string when no corrections exist."""
        manager = CorrectionsManager(db)
        result = await manager.relevant("some query")
        assert result == ""


class TestReflectorCorrectionParsing:
    def _make_response(self, content: str) -> LLMResponse:
        return LLMResponse(
            content=content,
            model="test/model",
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.0,
        )

    async def test_correction_block_parsed_and_stored(self, db):
        """Reflector parses correction block and calls corrections_manager.store()."""
        await _seed_conversation(db, "conv-1")

        correction_data = {
            "original": "I said meetings are at 9am",
            "correction": "Meetings are at 10am",
            "category": "accuracy",
            "context": "weekly team meetings",
        }
        content = f"Sure, I'll update that.\n<!--correction\n{json.dumps(correction_data)}\n-->"

        mock_corrections = MagicMock()
        mock_corrections.store = AsyncMock(return_value="corr-123")
        reflector = Reflector(db, corrections_manager=mock_corrections)

        await reflector.reflect("conv-1", self._make_response(content))

        mock_corrections.store.assert_called_once_with(
            conversation_id="conv-1",
            original_response="I said meetings are at 9am",
            correction="Meetings are at 10am",
            context="weekly team meetings",
            category="accuracy",
        )

    async def test_correction_block_stripped_from_stored_content(self, db):
        """The correction block is removed from the message stored in the DB."""
        await _seed_conversation(db, "conv-1")

        correction_data = {
            "original": "wrong thing",
            "correction": "right thing",
            "category": "accuracy",
            "context": "some context",
        }
        content = f"Here is my response.\n<!--correction\n{json.dumps(correction_data)}\n-->"

        mock_corrections = MagicMock()
        mock_corrections.store = AsyncMock(return_value="corr-123")
        reflector = Reflector(db, corrections_manager=mock_corrections)

        await reflector.reflect("conv-1", self._make_response(content))

        row = await db.fetch_one(
            "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
            ("conv-1",),
        )
        assert row is not None
        assert "<!--correction" not in row["content"]
        assert "Here is my response." in row["content"]

    async def test_no_correction_block_no_store_call(self, db):
        """Normal response without correction block does not call store()."""
        await _seed_conversation(db, "conv-1")

        mock_corrections = MagicMock()
        mock_corrections.store = AsyncMock()
        reflector = Reflector(db, corrections_manager=mock_corrections)

        await reflector.reflect("conv-1", self._make_response("Just a normal response."))

        mock_corrections.store.assert_not_called()

    async def test_malformed_correction_json_handled_gracefully(self, db):
        """Bad JSON in correction block does not crash; message is still stored."""
        await _seed_conversation(db, "conv-1")

        content = "Here is my response.\n<!--correction\n{bad json!!!\n-->"

        mock_corrections = MagicMock()
        mock_corrections.store = AsyncMock()
        reflector = Reflector(db, corrections_manager=mock_corrections)

        await reflector.reflect("conv-1", self._make_response(content))

        mock_corrections.store.assert_not_called()

        row = await db.fetch_one(
            "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
            ("conv-1",),
        )
        assert row is not None
        assert "Here is my response." in row["content"]


class TestCorrectionsEndToEnd:
    async def test_correction_stored_and_retrieved_in_context(self, db):
        """Full flow: store a correction, then verify it appears in relevant() output."""
        await _seed_conversation(db, "conv-1")
        manager = CorrectionsManager(db)

        await manager.store(
            conversation_id="conv-1",
            original_response="I scheduled for 8am",
            correction="Never schedule before 10am",
            context="morning scheduling",
            category="preference",
        )

        result = await manager.relevant("schedule meeting at 9am")

        assert "## Recent corrections" in result
        assert "Never schedule before 10am" in result
        assert "preference" in result
        assert "morning scheduling" in result
