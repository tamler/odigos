import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from odigos.channels.base import UniversalMessage
from odigos.core.agent import Agent
from odigos.core.context import ContextAssembler
from odigos.core.executor import Executor
from odigos.core.reflector import Reflector
from odigos.db import Database
from odigos.providers.base import LLMResponse, ToolCall
from odigos.skills.registry import SkillRegistry, Skill
from odigos.tools.base import ToolContract, ToolResult
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


class TestExecutor:
    async def test_execute_respond(self, db: Database, mock_provider: AsyncMock):
        """Simple response without tool calls."""
        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20        )
        executor = Executor(provider=mock_provider, context_assembler=assembler)

        result = await executor.execute("conv-1", "Hello")

        assert result.response.content == "I'm Odigos, your assistant."
        mock_provider.complete.assert_called_once()

    async def test_execute_search(self, db: Database, mock_provider: AsyncMock):
        """LLM calls web_search tool, gets results, then responds."""
        mock_tool = AsyncMock()
        mock_tool.name = "web_search"
        mock_tool.description = "Search"
        mock_tool.parameters_schema = {"type": "object", "properties": {"query": {"type": "string"}}}
        mock_tool.contract = ToolContract()
        mock_tool.execute.return_value = ToolResult(success=True, data="## Results\n1. Python docs")
        mock_tool.format_for_context = lambda result: result.data

        registry = ToolRegistry()
        registry.register(mock_tool)

        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20        )
        executor = Executor(
            provider=mock_provider, context_assembler=assembler, tool_registry=registry
        )

        mock_provider.complete.side_effect = [
            LLMResponse(
                content="", model="test/model", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="web_search", arguments={"query": "python docs"})],
            ),
            LLMResponse(
                content="Here are the Python docs.", model="test/model",
                tokens_in=20, tokens_out=15, cost_usd=0.002,
            ),
        ]

        result = await executor.execute("conv-1", "Find python docs")

        mock_tool.execute.assert_called_once_with({"query": "python docs", "_conversation_id": "conv-1", "_goal_id": None})
        assert mock_provider.complete.call_count == 2
        assert "Python docs" in result.response.content

    async def test_execute_search_tool_failure(self, db: Database, mock_provider: AsyncMock):
        """Tool failure feeds error back, LLM responds gracefully."""
        mock_tool = AsyncMock()
        mock_tool.name = "web_search"
        mock_tool.description = "Search"
        mock_tool.parameters_schema = {"type": "object", "properties": {"query": {"type": "string"}}}
        mock_tool.contract = ToolContract()
        mock_tool.execute.return_value = ToolResult(
            success=False, data="", error="Connection refused"
        )

        registry = ToolRegistry()
        registry.register(mock_tool)

        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20        )
        executor = Executor(
            provider=mock_provider, context_assembler=assembler, tool_registry=registry
        )

        mock_provider.complete.side_effect = [
            LLMResponse(
                content="", model="test/model", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="web_search", arguments={"query": "test"})],
            ),
            LLMResponse(
                content="I'm Odigos, your assistant.", model="test/model",
                tokens_in=20, tokens_out=10, cost_usd=0.001,
            ),
        ]

        result = await executor.execute("conv-1", "search for test")

        assert result.response.content == "I'm Odigos, your assistant."

    async def test_execute_scrape(self, db: Database, mock_provider: AsyncMock):
        """LLM calls read_page tool, gets page content, then responds."""
        mock_tool = AsyncMock()
        mock_tool.name = "read_page"
        mock_tool.description = "Read page"
        mock_tool.parameters_schema = {"type": "object", "properties": {"url": {"type": "string"}}}
        mock_tool.contract = ToolContract()
        mock_tool.execute.return_value = ToolResult(
            success=True, data="## Page: Example\n\nThe article content."
        )
        mock_tool.format_for_context = lambda result: result.data

        registry = ToolRegistry()
        registry.register(mock_tool)

        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20        )
        executor = Executor(
            provider=mock_provider, context_assembler=assembler, tool_registry=registry
        )

        mock_provider.complete.side_effect = [
            LLMResponse(
                content="", model="test/model", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="read_page", arguments={"url": "https://example.com"})],
            ),
            LLMResponse(
                content="Here is the article content.", model="test/model",
                tokens_in=20, tokens_out=15, cost_usd=0.002,
            ),
        ]

        result = await executor.execute("conv-1", "Read this page")

        mock_tool.execute.assert_called_once_with({"url": "https://example.com", "_conversation_id": "conv-1", "_goal_id": None})
        assert mock_provider.complete.call_count == 2


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
        """Reflector stores response content and passes extracted data to memory manager."""
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

        # Memory manager should have been called with extracted data
        mock_memory.store.assert_called_once()
        call_kwargs = mock_memory.store.call_args.kwargs
        extracted = call_kwargs["extracted"]
        # Extraction now uses a dedicated LLM call (not inline parsing), so
        # without an extraction provider the entities list is empty
        assert extracted["entities"] == []

        # Entity blocks are no longer stripped from content (extraction is
        # done via a separate LLM call now). The raw content is stored as-is.
        msg = await db.fetch_one(
            "SELECT content FROM messages WHERE conversation_id = 'conv-1' AND role = 'assistant'"
        )
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

        # Memory manager called with extracted dict
        mock_memory.store.assert_called_once()
        call_kwargs = mock_memory.store.call_args.kwargs
        extracted = call_kwargs["extracted"]
        assert extracted["entities"] == []

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

        agent = Agent(
            db=db,
            provider=mock_provider,
            agent_name="TestBot",
            history_limit=20,
            memory_manager=mock_memory,

        )
        message = _make_message("Hello agent")

        response = await agent.handle_message(message)
        assert response == "I'm Odigos, your assistant."

        mock_memory.store.assert_called_once()


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

        conv = await db.fetch_one("SELECT * FROM conversations LIMIT 1")
        assert conv is not None
        assert conv["channel"] == "telegram"

        msgs = await db.fetch_all("SELECT role FROM messages ORDER BY created_at")
        roles = [m["role"] for m in msgs]
        assert "user" in roles
        assert "assistant" in roles

    async def test_search_flow(self, db: Database, mock_provider: AsyncMock):
        """Agent performs search when LLM decides to call web_search tool."""
        mock_tool = AsyncMock()
        mock_tool.name = "web_search"
        mock_tool.description = "Search"
        mock_tool.parameters_schema = {"type": "object", "properties": {"query": {"type": "string"}}}
        mock_tool.contract = ToolContract()
        mock_tool.execute.return_value = ToolResult(
            success=True, data="## Results\n1. Python 3.13 released"
        )
        mock_tool.format_for_context = lambda result: result.data

        registry = ToolRegistry()
        registry.register(mock_tool)

        mock_provider.complete.side_effect = [
            LLMResponse(
                content="", model="test/model", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="web_search", arguments={"query": "python 3.13 features"})],
            ),
            LLMResponse(
                content="Python 3.13 has exciting new features!", model="test/model",
                tokens_in=20, tokens_out=15, cost_usd=0.002,
            ),
        ]

        agent = Agent(
            db=db,
            provider=mock_provider,
            agent_name="TestBot",
            history_limit=20,

            tool_registry=registry,
        )
        message = _make_message("What's new in Python 3.13?")

        response = await agent.handle_message(message)
        assert "Python 3.13" in response

        mock_tool.execute.assert_called_once()

    async def test_scrape_flow(self, db: Database, mock_provider: AsyncMock):
        """Agent performs scrape when LLM decides to call read_page tool."""
        mock_tool = AsyncMock()
        mock_tool.name = "read_page"
        mock_tool.description = "Read page"
        mock_tool.parameters_schema = {"type": "object", "properties": {"url": {"type": "string"}}}
        mock_tool.contract = ToolContract()
        mock_tool.execute.return_value = ToolResult(
            success=True,
            data="## Page: Example\n\n**URL:** https://example.com/page\n\nPage content here.",
        )
        mock_tool.format_for_context = lambda result: result.data

        registry = ToolRegistry()
        registry.register(mock_tool)

        mock_provider.complete.side_effect = [
            LLMResponse(
                content="", model="test/model", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="read_page", arguments={"url": "https://example.com/page"})],
            ),
            LLMResponse(
                content="Here's a summary of the page.", model="test/model",
                tokens_in=20, tokens_out=15, cost_usd=0.002,
            ),
        ]

        agent = Agent(
            db=db,
            provider=mock_provider,
            agent_name="TestBot",
            history_limit=20,

            tool_registry=registry,
        )
        message = _make_message("Read this: https://example.com/page")

        response = await agent.handle_message(message)
        assert response == "Here's a summary of the page."

        mock_tool.execute.assert_called_once()


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


