"""Tests for prompt consolidation and skill verification schema."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


class TestSchema:
    async def test_skill_verifications_table_exists(self, db):
        row_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO skill_verifications (id, skill_name, overall_score, model_used) "
            "VALUES (?, ?, ?, ?)",
            (row_id, "legal-draft", 0.85, "test/model"),
        )
        row = await db.fetch_one(
            "SELECT * FROM skill_verifications WHERE id = ?", (row_id,)
        )
        assert row is not None
        assert row["skill_name"] == "legal-draft"
        assert row["overall_score"] == 0.85

    async def test_consolidation_log_table_exists(self, db):
        row_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO consolidation_log (id, axis, corrections_processed, rules_before, rules_after) "
            "VALUES (?, ?, ?, ?, ?)",
            (row_id, "operational", 5, 3, 6),
        )
        row = await db.fetch_one(
            "SELECT * FROM consolidation_log WHERE id = ?", (row_id,)
        )
        assert row is not None
        assert row["axis"] == "operational"
        assert row["corrections_processed"] == 5

    async def test_corrections_consolidated_at_column(self, db):
        conv_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            (conv_id, "test"),
        )
        corr_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO corrections (id, conversation_id, correction, category) "
            "VALUES (?, ?, ?, ?)",
            (corr_id, conv_id, "Fix this", "accuracy"),
        )
        row = await db.fetch_one(
            "SELECT consolidated_at FROM corrections WHERE id = ?", (corr_id,)
        )
        assert row is not None
        assert row["consolidated_at"] is None
