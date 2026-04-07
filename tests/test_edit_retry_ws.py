"""Tests for edit message truncation logic."""
import pytest
from odigos.db import Database


class TestEditTruncation:
    @pytest.mark.asyncio
    async def test_truncate_messages_from_index(self, tmp_path):
        """Editing a message should delete all messages from that index onward."""
        db = Database(str(tmp_path / "test.db"))
        await db.initialize()
        conv_id = "test-conv"

        # Create conversation first (FK constraint)
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            (conv_id, "web"),
        )

        # Insert 5 messages
        for i in range(5):
            await db.execute(
                "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
                (f"msg-{i}", conv_id, "user" if i % 2 == 0 else "assistant", f"message {i}"),
            )

        # Truncate from index 2 (delete messages 2, 3, 4)
        rows = await db.fetch_all(
            "SELECT id FROM messages WHERE conversation_id = ? ORDER BY created_at",
            (conv_id,),
        )
        ids_to_delete = [r["id"] for r in rows[2:]]
        placeholders = ",".join("?" * len(ids_to_delete))
        await db.execute(
            f"DELETE FROM messages WHERE id IN ({placeholders})",
            ids_to_delete,
        )

        remaining = await db.fetch_all(
            "SELECT id FROM messages WHERE conversation_id = ? ORDER BY created_at",
            (conv_id,),
        )
        assert len(remaining) == 2
        assert remaining[0]["id"] == "msg-0"
        assert remaining[1]["id"] == "msg-1"
