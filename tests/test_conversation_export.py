import uuid
import pytest
from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


async def _create_conversation(db, conv_id, title="Test Chat"):
    await db.execute(
        "INSERT INTO conversations (id, channel, title) VALUES (?, ?, ?)",
        (conv_id, "test", title),
    )
    for i in range(4):
        role = "user" if i % 2 == 0 else "assistant"
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), conv_id, role, f"Message {i}"),
        )


class TestConversationExport:
    async def test_export_markdown(self, db):
        from odigos.api.conversations import _export_markdown
        conv_id = "conv-export-1"
        await _create_conversation(db, conv_id, "My Chat")
        result = await _export_markdown(db, conv_id)
        assert "# My Chat" in result
        assert "Message 0" in result
        assert "Message 3" in result

    async def test_export_json(self, db):
        import json
        from odigos.api.conversations import _export_json
        conv_id = "conv-export-2"
        await _create_conversation(db, conv_id)
        result = await _export_json(db, conv_id)
        data = json.loads(result)
        assert "messages" in data
        assert len(data["messages"]) == 4

    async def test_export_nonexistent(self, db):
        from odigos.api.conversations import _export_markdown
        result = await _export_markdown(db, "nope")
        assert result is None
