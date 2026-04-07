import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from odigos.core.reflector import Reflector
from odigos.db import Database
from odigos.providers.base import LLMResponse


@pytest.fixture
async def db(tmp_db_path: str):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


def _make_message_bus(db: Database):
    """Create a real-enough MessageBus stub that writes to the DB."""
    from odigos.channels.base import ChannelRegistry
    from odigos.core.message_bus import MessageBus

    registry = ChannelRegistry()
    return MessageBus(db=db, channel_registry=registry)


async def _seed_conversation(db: Database, conversation_id: str) -> None:
    """Insert a conversation row so the FK on messages is satisfied."""
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        (conversation_id, "test"),
    )


class TestAsyncCostBackfill:
    async def test_spawns_cost_task_when_generation_id_present(self, db):
        await _seed_conversation(db, "conv-1")
        mock_fetch = AsyncMock(return_value=0.00042)
        message_bus = _make_message_bus(db)
        reflector = Reflector(db, cost_fetcher=mock_fetch, message_bus=message_bus)
        response = LLMResponse(
            content="Hello",
            model="test/model",
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.0,
            generation_id="gen-abc-123",
        )
        await reflector.reflect("conv-1", response)
        await asyncio.sleep(0.1)
        mock_fetch.assert_called_once_with("gen-abc-123")
        row = await db.fetch_one(
            "SELECT cost_usd FROM messages WHERE conversation_id = ? AND role = 'assistant'",
            ("conv-1",),
        )
        assert row["cost_usd"] == pytest.approx(0.00042)

    async def test_no_task_spawned_when_no_generation_id(self, db):
        await _seed_conversation(db, "conv-1")
        mock_fetch = AsyncMock()
        message_bus = _make_message_bus(db)
        reflector = Reflector(db, cost_fetcher=mock_fetch, message_bus=message_bus)
        response = LLMResponse(
            content="Hello",
            model="test/model",
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.0,
            generation_id=None,
        )
        await reflector.reflect("conv-1", response)
        await asyncio.sleep(0.1)
        mock_fetch.assert_not_called()

    async def test_cost_fetch_failure_leaves_original_cost(self, db):
        await _seed_conversation(db, "conv-1")
        mock_fetch = AsyncMock(return_value=None)
        message_bus = _make_message_bus(db)
        reflector = Reflector(db, cost_fetcher=mock_fetch, message_bus=message_bus)
        response = LLMResponse(
            content="Hello",
            model="test/model",
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.001,
            generation_id="gen-xyz",
        )
        await reflector.reflect("conv-1", response)
        await asyncio.sleep(0.1)
        row = await db.fetch_one(
            "SELECT cost_usd FROM messages WHERE conversation_id = ? AND role = 'assistant'",
            ("conv-1",),
        )
        assert row["cost_usd"] == pytest.approx(0.001)
