import pytest

from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


async def test_profile_table_exists(db: Database):
    """Migration creates the user_profile table with a default row."""
    row = await db.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='user_profile'"
    )
    assert row is not None

    # Default 'owner' row should exist
    profile = await db.fetch_one("SELECT * FROM user_profile WHERE id = 'owner'")
    assert profile is not None
    assert profile["id"] == "owner"
    assert profile["conversation_count"] == 0


async def test_profile_fields(db: Database):
    """All expected columns exist on the user_profile table."""
    profile = await db.fetch_one("SELECT * FROM user_profile WHERE id = 'owner'")
    assert profile is not None
    expected_columns = [
        "id",
        "communication_style",
        "expertise_areas",
        "preferences",
        "recurring_topics",
        "correction_patterns",
        "summary",
        "last_analyzed_at",
        "conversation_count",
    ]
    for col in expected_columns:
        assert col in profile, f"Missing column: {col}"


async def test_empty_profile_no_injection(db: Database):
    """When summary is empty, user_profile string should be empty."""
    profile_row = await db.fetch_one(
        "SELECT communication_style, expertise_areas, preferences, "
        "recurring_topics, summary FROM user_profile WHERE id = 'owner'"
    )
    assert profile_row is not None
    # summary is empty string, so no profile should be built
    assert profile_row["summary"] == ""

    # Simulate the context assembly logic
    user_profile = ""
    if profile_row and profile_row["summary"]:
        lines = ["## About your user"]
        if profile_row["summary"]:
            lines.append(profile_row["summary"])
        user_profile = "\n".join(lines)

    assert user_profile == ""


async def test_profile_update_and_read(db: Database):
    """Profile can be updated and read back correctly."""
    await db.execute(
        "UPDATE user_profile SET "
        "communication_style = ?, expertise_areas = ?, preferences = ?, "
        "recurring_topics = ?, correction_patterns = ?, summary = ?, "
        "conversation_count = ? WHERE id = 'owner'",
        (
            "Direct and concise",
            "Python, distributed systems",
            "Prefers code examples over explanations",
            "Testing, deployment, API design",
            "Often asks for less verbose output",
            "A senior engineer who prefers direct answers with code.",
            10,
        ),
    )
    profile = await db.fetch_one("SELECT * FROM user_profile WHERE id = 'owner'")
    assert profile["summary"] == "A senior engineer who prefers direct answers with code."
    assert profile["communication_style"] == "Direct and concise"
    assert profile["conversation_count"] == 10
