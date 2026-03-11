"""Test conversation auto-title generation."""
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.core.auto_title import generate_title, maybe_auto_title
from odigos.db import Database


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.fallback_model = "test-fallback"
    provider.complete = AsyncMock(return_value=AsyncMock(
        content="Python Decorator Help"
    ))
    return provider


@pytest.mark.asyncio
async def test_generate_title(mock_provider):
    title = await generate_title(
        mock_provider, "Explain decorators in Python", "Decorators wrap functions..."
    )
    assert title == "Python Decorator Help"
    mock_provider.complete.assert_called_once()


@pytest.mark.asyncio
async def test_maybe_auto_title_sets_title(db, mock_provider):
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)", (conv_id, "web")
    )
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), conv_id, "user", "Explain decorators"),
    )
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), conv_id, "assistant", "Decorators wrap functions..."),
    )
    await maybe_auto_title(db, mock_provider, conv_id, "Explain decorators", "Decorators wrap functions...")
    conv = await db.fetch_one("SELECT title FROM conversations WHERE id = ?", (conv_id,))
    assert conv["title"] == "Python Decorator Help"


@pytest.mark.asyncio
async def test_maybe_auto_title_skips_if_title_exists(db, mock_provider):
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel, title) VALUES (?, ?, ?)", (conv_id, "web", "Existing Title")
    )
    await maybe_auto_title(db, mock_provider, conv_id, "msg", "resp")
    mock_provider.complete.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_auto_title_skips_after_first_exchange(db, mock_provider):
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)", (conv_id, "web")
    )
    for i in range(4):
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), conv_id, "user" if i % 2 == 0 else "assistant", f"msg {i}"),
        )
    await maybe_auto_title(db, mock_provider, conv_id, "msg", "resp")
    mock_provider.complete.assert_not_called()
