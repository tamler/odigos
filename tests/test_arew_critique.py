"""Tests for AREW-inspired AS/BT critique signals."""

import pytest

from odigos.core.evaluator import compute_as_critique, compute_bt_critique
from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


class TestActionSelectionCritique:
    async def test_document_query_without_tools_is_negative(self, db):
        score = await compute_as_critique(db, "conv-1", "document_query", [])
        assert score == -1

    async def test_document_query_with_active_tools_is_positive(self, db):
        score = await compute_as_critique(db, "conv-1", "document_query", ["run_code"])
        assert score == 1

    async def test_complex_query_without_tools_is_negative(self, db):
        score = await compute_as_critique(db, "conv-1", "complex", [])
        assert score == -1

    async def test_standard_query_with_search_is_positive(self, db):
        score = await compute_as_critique(db, "conv-1", "standard", ["read_page"])
        assert score == 1

    async def test_simple_query_without_tools_is_neutral(self, db):
        score = await compute_as_critique(db, "conv-1", "simple", [])
        assert score == 0

    async def test_standard_query_without_tools_is_neutral(self, db):
        score = await compute_as_critique(db, "conv-1", "standard", [])
        assert score == 0


class TestBeliefTrackingCritique:
    async def test_no_tools_is_neutral(self, db):
        score = await compute_bt_critique(db, "conv-1", "Hello!", [])
        assert score == 0

    async def test_tool_results_referenced_is_positive(self, db):
        # Insert a tool result message
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-bt", "web"),
        )
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, timestamp) "
            "VALUES (?, ?, 'tool', ?, datetime('now'))",
            ("tool-1", "conv-bt",
             "The document says the quarterly revenue was $4.2 million with expenses of $3.1 million"),
        )

        # Assistant response references the tool content
        response = "Based on the data, quarterly revenue was $4.2 million and expenses were $3.1 million, giving a profit of $1.1 million."
        score = await compute_bt_critique(db, "conv-bt", response, ["process_document"])
        assert score == 1

    async def test_tool_results_ignored_is_negative(self, db):
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-bt2", "web"),
        )
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, timestamp) "
            "VALUES (?, ?, 'tool', ?, datetime('now'))",
            ("tool-2", "conv-bt2",
             "The Springfield facility reported production output of 15,000 units with a defect rate of 2.3%"),
        )

        # Assistant response completely ignores tool content
        response = "I think the answer is probably around 10,000 units. Let me know if you need anything else!"
        score = await compute_bt_critique(db, "conv-bt2", response, ["process_document"])
        assert score == -1

    async def test_no_tool_messages_is_neutral(self, db):
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-bt3", "web"),
        )
        score = await compute_bt_critique(db, "conv-bt3", "Some response", ["read_page"])
        assert score == 0
