import asyncio
import uuid as uuid_mod
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from odigos.channels.base import UniversalMessage
from odigos.core.agent import Agent
from odigos.core.context import ContextAssembler
from odigos.core.executor import Executor, ExecuteResult
from odigos.db import Database
from odigos.providers.base import LLMResponse, ToolCall
from odigos.tools.base import BaseTool, ToolResult
from odigos.tools.registry import ToolRegistry


@pytest.fixture
def mock_assembler():
    assembler = AsyncMock()
    assembler.build = AsyncMock(return_value=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello"},
    ])
    return assembler


@pytest.fixture
def mock_provider():
    return AsyncMock()


def _make_message(content: str = "Hello") -> UniversalMessage:
    return UniversalMessage(
        id=str(uuid_mod.uuid4()),
        channel="telegram",
        sender="user-1",
        content=content,
        timestamp=datetime.now(timezone.utc),
        metadata={"chat_id": 12345},
    )


class TestReActLoop:
    @pytest.mark.asyncio
    async def test_simple_response_no_tools(self, mock_provider, mock_assembler):
        """LLM responds with text only -- no loop iteration."""
        mock_provider.complete.return_value = LLMResponse(
            content="Hello!", model="test", tokens_in=10, tokens_out=5, cost_usd=0.001,
        )
        executor = Executor(provider=mock_provider, context_assembler=mock_assembler)
        result = await executor.execute("conv-1", "Hello")
        assert result.response.content == "Hello!"
        assert mock_provider.complete.call_count == 1

    @pytest.mark.asyncio
    async def test_single_tool_call_then_response(self, mock_provider, mock_assembler):
        """LLM calls a tool, gets result, then responds."""
        mock_tool = AsyncMock(spec=BaseTool)
        mock_tool.name = "web_search"
        mock_tool.description = "Search"
        mock_tool.parameters_schema = {"type": "object", "properties": {}}
        mock_tool.execute.return_value = ToolResult(success=True, data="Python 3.13 released")

        registry = ToolRegistry()
        registry.register(mock_tool)

        mock_provider.complete.side_effect = [
            LLMResponse(
                content="", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="web_search", arguments={"query": "python 3.13"})],
            ),
            LLMResponse(
                content="Python 3.13 was just released!", model="test",
                tokens_in=20, tokens_out=15, cost_usd=0.002,
            ),
        ]

        executor = Executor(provider=mock_provider, context_assembler=mock_assembler, tool_registry=registry)
        result = await executor.execute("conv-1", "What's new in Python?")
        assert result.response.content == "Python 3.13 was just released!"
        assert mock_provider.complete.call_count == 2
        mock_tool.execute.assert_called_once_with({"query": "python 3.13", "_conversation_id": "conv-1"})

    @pytest.mark.asyncio
    async def test_multi_turn_tool_calls(self, mock_provider, mock_assembler):
        """LLM calls tools across multiple turns before responding."""
        mock_search = AsyncMock(spec=BaseTool)
        mock_search.name = "web_search"
        mock_search.description = "Search"
        mock_search.parameters_schema = {"type": "object", "properties": {}}
        mock_search.execute.return_value = ToolResult(success=True, data="Result 1")

        mock_scrape = AsyncMock(spec=BaseTool)
        mock_scrape.name = "read_page"
        mock_scrape.description = "Read page"
        mock_scrape.parameters_schema = {"type": "object", "properties": {}}
        mock_scrape.execute.return_value = ToolResult(success=True, data="Page content")

        registry = ToolRegistry()
        registry.register(mock_search)
        registry.register(mock_scrape)

        mock_provider.complete.side_effect = [
            LLMResponse(content="", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="web_search", arguments={"query": "AI news"})]),
            LLMResponse(content="", model="test", tokens_in=20, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_2", name="read_page", arguments={"url": "https://example.com"})]),
            LLMResponse(content="Here's a summary of AI news.", model="test",
                tokens_in=30, tokens_out=20, cost_usd=0.002),
        ]

        executor = Executor(provider=mock_provider, context_assembler=mock_assembler, tool_registry=registry)
        result = await executor.execute("conv-1", "Research AI news")
        assert result.response.content == "Here's a summary of AI news."
        assert mock_provider.complete.call_count == 3

    @pytest.mark.asyncio
    async def test_max_tool_turns_limit(self, mock_provider, mock_assembler):
        """Loop stops after max_tool_turns even if LLM keeps calling tools."""
        mock_tool = AsyncMock(spec=BaseTool)
        mock_tool.name = "web_search"
        mock_tool.description = "Search"
        mock_tool.parameters_schema = {"type": "object", "properties": {}}
        mock_tool.execute.return_value = ToolResult(success=True, data="result")

        registry = ToolRegistry()
        registry.register(mock_tool)

        mock_provider.complete.return_value = LLMResponse(
            content="", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
            tool_calls=[ToolCall(id="call_n", name="web_search", arguments={"query": "test"})],
        )

        executor = Executor(provider=mock_provider, context_assembler=mock_assembler, tool_registry=registry, max_tool_turns=3)
        result = await executor.execute("conv-1", "infinite search")
        assert mock_provider.complete.call_count == 3
        assert result.response is not None

    @pytest.mark.asyncio
    async def test_tool_failure_feeds_error_back(self, mock_provider, mock_assembler):
        """When a tool fails, error is fed back to LLM."""
        mock_tool = AsyncMock(spec=BaseTool)
        mock_tool.name = "web_search"
        mock_tool.description = "Search"
        mock_tool.parameters_schema = {"type": "object", "properties": {}}
        mock_tool.execute.return_value = ToolResult(success=False, data="", error="Connection refused")

        registry = ToolRegistry()
        registry.register(mock_tool)

        mock_provider.complete.side_effect = [
            LLMResponse(content="", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="web_search", arguments={"query": "test"})]),
            LLMResponse(content="Sorry, I couldn't search right now.", model="test",
                tokens_in=20, tokens_out=10, cost_usd=0.001),
        ]

        executor = Executor(provider=mock_provider, context_assembler=mock_assembler, tool_registry=registry)
        result = await executor.execute("conv-1", "search for test")
        assert result.response.content == "Sorry, I couldn't search right now."
        # Verify error was fed back
        second_call_messages = mock_provider.complete.call_args_list[1][0][0]
        tool_result_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
        assert len(tool_result_msgs) == 1
        assert "Connection refused" in tool_result_msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_unknown_tool_feeds_error_back(self, mock_provider, mock_assembler):
        """When LLM calls an unknown tool, error is fed back."""
        registry = ToolRegistry()

        mock_provider.complete.side_effect = [
            LLMResponse(content="", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="nonexistent", arguments={})]),
            LLMResponse(content="Let me try something else.", model="test",
                tokens_in=20, tokens_out=10, cost_usd=0.001),
        ]

        executor = Executor(provider=mock_provider, context_assembler=mock_assembler, tool_registry=registry)
        result = await executor.execute("conv-1", "do something")
        assert result.response.content == "Let me try something else."

    @pytest.mark.asyncio
    async def test_abort_flag_stops_loop(self, mock_provider, mock_assembler):
        """Setting abort flag stops the loop between turns."""
        mock_tool = AsyncMock(spec=BaseTool)
        mock_tool.name = "web_search"
        mock_tool.description = "Search"
        mock_tool.parameters_schema = {"type": "object", "properties": {}}
        mock_tool.execute.return_value = ToolResult(success=True, data="result")

        registry = ToolRegistry()
        registry.register(mock_tool)

        abort = asyncio.Event()
        abort.set()

        mock_provider.complete.return_value = LLMResponse(
            content="partial", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
            tool_calls=[ToolCall(id="call_1", name="web_search", arguments={"query": "test"})],
        )

        executor = Executor(provider=mock_provider, context_assembler=mock_assembler, tool_registry=registry)
        result = await executor.execute("conv-1", "search", abort_event=abort)
        # Should not even make a call since abort is already set
        assert mock_provider.complete.call_count == 0
        # last_response is None, so we get the fallback
        assert result.response.content == "I couldn't process that request."

    @pytest.mark.asyncio
    async def test_aggregates_token_costs(self, mock_provider, mock_assembler):
        """Total tokens and cost are aggregated across all turns."""
        mock_tool = AsyncMock(spec=BaseTool)
        mock_tool.name = "web_search"
        mock_tool.description = "Search"
        mock_tool.parameters_schema = {"type": "object", "properties": {}}
        mock_tool.execute.return_value = ToolResult(success=True, data="result")

        registry = ToolRegistry()
        registry.register(mock_tool)

        mock_provider.complete.side_effect = [
            LLMResponse(content="", model="test", tokens_in=100, tokens_out=50, cost_usd=0.01,
                tool_calls=[ToolCall(id="call_1", name="web_search", arguments={"query": "test"})]),
            LLMResponse(content="Done!", model="test", tokens_in=200, tokens_out=30, cost_usd=0.02),
        ]

        executor = Executor(provider=mock_provider, context_assembler=mock_assembler, tool_registry=registry)
        result = await executor.execute("conv-1", "search")
        assert result.response.tokens_in == 300
        assert result.response.tokens_out == 80
        assert abs(result.response.cost_usd - 0.03) < 0.001


