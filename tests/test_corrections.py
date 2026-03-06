import uuid

import pytest

from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path: str):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


class TestCorrectionsMigration:
    async def test_corrections_table_exists_and_stores_rows(self, db):
        """The corrections table is created by migration and can store/retrieve rows."""
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
        assert row["timestamp"] is not None
