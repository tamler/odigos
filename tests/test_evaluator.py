"""Tests for the evaluator (implicit feedback + C.1/C.2 scoring)."""
import json
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.core.evaluator import Evaluator, infer_implicit_feedback
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
    return provider


def _insert_message(db, conv_id, role, content, ts_offset_minutes=0):
    """Helper to insert a message with controlled timestamp."""
    msg_id = str(uuid.uuid4())
    ts = (datetime.now(timezone.utc) + timedelta(minutes=ts_offset_minutes)).isoformat()
    return msg_id, db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (msg_id, conv_id, role, content, ts),
    )


# --- Implicit feedback inference tests ---

@pytest.mark.asyncio
async def test_feedback_correction_is_negative(db):
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)", (conv_id, "test")
    )
    _, coro = _insert_message(db, conv_id, "user", "What is Python?", -2)
    await coro
    asst_id, coro = _insert_message(db, conv_id, "assistant", "Python is a snake.", -1)
    await coro
    _, coro = _insert_message(db, conv_id, "user", "No, I meant the programming language.", 0)
    await coro

    score = await infer_implicit_feedback(db, asst_id, conv_id)
    assert score < 0  # Correction = negative


@pytest.mark.asyncio
async def test_feedback_acknowledgment_is_positive(db):
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)", (conv_id, "test")
    )
    _, coro = _insert_message(db, conv_id, "user", "Explain decorators", -2)
    await coro
    asst_id, coro = _insert_message(db, conv_id, "assistant", "Decorators wrap functions...", -1)
    await coro
    _, coro = _insert_message(db, conv_id, "user", "Thanks, that makes sense!", 0)
    await coro

    score = await infer_implicit_feedback(db, asst_id, conv_id)
    assert score > 0  # Acknowledgment = positive


# --- C.1/C.2 scoring tests ---

@pytest.mark.asyncio
async def test_evaluate_action_stores_result(db, mock_provider):
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)", (conv_id, "test")
    )
    msg_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
        (msg_id, conv_id, "assistant", "Here is some code..."),
    )
    # Mock LLM returns rubric then score
    mock_provider.complete = AsyncMock(side_effect=[
        # C.1 rubric response
        AsyncMock(content=json.dumps({
            "task_type": "code_generation",
            "criteria": [{"name": "correctness", "weight": 1.0, "description": "code works"}],
            "notes": "test",
        })),
        # C.2 score response
        AsyncMock(content=json.dumps({
            "scores": [{"criterion": "correctness", "score": 8, "observation": "looks good"}],
            "overall": 8.0,
            "improvement_signal": None,
        })),
    ])

    evaluator = Evaluator(db=db, provider=mock_provider)
    result = await evaluator.evaluate_action(msg_id, conv_id)

    assert result is not None
    assert result["overall_score"] == 8.0
    row = await db.fetch_one("SELECT * FROM evaluations WHERE message_id = ?", (msg_id,))
    assert row is not None
    assert row["overall_score"] == 8.0


@pytest.mark.asyncio
async def test_get_unscored_messages(db, mock_provider):
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)", (conv_id, "test")
    )
    for i in range(3):
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), conv_id, "assistant", f"Response {i}"),
        )
    evaluator = Evaluator(db=db, provider=mock_provider)
    unscored = await evaluator.get_unscored_messages(limit=5)
    assert len(unscored) == 3
