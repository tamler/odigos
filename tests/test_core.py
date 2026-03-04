import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from odigos.channels.base import UniversalMessage
from odigos.core.agent import Agent
from odigos.core.context import ContextAssembler
from odigos.core.executor import Executor
from odigos.core.planner import Planner
from odigos.core.reflector import Reflector
from odigos.db import Database
from odigos.providers.base import LLMResponse


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def mock_provider() -> AsyncMock:
    provider = AsyncMock()
    provider.complete.return_value = LLMResponse(
        content="I'm Odigos, your assistant.",
        model="test/model",
        tokens_in=20,
        tokens_out=10,
        cost_usd=0.001,
    )
    return provider


def _make_message(content: str = "Hello") -> UniversalMessage:
    return UniversalMessage(
        id=str(uuid.uuid4()),
        channel="telegram",
        sender="user-1",
        content=content,
        timestamp=datetime.now(timezone.utc),
        metadata={"chat_id": 12345},
    )


class TestContextAssembler:
    async def test_builds_messages_list(self, db: Database):
        assembler = ContextAssembler(db=db, agent_name="TestBot", history_limit=20)

        messages = await assembler.build("conv-1", "Hello there")

        assert messages[0]["role"] == "system"
        assert "TestBot" in messages[0]["content"]
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "Hello there"

    async def test_includes_conversation_history(self, db: Database):
        assembler = ContextAssembler(db=db, agent_name="TestBot", history_limit=20)

        # Insert some history
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-1", "telegram"),
        )
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            ("msg-1", "conv-1", "user", "Previous message"),
        )
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            ("msg-2", "conv-1", "assistant", "Previous response"),
        )

        messages = await assembler.build("conv-1", "New message")

        # system + 2 history + 1 current
        assert len(messages) == 4
        assert messages[1]["content"] == "Previous message"
        assert messages[2]["content"] == "Previous response"
        assert messages[3]["content"] == "New message"


class TestPlanner:
    async def test_returns_respond_plan(self):
        planner = Planner()
        plan = await planner.plan("Hello")
        assert plan.action == "respond"
        assert plan.requires_tools is False


class TestExecutor:
    async def test_calls_provider(self, db: Database, mock_provider: AsyncMock):
        assembler = ContextAssembler(db=db, agent_name="TestBot", history_limit=20)
        executor = Executor(provider=mock_provider, context_assembler=assembler)

        result = await executor.execute("conv-1", "Hello")

        assert result.content == "I'm Odigos, your assistant."
        mock_provider.complete.assert_called_once()


class TestReflector:
    async def test_stores_message(self, db: Database):
        reflector = Reflector(db=db)
        response = LLMResponse(
            content="Hi there",
            model="test/model",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
        )

        # Create the conversation first (FK constraint)
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-1", "telegram"),
        )

        await reflector.reflect("conv-1", response)

        msg = await db.fetch_one(
            "SELECT content, role FROM messages WHERE conversation_id = ? AND role = 'assistant'",
            ("conv-1",),
        )
        assert msg is not None
        assert msg["content"] == "Hi there"


class TestAgent:
    async def test_full_loop(self, db: Database, mock_provider: AsyncMock):
        agent = Agent(
            db=db,
            provider=mock_provider,
            agent_name="TestBot",
            history_limit=20,
        )
        message = _make_message("Hello agent")

        response = await agent.handle_message(message)

        assert response == "I'm Odigos, your assistant."

        # Verify conversation was created
        conv = await db.fetch_one("SELECT * FROM conversations LIMIT 1")
        assert conv is not None
        assert conv["channel"] == "telegram"

        # Verify messages stored (user + assistant)
        msgs = await db.fetch_all("SELECT role FROM messages ORDER BY timestamp")
        roles = [m["role"] for m in msgs]
        assert "user" in roles
        assert "assistant" in roles
