import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from odigos.channels.base import UniversalMessage
from odigos.core.agent import Agent
from odigos.core.context import ContextAssembler
from odigos.core.executor import Executor
from odigos.core.planner import Plan, Planner
from odigos.core.reflector import Reflector
from odigos.db import Database
from odigos.providers.base import LLMResponse
from odigos.tools.base import ToolResult
from odigos.tools.registry import ToolRegistry


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
        assembler = ContextAssembler(
            db=db,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
        )

        messages = await assembler.build("conv-1", "Hello there")

        assert messages[0]["role"] == "system"
        assert "Odigos" in messages[0]["content"]
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "Hello there"

    async def test_includes_conversation_history(self, db: Database):
        assembler = ContextAssembler(
            db=db,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
        )

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

    async def test_includes_tool_context(self, db: Database):
        assembler = ContextAssembler(
            db=db,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
        )

        messages = await assembler.build(
            "conv-1",
            "What is Python 3.13?",
            tool_context="## Web search results\n1. Python 3.13 release notes.",
        )

        system_content = messages[0]["content"]
        assert "Web search results" in system_content
        assert "Python 3.13 release notes" in system_content


class TestContextAssemblerWithMemory:
    async def test_injects_memories(self, db: Database):
        """Context includes memory section when memory manager has data."""
        mock_memory = AsyncMock()
        mock_memory.recall.return_value = "## Relevant memories\n- Alice prefers morning meetings."

        assembler = ContextAssembler(
            db=db,
            agent_name="TestBot",
            history_limit=20,
            memory_manager=mock_memory,
            personality_path="/nonexistent",
        )
        messages = await assembler.build("conv-1", "When should we meet?")

        system_content = messages[0]["content"]
        assert "Relevant memories" in system_content
        assert "Alice prefers morning meetings" in system_content

    async def test_includes_entity_extraction_instruction(self, db: Database):
        """System prompt includes entity extraction instruction."""
        assembler = ContextAssembler(
            db=db,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
        )
        messages = await assembler.build("conv-1", "Hello")

        system_content = messages[0]["content"]
        assert "<!--entities" in system_content

    async def test_no_memory_manager_still_works(self, db: Database):
        """Without memory manager, context assembler works as before."""
        assembler = ContextAssembler(
            db=db,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
        )
        messages = await assembler.build("conv-1", "Hello")

        assert messages[0]["role"] == "system"
        assert messages[-1]["content"] == "Hello"


class TestContextAssemblerWithPersonality:
    async def test_uses_personality_from_file(self, db: Database, tmp_path):
        """Context assembler loads personality from file and uses it in prompt."""
        import yaml

        personality_file = tmp_path / "personality.yaml"
        personality_file.write_text(
            yaml.dump({"name": "Hal", "voice": {"tone": "robotic and precise"}})
        )

        assembler = ContextAssembler(
            db=db,
            agent_name="Hal",
            history_limit=20,
            personality_path=str(personality_file),
        )
        messages = await assembler.build("conv-1", "Hello")

        system_content = messages[0]["content"]
        assert "Hal" in system_content
        assert "robotic and precise" in system_content

    async def test_falls_back_to_defaults(self, db: Database):
        """Missing personality file falls back to defaults."""
        assembler = ContextAssembler(
            db=db,
            agent_name="Odigos",
            history_limit=20,
            personality_path="/nonexistent/file.yaml",
        )
        messages = await assembler.build("conv-1", "Hello")

        system_content = messages[0]["content"]
        assert "Odigos" in system_content
        assert "direct, warm" in system_content


