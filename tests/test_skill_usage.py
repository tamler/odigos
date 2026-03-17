import pytest
from odigos.db import Database


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    await d.initialize()
    return d


@pytest.mark.asyncio
async def test_skill_usage_insert(db):
    import uuid
    await db.execute(
        "INSERT INTO skill_usage (id, conversation_id, skill_name, skill_type, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), "conv-1", "fetch_price", "code", "2026-03-17T00:00:00Z"),
    )
    row = await db.fetch_one("SELECT * FROM skill_usage WHERE skill_name = 'fetch_price'")
    assert row is not None
    assert row["skill_type"] == "code"


@pytest.mark.asyncio
async def test_skill_usage_score_update(db):
    import uuid
    sid = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO skill_usage (id, conversation_id, skill_name, skill_type, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (sid, "conv-2", "summarizer", "text", "2026-03-17T00:00:00Z"),
    )
    await db.execute(
        "UPDATE skill_usage SET evaluation_score = 0.9 WHERE id = ?", (sid,),
    )
    row = await db.fetch_one("SELECT evaluation_score FROM skill_usage WHERE id = ?", (sid,))
    assert row["evaluation_score"] == 0.9
