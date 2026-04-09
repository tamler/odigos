"""Integration test: store -> recall -> evolution full pipeline."""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.db import Database
from odigos.memory.store import MemoryStore
from odigos.memory.recall import MemoryRecall
from odigos.memory.evolution import MemoryEvolution
from odigos.providers.base import LLMResponse


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content, model="test/model",
        tokens_in=50, tokens_out=100, cost_usd=0.001,
    )


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


class TestFullPipeline:
    async def test_store_recall_cycle(self, db):
        """Store a memory, then recall it by type."""
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response(json.dumps({
            "memory_type": "preference",
            "keywords": ["dark mode", "UI"],
            "tags": ["user-profile"],
            "context_description": "User prefers dark mode for the UI.",
        })))

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.5] * 768)
        mock_embedder.embed_query = AsyncMock(return_value=[0.5] * 768)

        store = MemoryStore(db=db, llm_client=mock_llm, embedder=mock_embedder)
        recall = MemoryRecall(db=db, embedder=mock_embedder)

        # Store
        record = await store.store(
            content="I prefer dark mode",
            source_type="conversation",
            source_id="conv-1",
        )
        assert record.memory_type == "preference"

        # Recall by type filter (uses FTS only since vec may be unavailable)
        results = await recall.search("dark mode preference", memory_types=["preference"])
        assert len(results) >= 1
        assert any("dark mode" in r.content.lower() for r in results)

        # Format
        output = recall.format_grouped(results)
        assert "### Preferences" in output

    async def test_evolution_updates_stale_memory(self, db):
        """Store a fact, queue evolution, verify it updates."""
        classify_response = json.dumps({
            "memory_type": "fact",
            "keywords": ["timezone", "EST"],
            "tags": ["user-profile"],
            "context_description": "User timezone is EST.",
        })
        evolve_response = json.dumps({
            "action": "UPDATE",
            "context_description": "User timezone is PST (moved from EST).",
            "keywords": ["timezone", "PST"],
            "tags": ["user-profile"],
        })

        call_count = 0

        async def mock_complete(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return _make_llm_response(classify_response)
            return _make_llm_response(evolve_response)

        mock_llm = AsyncMock()
        mock_llm.complete = mock_complete

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.5] * 768)

        store = MemoryStore(db=db, llm_client=mock_llm, embedder=mock_embedder)
        record = await store.store("My timezone is EST", "conversation", "conv-1")

        # Queue evolution
        await db.execute(
            "INSERT INTO evolution_queue (existing_memory_id, new_content, reason) "
            "VALUES (?, ?, ?)",
            (record.id, "I moved to PST", "richer_content"),
        )

        # Run evolution
        evo = MemoryEvolution(db=db, llm_client=mock_llm, prompts_dir="data/prompts")
        stats = await evo.run_cycle()
        assert stats["processed"] == 1

        # Verify update
        row = await db.fetch_one("SELECT * FROM memories WHERE id = ?", (record.id,))
        assert "PST" in row["context_description"]