class TestPlanner:
    @pytest.fixture
    def mock_classify_provider(self):
        provider = AsyncMock()
        return provider

    async def test_classify_as_respond(self, mock_classify_provider):
        """Planner returns respond when LLM says no search needed."""
        mock_classify_provider.complete.return_value = LLMResponse(
            content='{"action": "respond"}',
            model="test/model",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.0,
        )
        planner = Planner(provider=mock_classify_provider)
        plan = await planner.plan("Hello, how are you?")

        assert plan.action == "respond"
        assert plan.tool_params == {}

    async def test_classify_as_search(self, mock_classify_provider):
        """Planner returns search with query when LLM says search needed."""
        mock_classify_provider.complete.return_value = LLMResponse(
            content='{"action": "search", "query": "weather in NYC today"}',
            model="test/model",
            tokens_in=10,
            tokens_out=10,
            cost_usd=0.0,
        )
        planner = Planner(provider=mock_classify_provider)
        plan = await planner.plan("What's the weather in NYC?")

        assert plan.action == "search"
        assert plan.tool_params == {"query": "weather in NYC today"}

    async def test_handles_markdown_wrapped_json(self, mock_classify_provider):
        """Planner extracts JSON from markdown code blocks."""
        mock_classify_provider.complete.return_value = LLMResponse(
            content='```json\n{"action": "search", "query": "test query"}\n```',
            model="test/model",
            tokens_in=10,
            tokens_out=10,
            cost_usd=0.0,
        )
        planner = Planner(provider=mock_classify_provider)
        plan = await planner.plan("search for something")

        assert plan.action == "search"
        assert plan.tool_params == {"query": "test query"}

    async def test_fallback_to_respond_on_parse_error(self, mock_classify_provider):
        """Planner falls back to respond if LLM returns unparseable response."""
        mock_classify_provider.complete.return_value = LLMResponse(
            content="I'm not sure what you mean",
            model="test/model",
            tokens_in=10,
            tokens_out=10,
            cost_usd=0.0,
        )
        planner = Planner(provider=mock_classify_provider)
        plan = await planner.plan("something weird")

        assert plan.action == "respond"

    async def test_fallback_to_respond_on_provider_error(self, mock_classify_provider):
        """Planner falls back to respond if LLM call fails entirely."""
        mock_classify_provider.complete.side_effect = RuntimeError("API down")
        planner = Planner(provider=mock_classify_provider)
        plan = await planner.plan("search for something")

        assert plan.action == "respond"

    async def test_classify_as_scrape(self, mock_classify_provider):
        """Planner returns scrape with URL when LLM detects page-reading intent."""
        mock_classify_provider.complete.return_value = LLMResponse(
            content='{"action": "scrape", "url": "https://example.com/article"}',
            model="test/model",
            tokens_in=10,
            tokens_out=10,
            cost_usd=0.0,
        )
        planner = Planner(provider=mock_classify_provider)
        plan = await planner.plan("Read this page: https://example.com/article")

        assert plan.action == "scrape"
        assert plan.tool_params == {"url": "https://example.com/article"}


class TestExecutor:
    async def test_execute_respond(self, db: Database, mock_provider: AsyncMock):
        """Respond plan calls LLM directly without tools."""
        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20, personality_path="/nonexistent"
        )
        executor = Executor(provider=mock_provider, context_assembler=assembler)
        plan = Plan(action="respond")

        result = await executor.execute("conv-1", "Hello", plan=plan)

        assert result.response.content == "I'm Odigos, your assistant."
        mock_provider.complete.assert_called_once()

    async def test_execute_search(self, db: Database, mock_provider: AsyncMock):
        """Search plan calls tool then LLM with results in context."""
        mock_tool = AsyncMock()
        mock_tool.name = "web_search"
        mock_tool.execute.return_value = ToolResult(success=True, data="## Results\n1. Python docs")

        registry = ToolRegistry()
        registry.register(mock_tool)

        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20, personality_path="/nonexistent"
        )
        executor = Executor(
            provider=mock_provider, context_assembler=assembler, tool_registry=registry
        )
        plan = Plan(action="search", requires_tools=True, tool_params={"query": "python docs"})

        _result = await executor.execute("conv-1", "Find python docs", plan=plan)

        # Tool should have been called
        mock_tool.execute.assert_called_once_with({"query": "python docs"})
        # LLM should have been called with tool results in context
        mock_provider.complete.assert_called_once()
        call_messages = mock_provider.complete.call_args[0][0]
        system_content = call_messages[0]["content"]
        assert "Results" in system_content

    async def test_execute_search_tool_failure(self, db: Database, mock_provider: AsyncMock):
        """Search falls back to normal response if tool fails."""
        mock_tool = AsyncMock()
        mock_tool.name = "web_search"
        mock_tool.execute.return_value = ToolResult(
            success=False, data="", error="Connection refused"
        )

        registry = ToolRegistry()
        registry.register(mock_tool)

        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20, personality_path="/nonexistent"
        )
        executor = Executor(
            provider=mock_provider, context_assembler=assembler, tool_registry=registry
        )
        plan = Plan(action="search", requires_tools=True, tool_params={"query": "test"})

        result = await executor.execute("conv-1", "search for test", plan=plan)

        # Should still get a response (LLM called without tool results)
        assert result.response.content == "I'm Odigos, your assistant."

    async def test_backward_compat_no_plan(self, db: Database, mock_provider: AsyncMock):
        """Executor works without plan (backward compat, defaults to respond)."""
        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20, personality_path="/nonexistent"
        )
        executor = Executor(provider=mock_provider, context_assembler=assembler)

        result = await executor.execute("conv-1", "Hello")

        assert result.response.content == "I'm Odigos, your assistant."

    async def test_execute_scrape(self, db: Database, mock_provider: AsyncMock):
        """Scrape plan calls read_page tool then LLM with page content in context."""
        mock_tool = AsyncMock()
        mock_tool.name = "read_page"
        mock_tool.execute.return_value = ToolResult(
            success=True, data="## Page: Example\n\nThe article content."
        )

        registry = ToolRegistry()
        registry.register(mock_tool)

        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20, personality_path="/nonexistent"
        )
        executor = Executor(
            provider=mock_provider, context_assembler=assembler, tool_registry=registry
        )
        plan = Plan(action="scrape", requires_tools=True, tool_params={"url": "https://example.com"})

        _result = await executor.execute("conv-1", "Read this page", plan=plan)

        mock_tool.execute.assert_called_once_with({"url": "https://example.com"})
        mock_provider.complete.assert_called_once()
        call_messages = mock_provider.complete.call_args[0][0]
        system_content = call_messages[0]["content"]
        assert "article content" in system_content


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