class TestExecutorDocumentAction:
    async def test_executor_calls_document_tool(self, db: Database, mock_provider: AsyncMock):
        mock_doc_tool = AsyncMock()
        mock_doc_tool.name = "read_document"
        mock_doc_tool.description = "Read document"
        mock_doc_tool.parameters_schema = {"type": "object", "properties": {"path": {"type": "string"}}}
        mock_doc_tool.contract = ToolContract()
        mock_doc_tool.execute.return_value = ToolResult(
            success=True, data="# Meeting Notes\n\n- Action items listed"
        )
        mock_doc_tool.format_for_context = lambda result: result.data

        registry = ToolRegistry()
        registry.register(mock_doc_tool)

        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20        )
        executor = Executor(
            provider=mock_provider, context_assembler=assembler, tool_registry=registry
        )

        mock_provider.complete.side_effect = [
            LLMResponse(
                content="", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="read_document", arguments={"path": "/tmp/test.pdf"})],
            ),
            LLMResponse(
                content="Here are the meeting notes.", model="test",
                tokens_in=20, tokens_out=15, cost_usd=0.002,
            ),
        ]

        result = await executor.execute("conv-1", "Read this document")

        registry_tool = registry.get("read_document")
        assert registry_tool is not None
        mock_doc_tool.execute.assert_called_once_with({"path": "/tmp/test.pdf", "_conversation_id": "conv-1", "_goal_id": None})
        assert result.response.content == "Here are the meeting notes."


