import pytest

from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


class TestPeerMessageTable:
    async def test_table_exists(self, db):
        """peer_messages table exists after migration."""
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='peer_messages'"
        )
        assert row is not None

    async def test_insert_outbound(self, db):
        """Can insert an outbound peer message."""
        await db.execute(
            "INSERT INTO peer_messages "
            "(message_id, direction, peer_name, message_type, content, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("msg-001", "outbound", "sarah", "message", "hello", "sent"),
        )
        row = await db.fetch_one(
            "SELECT * FROM peer_messages WHERE message_id = ?", ("msg-001",)
        )
        assert row["peer_name"] == "sarah"
        assert row["status"] == "sent"

    async def test_insert_inbound(self, db):
        """Can insert an inbound peer message."""
        await db.execute(
            "INSERT INTO peer_messages "
            "(message_id, direction, peer_name, message_type, content, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("msg-002", "inbound", "bob", "help_request", "need help", "received"),
        )
        row = await db.fetch_one(
            "SELECT * FROM peer_messages WHERE message_id = ?", ("msg-002",)
        )
        assert row["direction"] == "inbound"

    async def test_duplicate_message_id_rejected(self, db):
        """Duplicate message_id is rejected (UNIQUE constraint)."""
        await db.execute(
            "INSERT INTO peer_messages "
            "(message_id, direction, peer_name, message_type, content, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("msg-dup", "outbound", "sarah", "message", "first", "sent"),
        )
        with pytest.raises(Exception):
            await db.execute(
                "INSERT INTO peer_messages "
                "(message_id, direction, peer_name, message_type, content, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("msg-dup", "inbound", "bob", "message", "duplicate", "received"),
            )

    async def test_status_update(self, db):
        """Can update delivery status."""
        await db.execute(
            "INSERT INTO peer_messages "
            "(message_id, direction, peer_name, message_type, content, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("msg-003", "outbound", "sarah", "message", "hello", "queued"),
        )
        await db.execute(
            "UPDATE peer_messages SET status = ?, delivered_at = datetime('now') "
            "WHERE message_id = ?",
            ("delivered", "msg-003"),
        )
        row = await db.fetch_one(
            "SELECT * FROM peer_messages WHERE message_id = ?", ("msg-003",)
        )
        assert row["status"] == "delivered"
        assert row["delivered_at"] is not None