class TestReflectorWithMemory:
    async def test_parses_entity_block(self, db: Database):
        """Reflector parses <!--entities--> block from response and strips it."""
        mock_memory = AsyncMock()
        reflector = Reflector(db=db, memory_manager=mock_memory)

        content_with_entities = (
            "Hello! I can help with that.\n\n"
            "<!--entities\n"
            '[{"name": "Alice", "type": "person", "relationship": "friend", "detail": "engineer"}]\n'
            "-->"
        )
        response = LLMResponse(
            content=content_with_entities,
            model="test/model",
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.001,
        )

        # Create conversation first
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-1", "test"),
        )

        await reflector.reflect("conv-1", response, user_message="I talked to Alice")

        # Memory manager should have been called with extracted entities
        mock_memory.store.assert_called_once()
        call_kwargs = mock_memory.store.call_args.kwargs
        assert len(call_kwargs["extracted_entities"]) == 1
        assert call_kwargs["extracted_entities"][0]["name"] == "Alice"

        # Stored message should NOT contain the entities block
        msg = await db.fetch_one(
            "SELECT content FROM messages WHERE conversation_id = 'conv-1' AND role = 'assistant'"
        )
        assert "<!--entities" not in msg["content"]
        assert "Hello! I can help with that." in msg["content"]

    async def test_no_entity_block(self, db: Database):
        """Reflector works normally when no entity block is present."""
        mock_memory = AsyncMock()
        reflector = Reflector(db=db, memory_manager=mock_memory)

        response = LLMResponse(
            content="Just a normal response.",
            model="test/model",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
        )

        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-2", "test"),
        )

        await reflector.reflect("conv-2", response, user_message="Hello")

        # Memory manager called with empty entities
        mock_memory.store.assert_called_once()
        call_kwargs = mock_memory.store.call_args.kwargs
        assert call_kwargs["extracted_entities"] == []

    async def test_reflector_backward_compatible(self, db: Database):
        """Reflector without memory_manager still works (Phase 0 compat)."""
        reflector = Reflector(db=db)
        response = LLMResponse(
            content="Hi there", model="m", tokens_in=1, tokens_out=1, cost_usd=0.0
        )

        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-3", "test"),
        )

        await reflector.reflect("conv-3", response)

        msg = await db.fetch_one("SELECT content FROM messages WHERE conversation_id = 'conv-3'")
        assert msg["content"] == "Hi there"


class TestAgentWithMemory:
    async def test_full_loop_with_memory(self, db: Database, mock_provider: AsyncMock):
        """Agent passes user_message to reflector when memory is wired."""
        mock_memory = AsyncMock()
        mock_memory.recall.return_value = ""

        mock_planner_provider = AsyncMock()
        mock_planner_provider.complete.return_value = LLMResponse(
            content='{"action": "respond"}',
            model="test/model",
            tokens_in=5,
            tokens_out=5,
            cost_usd=0.0,
        )

        agent = Agent(
            db=db,
            provider=mock_provider,
            agent_name="TestBot",
            history_limit=20,
            memory_manager=mock_memory,
            personality_path="/nonexistent",
            planner_provider=mock_planner_provider,
        )
        message = _make_message("Hello agent")

        response = await agent.handle_message(message)
        assert response == "I'm Odigos, your assistant."

        mock_memory.store.assert_called_once()


