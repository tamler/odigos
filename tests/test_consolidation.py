"""Tests for prompt consolidation and skill verification schema."""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.db import Database
from odigos.core.consolidation import ConsolidationOp, PromptConsolidator
from odigos.providers.base import LLMResponse


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content, model="test/model",
        tokens_in=100, tokens_out=200, cost_usd=0.001,
    )


async def _seed_corrections(db, count: int = 5) -> list[str]:
    """Insert test corrections, return their IDs."""
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        (conv_id, "test"),
    )
    ids = []
    categories = ["accuracy", "tone", "preference", "tool_choice", "behavior"]
    for i in range(count):
        cid = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO corrections "
            "(id, conversation_id, original_response, correction, context, category) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cid, conv_id, f"Original {i}", f"Correction {i}",
             f"Context {i}", categories[i % len(categories)]),
        )
        ids.append(cid)
    return ids


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


class TestConsolidation:
    async def test_skips_when_fewer_than_min_batch(self, db):
        """consolidate() skips when fewer than 3 unconsolidated corrections."""
        await _seed_corrections(db, count=2)
        mock_llm = AsyncMock()
        consolidator = PromptConsolidator(
            db=db, llm_client=mock_llm,
            prompts_dir="data/prompts", sections_dir="data/agent",
        )
        stats = await consolidator.consolidate()
        assert stats["corrections_processed"] == 0
        mock_llm.complete.assert_not_called()

    async def test_processes_batch_and_marks_consolidated(self, db):
        """consolidate() processes corrections and marks them consolidated."""
        ids = await _seed_corrections(db, count=5)
        merge_response = json.dumps({
            "classifications": [
                {"correction_id": ids[i], "axis": ["operational", "behavioral", "behavioral", "operational", "knowledge"][i]}
                for i in range(5)
            ],
            "operations": [
                {"op": "ADD", "rule": "Rule from correction 0", "source_correction_id": ids[0]},
                {"op": "ADD", "rule": "Rule from correction 1", "source_correction_id": ids[1]},
            ],
            "updated_section": "- Rule from correction 0\n- Rule from correction 1",
        })
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response(merge_response))
        consolidator = PromptConsolidator(
            db=db, llm_client=mock_llm,
            prompts_dir="data/prompts", sections_dir="data/agent",
        )
        stats = await consolidator.consolidate()
        assert stats["corrections_processed"] == 5
        rows = await db.fetch_all(
            "SELECT consolidated_at FROM corrections WHERE consolidated_at IS NOT NULL"
        )
        assert len(rows) == 5

    async def test_knowledge_corrections_marked_skipped(self, db):
        """Knowledge corrections get consolidated_at='skipped'."""
        ids = await _seed_corrections(db, count=3)
        merge_response = json.dumps({
            "classifications": [
                {"correction_id": ids[0], "axis": "knowledge"},
                {"correction_id": ids[1], "axis": "operational"},
                {"correction_id": ids[2], "axis": "behavioral"},
            ],
            "operations": [
                {"op": "SKIP", "source_correction_id": ids[0], "reason": "Factual"},
                {"op": "ADD", "rule": "Operational rule", "source_correction_id": ids[1]},
                {"op": "ADD", "rule": "Behavioral rule", "source_correction_id": ids[2]},
            ],
            "updated_section": "- Operational rule",
        })
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response(merge_response))
        consolidator = PromptConsolidator(
            db=db, llm_client=mock_llm,
            prompts_dir="data/prompts", sections_dir="data/agent",
        )
        await consolidator.consolidate()
        row = await db.fetch_one(
            "SELECT consolidated_at FROM corrections WHERE id = ?", (ids[0],)
        )
        assert row["consolidated_at"] == "skipped"

    async def test_consolidation_log_written(self, db):
        """consolidate() writes an entry to consolidation_log."""
        await _seed_corrections(db, count=3)
        merge_response = json.dumps({
            "classifications": [{"correction_id": "x", "axis": "operational"}] * 3,
            "operations": [{"op": "ADD", "rule": "Test rule", "source_correction_id": "x"}],
            "updated_section": "- Test rule",
        })
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response(merge_response))
        consolidator = PromptConsolidator(
            db=db, llm_client=mock_llm,
            prompts_dir="data/prompts", sections_dir="data/agent",
        )
        await consolidator.consolidate()
        rows = await db.fetch_all("SELECT * FROM consolidation_log")
        assert len(rows) >= 1
