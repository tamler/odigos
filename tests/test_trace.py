import json
import uuid

import pytest

from odigos.core.trace import Tracer
from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path: str):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


async def _seed_conversation(db: Database, conversation_id: str) -> None:
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        (conversation_id, "test"),
    )


class TestTracer:
    async def test_emit_inserts_row(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        trace_id = await tracer.emit("step_start", "conv-1", {"message": "hello"})

        row = await db.fetch_one("SELECT * FROM traces WHERE id = ?", (trace_id,))
        assert row is not None
        assert row["event_type"] == "step_start"
        assert row["conversation_id"] == "conv-1"
        data = json.loads(row["data_json"])
        assert data["message"] == "hello"

    async def test_emit_returns_id(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        trace_id = await tracer.emit("response", "conv-1", {})
        assert isinstance(trace_id, str)
        assert len(trace_id) > 0

    async def test_emit_without_conversation(self, db):
        tracer = Tracer(db)
        trace_id = await tracer.emit("heartbeat_tick", None, {"todos": 3})

        row = await db.fetch_one("SELECT * FROM traces WHERE id = ?", (trace_id,))
        assert row is not None
        assert row["conversation_id"] is None
        assert row["event_type"] == "heartbeat_tick"

    async def test_emit_serializes_complex_data(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        data = {"tools": ["search", "scrape"], "nested": {"key": "value"}, "count": 42}
        trace_id = await tracer.emit("tool_call", "conv-1", data)

        row = await db.fetch_one("SELECT * FROM traces WHERE id = ?", (trace_id,))
        parsed = json.loads(row["data_json"])
        assert parsed["tools"] == ["search", "scrape"]
        assert parsed["nested"]["key"] == "value"
        assert parsed["count"] == 42

    async def test_emit_with_empty_data(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        trace_id = await tracer.emit("warning", "conv-1", {})

        row = await db.fetch_one("SELECT * FROM traces WHERE id = ?", (trace_id,))
        assert row is not None
        assert json.loads(row["data_json"]) == {}

    async def test_emit_has_timestamp(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        trace_id = await tracer.emit("response", "conv-1", {})

        row = await db.fetch_one("SELECT * FROM traces WHERE id = ?", (trace_id,))
        assert row["timestamp"] is not None

    async def test_action_log_table_dropped(self, db):
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='action_log'"
        )
        assert row is None

    async def test_traces_table_exists(self, db):
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='traces'"
        )
        assert row is not None
