"""Tests for publish_to_feed tool."""
import json

import pytest
import pytest_asyncio

from odigos.db import Database
from odigos.tools.feed_publish import PublishToFeedTool


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_publish_entry(db):
    tool = PublishToFeedTool(db=db, feed_base_url="http://localhost:8000")
    result = await tool.execute({"title": "Test Alert", "content": "Server is down"})
    assert result.success is True
    data = json.loads(result.data)
    assert data["title"] == "Test Alert"
    assert "id" in data
    assert data["feed_url"] == "http://localhost:8000/feed.xml"

    row = await db.fetch_one("SELECT * FROM feed_entries WHERE id = ?", (data["id"],))
    assert row is not None
    assert row["title"] == "Test Alert"


@pytest.mark.asyncio
async def test_publish_with_category(db):
    tool = PublishToFeedTool(db=db, feed_base_url="http://localhost:8000")
    result = await tool.execute({"title": "Research", "content": "Findings", "category": "research"})
    assert result.success is True
    data = json.loads(result.data)

    row = await db.fetch_one("SELECT * FROM feed_entries WHERE id = ?", (data["id"],))
    assert row["category"] == "research"


@pytest.mark.asyncio
async def test_publish_missing_title(db):
    tool = PublishToFeedTool(db=db, feed_base_url="http://localhost:8000")
    result = await tool.execute({"content": "No title"})
    assert result.success is False


@pytest.mark.asyncio
async def test_publish_missing_content(db):
    tool = PublishToFeedTool(db=db, feed_base_url="http://localhost:8000")
    result = await tool.execute({"title": "No content"})
    assert result.success is False