class TestAgent:
    async def test_full_loop(self, db: Database, mock_provider: AsyncMock):
        mock_planner_provider = AsyncMock()
        mock_planner_provider.complete.return_value = LLMResponse(
            content='{"action": "respond"}',
            model="test/model",
            tokens_in=5,
            tokens_out=5,
            cost_usd=0.0,
        )

        agent = Agent(
            db=db,
            provider=mock_provider,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
            planner_provider=mock_planner_provider,
        )
        message = _make_message("Hello agent")

        response = await agent.handle_message(message)

        assert response == "I'm Odigos, your assistant."

        conv = await db.fetch_one("SELECT * FROM conversations LIMIT 1")
        assert conv is not None
        assert conv["channel"] == "telegram"

        msgs = await db.fetch_all("SELECT role FROM messages ORDER BY timestamp")
        roles = [m["role"] for m in msgs]
        assert "user" in roles
        assert "assistant" in roles

    async def test_search_flow(self, db: Database, mock_provider: AsyncMock):
        """Agent performs search when planner classifies as search intent."""
        mock_planner_provider = AsyncMock()
        mock_planner_provider.complete.return_value = LLMResponse(
            content='{"action": "search", "query": "python 3.13 features"}',
            model="test/model",
            tokens_in=5,
            tokens_out=10,
            cost_usd=0.0,
        )

        mock_tool = AsyncMock()
        mock_tool.name = "web_search"
        mock_tool.execute.return_value = ToolResult(
            success=True, data="## Results\n1. Python 3.13 released"
        )

        registry = ToolRegistry()
        registry.register(mock_tool)

        agent = Agent(
            db=db,
            provider=mock_provider,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
            planner_provider=mock_planner_provider,
            tool_registry=registry,
        )
        message = _make_message("What's new in Python 3.13?")

        response = await agent.handle_message(message)
        assert response == "I'm Odigos, your assistant."

        mock_tool.execute.assert_called_once()

    async def test_scrape_flow(self, db: Database, mock_provider: AsyncMock):
        """Agent performs scrape when planner classifies as scrape intent."""
        mock_planner_provider = AsyncMock()
        mock_planner_provider.complete.return_value = LLMResponse(
            content='{"action": "scrape", "url": "https://example.com/page"}',
            model="test/model",
            tokens_in=5,
            tokens_out=10,
            cost_usd=0.0,
        )

        mock_tool = AsyncMock()
        mock_tool.name = "read_page"
        mock_tool.execute.return_value = ToolResult(
            success=True, data="## Page: Example\n\n**URL:** https://example.com/page\n\nPage content here."
        )

        registry = ToolRegistry()
        registry.register(mock_tool)

        agent = Agent(
            db=db,
            provider=mock_provider,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
            planner_provider=mock_planner_provider,
            tool_registry=registry,
        )
        message = _make_message("Read this: https://example.com/page")

        response = await agent.handle_message(message)
        assert response == "I'm Odigos, your assistant."

        mock_tool.execute.assert_called_once()

        # Verify scrape was logged
        row = await db.fetch_one("SELECT url FROM scraped_pages LIMIT 1")
        assert row is not None
        assert row["url"] == "https://example.com/page"


class TestReflectorScrapeLog:
    async def test_logs_scrape_to_db(self, db: Database):
        """Reflector logs scrape metadata to scraped_pages table."""
        reflector = Reflector(db=db)
        response = LLMResponse(
            content="Here's a summary of the page.",
            model="test/model",
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.001,
        )

        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-scrape", "test"),
        )

        await reflector.reflect(
            "conv-scrape",
            response,
            user_message="Read this page",
            scrape_metadata={
                "url": "https://example.com/article",
                "title": "Example Article",
                "content": "This is the main article content about testing.",
            },
        )

        row = await db.fetch_one(
            "SELECT url, title, summary FROM scraped_pages WHERE url = ?",
            ("https://example.com/article",),
        )
        assert row is not None
        assert row["url"] == "https://example.com/article"
        assert row["title"] == "Example Article"
        assert "main article content" in row["summary"]

    async def test_no_scrape_metadata_no_log(self, db: Database):
        """Without scrape_metadata, no scraped_pages entry is created."""
        reflector = Reflector(db=db)
        response = LLMResponse(
            content="Normal response.",
            model="test/model",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
        )

        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-no-scrape", "test"),
        )

        await reflector.reflect("conv-no-scrape", response, user_message="Hello")

        rows = await db.fetch_all("SELECT * FROM scraped_pages")
        assert len(rows) == 0