class TestExecutorCodeAction:
    async def test_code_action_uses_run_code_tool(self, db: Database, mock_provider: AsyncMock):
        mock_code_tool = AsyncMock()
        mock_code_tool.name = "run_code"
        mock_code_tool.description = "Run code"
        mock_code_tool.parameters_schema = {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "language": {"type": "string"},
            },
        }
        mock_code_tool.contract = ToolContract()
        mock_code_tool.execute.return_value = ToolResult(success=True, data="42\n")
        mock_code_tool.format_for_context = lambda result: result.data

        registry = ToolRegistry()
        registry.register(mock_code_tool)

        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20        )
        executor = Executor(
            provider=mock_provider, context_assembler=assembler, tool_registry=registry
        )

        mock_provider.complete.side_effect = [
            LLMResponse(
                content="", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="run_code", arguments={"code": "print(42)", "language": "python"})],
            ),
            LLMResponse(
                content="The answer is 42.", model="test",
                tokens_in=20, tokens_out=10, cost_usd=0.002,
            ),
        ]

        result = await executor.execute("conv-1", "calculate 42")
        registry_tool = registry.get("run_code")
        assert registry_tool is not None
        mock_code_tool.execute.assert_called_once_with({"code": "print(42)", "language": "python", "_conversation_id": "conv-1", "_goal_id": None})
        assert result.response.content == "The answer is 42."


class TestAgentBudgetEnforcement:
    async def test_over_budget_returns_low_cost_response(self, db: Database):
        """When budget is exceeded, agent returns canned response without LLM call."""
        mock_provider = AsyncMock()
        mock_budget = AsyncMock()
        mock_budget.check_budget = AsyncMock(
            return_value=AsyncMock(within_budget=False)
        )

        agent = Agent(db=db, provider=mock_provider, agent_name="TestBot", budget_tracker=mock_budget)

        message = UniversalMessage(
            id="msg-1",
            channel="test",
            sender="user-1",
            content="hello",
            timestamp=datetime.now(timezone.utc),
            metadata={"chat_id": "123"},
        )
        response = await agent.handle_message(message)
        assert "spending limit" in response
        mock_provider.complete.assert_not_called()

    async def test_within_budget_proceeds_normally(self, db: Database):
        """When budget is fine, agent works normally."""
        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(
            return_value=LLMResponse(
                content="Hello!", model="test", tokens_in=10, tokens_out=5, cost_usd=0.001
            )
        )
        mock_budget = AsyncMock()
        mock_budget.check_budget = AsyncMock(
            return_value=AsyncMock(within_budget=True, warning=False, circuit_breaker=False)
        )

        agent = Agent(db=db, provider=mock_provider, agent_name="TestBot", budget_tracker=mock_budget)

        message = UniversalMessage(
            id="msg-2",
            channel="test",
            sender="user-1",
            content="hi",
            timestamp=datetime.now(timezone.utc),
            metadata={"chat_id": "123"},
        )
        response = await agent.handle_message(message)
        assert response == "Hello!"
        assert mock_provider.complete.call_count == 1


