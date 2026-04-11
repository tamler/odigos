"""Tests for fact contradiction detection."""
import pytest
from odigos.db import Database
from odigos.memory.fact_checker import check_and_store_fact, find_similar_facts


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    await d.initialize()
    return d


class TestFactChecker:
    @pytest.mark.asyncio
    async def test_store_new_fact(self, db):
        """First-time fact should be stored normally."""
        result = await check_and_store_fact(db, "User lives in Manila")
        assert result["action"] == "stored"
        assert result["fact_id"]

        rows = await db.fetch_all(
            "SELECT content FROM memories WHERE memory_type = 'fact' AND status = 'active'"
        )
        assert len(rows) == 1
        assert rows[0]["content"] == "User lives in Manila"

    @pytest.mark.asyncio
    async def test_exact_duplicate(self, db):
        """Exact same fact should be detected as duplicate."""
        await check_and_store_fact(db, "User likes coffee")
        result = await check_and_store_fact(db, "User likes coffee")
        assert result["action"] == "duplicate"

        rows = await db.fetch_all(
            "SELECT content FROM memories WHERE memory_type = 'fact' AND status = 'active'"
        )
        assert len(rows) == 1  # Still just one fact

    @pytest.mark.asyncio
    async def test_store_without_provider(self, db):
        """Without an LLM provider, similar facts are stored without contradiction check."""
        await check_and_store_fact(db, "User works at Google")
        result = await check_and_store_fact(db, "User works at Meta")
        # Without LLM, can't detect contradiction, so stores as new
        assert result["action"] == "stored"

        rows = await db.fetch_all(
            "SELECT content FROM memories WHERE memory_type = 'fact' AND status = 'active'"
        )
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_find_similar_keyword_fallback(self, db):
        """Keyword-based fallback should find similar facts."""
        await check_and_store_fact(db, "User lives in Manila Philippines")
        similar = await find_similar_facts(db, None, "User lives in Tokyo Japan")
        # Both have "User lives in" — should find some overlap
        assert len(similar) >= 1
        assert similar[0]["fact"] == "User lives in Manila Philippines"

    @pytest.mark.asyncio
    async def test_category_preserved(self, db):
        """Category should be stored correctly."""
        result = await check_and_store_fact(db, "Prefers dark mode", category="preference")
        row = await db.fetch_one(
            "SELECT source_type FROM memories WHERE id = ?", (result["fact_id"],)
        )
        assert row["source_type"] == "preference"