class TestAgentReAct:
    @pytest_asyncio.fixture
    async def db(self, tmp_path):
        db = Database(str(tmp_path / "test.db"), migrations_dir="migrations")
        await db.initialize()
        yield db
        await db.close()

    @pytest.mark.asyncio
    async def test_agent_no_planner(self, db):
        """Agent works without planner -- goes straight to executor."""
        provider = AsyncMock()
        provider.complete.return_value = LLMResponse(
            content="Hello!", model="test", tokens_in=10, tokens_out=5, cost_usd=0.001,
        )
        agent = Agent(db=db, provider=provider)
        response = await agent.handle_message(_make_message("Hello"))
        assert response == "Hello!"
        # Only one complete call (executor), no planner call
        assert provider.complete.call_count == 1

    @pytest.mark.asyncio
    async def test_agent_with_tool_use(self, db):
        """Agent handles tool-calling flow end-to-end."""
        mock_tool = AsyncMock(spec=BaseTool)
        mock_tool.name = "web_search"
        mock_tool.description = "Search"
        mock_tool.parameters_schema = {"type": "object", "properties": {"query": {"type": "string"}}}
        mock_tool.execute.return_value = ToolResult(success=True, data="Python 3.13 features")

        registry = ToolRegistry()
        registry.register(mock_tool)

        provider = AsyncMock()
        provider.complete.side_effect = [
            LLMResponse(content="", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="web_search", arguments={"query": "python 3.13"})]),
            LLMResponse(content="Python 3.13 has great new features!", model="test",
                tokens_in=20, tokens_out=15, cost_usd=0.002),
        ]

        agent = Agent(db=db, provider=provider, tool_registry=registry)
        response = await agent.handle_message(_make_message("What's new in Python?"))
        assert "Python 3.13" in response

    @pytest.mark.asyncio
    async def test_agent_session_serialization(self, db):
        """Concurrent messages to same session are serialized."""
        call_order = []

        async def slow_complete(messages, **kwargs):
            call_order.append("start")
            await asyncio.sleep(0.05)
            call_order.append("end")
            return LLMResponse(content="Done", model="test", tokens_in=10, tokens_out=5, cost_usd=0.001)

        provider = AsyncMock()
        provider.complete.side_effect = slow_complete

        agent = Agent(db=db, provider=provider)

        msg1 = _make_message("First")
        msg2 = _make_message("Second")

        await asyncio.gather(
            agent.handle_message(msg1),
            agent.handle_message(msg2),
        )

        # Serialized: start, end, start, end (not start, start, end, end)
        assert call_order == ["start", "end", "start", "end"]

    @pytest.mark.asyncio
    async def test_agent_budget_enforcement(self, db):
        """Budget exceeded returns canned response."""
        provider = AsyncMock()
        mock_budget = AsyncMock()
        mock_budget.check_budget = AsyncMock(return_value=AsyncMock(within_budget=False))

        agent = Agent(db=db, provider=provider, budget_tracker=mock_budget)
        response = await agent.handle_message(_make_message("hello"))
        assert "spending limit" in response
        provider.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_agent_timeout(self, db):
        """Run timeout returns timeout message."""
        async def hang_forever(messages, **kwargs):
            await asyncio.sleep(999)
            return LLMResponse(content="never", model="test", tokens_in=0, tokens_out=0, cost_usd=0.0)

        provider = AsyncMock()
        provider.complete.side_effect = hang_forever

        agent = Agent(db=db, provider=provider, run_timeout=1)  # 1 second timeout
        response = await agent.handle_message(_make_message("hello"))
        assert "time" in response.lower()