class TestExecutorErrorRecovery:
    async def test_llm_failure_returns_graceful_message(self, db: Database):
        """Executor returns a user-friendly message when all LLM models fail."""
        provider = AsyncMock()
        provider.complete.side_effect = RuntimeError("All LLM providers failed")

        context = AsyncMock()
        context.build.return_value = [
            {"role": "system", "content": "test"},
            {"role": "user", "content": "hello"},
        ]

        executor = Executor(provider=provider, context_assembler=context, db=db)
        result = await executor.execute("test-conv", "hello")

        assert result.response.content is not None
        assert "trouble" in result.response.content.lower() or "couldn't" in result.response.content.lower()
        assert result.response.model == "system"

    async def test_llm_failure_does_not_crash(self, db: Database):
        """Agent.handle_message doesn't propagate LLM exceptions to the caller."""
        provider = AsyncMock()
        provider.complete.side_effect = RuntimeError("Connection refused")

        agent = Agent(db=db, provider=provider, agent_name="TestBot")
        msg = UniversalMessage(
            id="test-1", content="hello", sender="user1",
            channel="test", metadata={"chat_id": "1"},
            timestamp=datetime.now(timezone.utc),
        )
        # Should NOT raise
        response = await agent.handle_message(msg)
        assert isinstance(response, str)
        assert len(response) > 0


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("sentence_transformers"),
    reason="sentence_transformers not installed",
)
class TestEmbeddingFailureResilience:
    async def test_memory_store_survives_embedding_failure(self, db: Database):
        """MemoryManager.store() logs warning but doesn't raise when embedding fails."""
        from unittest.mock import AsyncMock
        from odigos.memory.manager import MemoryManager

        memory_store = AsyncMock()
        memory_store.store.side_effect = RuntimeError("Embedding model crashed")
        memory_recall = AsyncMock()
        graph = AsyncMock()
        resolver = AsyncMock()
        resolver.resolve.return_value = AsyncMock(entity_id="e1")
        summarizer = AsyncMock()

        mm = MemoryManager(
            memory_store=memory_store, memory_recall=memory_recall,
            graph=graph, resolver=resolver, summarizer=summarizer,
        )

        # Should NOT raise
        await mm.store(
            conversation_id="c1",
            user_message="hello",
            assistant_response="hi",
            extracted=None,
        )

    async def test_reflector_survives_memory_failure(self, db: Database):
        """Reflector.reflect() returns clean content even if memory storage fails."""
        from unittest.mock import AsyncMock
        from odigos.core.reflector import Reflector
        from odigos.providers.base import LLMResponse

        memory_manager = AsyncMock()
        memory_manager.store.side_effect = RuntimeError("Memory system down")

        reflector = Reflector(db=db, memory_manager=memory_manager)
        response = LLMResponse(
            content="Hello there!", model="test",
            tokens_in=10, tokens_out=5, cost_usd=0.001,
        )

        # Create conversation for FK constraint
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("c1", "test"),
        )

        # Should NOT raise, should return clean content
        result = await reflector.reflect("c1", response, user_message="hi")
        assert result == "Hello there!"


class TestTransactionSafety:
    async def test_ingester_records_partial_chunk_count(self, db: Database):
        """DocumentIngester records chunks that were successfully stored before failure."""
        from unittest.mock import AsyncMock
        from odigos.memory.ingester import DocumentIngester

        memory_store = AsyncMock()
        store_count = 0
        async def store_then_fail(**kwargs):
            nonlocal store_count
            store_count += 1
            if store_count >= 3:
                raise RuntimeError("Embedding failed")
            return "vec-id"
        memory_store.store.side_effect = store_then_fail

        from odigos.memory.chunking import ChunkingService

        chunking = ChunkingService()
        ingester = DocumentIngester(db=db, memory_store=memory_store, chunking_service=chunking)
        # Build a text long enough to produce multiple chunks (over 500 tokens)
        text = ("Paragraph about topic A. " * 80 + "\n\n") * 5

        # Pre-check: chunking produces multiple chunks
        chunks = chunking.chunk(text, content_type="document")
        assert len(chunks) >= 3, f"Expected at least 3 chunks, got {len(chunks)}"

        # Should not raise, should record partial progress
        doc_id = await ingester.ingest(text, "test.txt")

        doc = await db.fetch_one("SELECT * FROM documents WHERE id = ?", (doc_id,))
        assert doc is not None
        # chunk_count should reflect what was actually stored (2 of N)
        assert doc["chunk_count"] == 2


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("sentence_transformers"),
    reason="sentence_transformers not installed",
)
class TestChunkingIntegration:
    async def test_long_message_is_chunked_before_storage(self, db: Database):
        """Long user messages are chunked before vector storage."""
        from unittest.mock import AsyncMock, call
        from odigos.memory.chunking import ChunkingService
        from odigos.memory.manager import MemoryManager

        memory_store = AsyncMock()
        memory_store.store.return_value = "vec-id"
        memory_recall = AsyncMock()
        memory_recall.search.return_value = []
        graph = AsyncMock()
        resolver = AsyncMock()
        summarizer = AsyncMock()
        chunking = ChunkingService()

        mm = MemoryManager(
            memory_store=memory_store, memory_recall=memory_recall,
            graph=graph, resolver=resolver, summarizer=summarizer,
            chunking_service=chunking,
        )

        long_msg = "This is a detailed message about cats. " * 200
        await mm.store("c1", long_msg, "response", [])

        # Should have been called multiple times (once per chunk)
        assert memory_store.store.call_count > 1
