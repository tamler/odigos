"""Tests for generate_card and import_card tools."""
import json

import pytest
import pytest_asyncio

from odigos.core.cards import CardManager
from odigos.db import Database
from odigos.tools.card_tools import GenerateCardTool, ImportCardTool


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def manager(db):
    return CardManager(db=db, agent_name="Odigos", host="100.64.0.1", ws_port=8001)


@pytest.mark.asyncio
async def test_generate_card_tool(manager):
    tool = GenerateCardTool(card_manager=manager)
    result = await tool.execute({"type": "connect"})
    assert result.success is True
    data = json.loads(result.data)
    assert data["card"]["type"] == "connect"
    assert "yaml" in data
    assert "compact" in data


@pytest.mark.asyncio
async def test_generate_card_tool_subscribe(manager):
    tool = GenerateCardTool(card_manager=manager)
    result = await tool.execute({"type": "subscribe"})
    assert result.success is True
    data = json.loads(result.data)
    assert data["card"]["type"] == "subscribe"
    assert data["card"]["feed_url"] is not None


@pytest.mark.asyncio
async def test_generate_card_tool_missing_type(manager):
    tool = GenerateCardTool(card_manager=manager)
    result = await tool.execute({})
    assert result.success is False


@pytest.mark.asyncio
async def test_import_card_tool(manager, db):
    # Generate a card first
    card = await manager.generate_card(card_type="connect")
    compact = manager.card_to_compact(card)

    # Import on a different "agent"
    importer_mgr = CardManager(db=db, agent_name="Archie", host="100.64.0.2", ws_port=8001)
    tool = ImportCardTool(card_manager=importer_mgr)
    result = await tool.execute({"card_data": compact})
    assert result.success is True
    data = json.loads(result.data)
    assert data["status"] == "accepted"


@pytest.mark.asyncio
async def test_import_card_tool_bad_data(manager):
    tool = ImportCardTool(card_manager=manager)
    result = await tool.execute({"card_data": "garbage"})
    assert result.success is False
