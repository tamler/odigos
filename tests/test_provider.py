import pytest
import httpx
from unittest.mock import AsyncMock, patch

from odigos.providers.base import LLMResponse, ToolCall
from odigos.providers.openrouter import OpenRouterProvider
from odigos.tools.base import BaseTool, ToolResult
from odigos.tools.goals import CreateReminderTool, CreateTodoTool, CreateGoalTool
from odigos.tools.registry import ToolRegistry


class TestToolCall:
    def test_tool_call_fields(self):
        tc = ToolCall(id="call_1", name="web_search", arguments={"query": "test"})
        assert tc.id == "call_1"
        assert tc.name == "web_search"
        assert tc.arguments == {"query": "test"}


class TestLLMResponse:
    def test_response_without_tool_calls(self):
        r = LLMResponse(
            content="Hello", model="test", tokens_in=10, tokens_out=5, cost_usd=0.0
        )
        assert r.tool_calls is None

    def test_response_with_tool_calls(self):
        tc = ToolCall(id="call_1", name="web_search", arguments={"query": "test"})
        r = LLMResponse(
            content="", model="test", tokens_in=10, tokens_out=5, cost_usd=0.0,
            tool_calls=[tc],
        )
        assert len(r.tool_calls) == 1
        assert r.tool_calls[0].name == "web_search"


class TestToolSchema:
    def test_tool_has_schema(self):
        class MyTool(BaseTool):
            name = "test_tool"
            description = "A test tool"
            parameters_schema = {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            }
            async def execute(self, params: dict) -> ToolResult:
                return ToolResult(success=True, data="ok")

        tool = MyTool()
        assert tool.parameters_schema["properties"]["query"]["type"] == "string"

    def test_tool_schema_defaults_empty(self):
        class MinimalTool(BaseTool):
            name = "minimal"
            description = "No schema"
            async def execute(self, params: dict) -> ToolResult:
                return ToolResult(success=True, data="ok")

        tool = MinimalTool()
        assert tool.parameters_schema == {"type": "object", "properties": {}}


class TestToolRegistry:
    def test_tool_definitions(self):
        class FakeTool(BaseTool):
            name = "web_search"
            description = "Search the web"
            parameters_schema = {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query"}},
                "required": ["query"],
            }
            async def execute(self, params: dict) -> ToolResult:
                return ToolResult(success=True, data="ok")

        registry = ToolRegistry()
        registry.register(FakeTool())
        defs = registry.tool_definitions()
        assert len(defs) == 1
        assert defs[0]["type"] == "function"
        assert defs[0]["function"]["name"] == "web_search"
        assert defs[0]["function"]["description"] == "Search the web"
        assert defs[0]["function"]["parameters"]["properties"]["query"]["type"] == "string"

    def test_tool_definitions_empty(self):
        registry = ToolRegistry()
        assert registry.tool_definitions() == []


class TestGoalTools:
    @pytest.mark.asyncio
    async def test_create_reminder_tool(self):
        mock_store = AsyncMock()
        mock_store.create_reminder = AsyncMock(return_value="rem-12345678")
        tool = CreateReminderTool(goal_store=mock_store)
        result = await tool.execute({"description": "call dentist", "due_seconds": 7200})
        assert result.success
        assert "dentist" in result.data.lower() or "reminder" in result.data.lower()
        mock_store.create_reminder.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_todo_tool(self):
        mock_store = AsyncMock()
        mock_store.create_todo = AsyncMock(return_value="todo-12345678")
        tool = CreateTodoTool(goal_store=mock_store)
        result = await tool.execute({"description": "research flights"})
        assert result.success
        mock_store.create_todo.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_goal_tool(self):
        mock_store = AsyncMock()
        mock_store.create_goal = AsyncMock(return_value="goal-12345678")
        tool = CreateGoalTool(goal_store=mock_store)
        result = await tool.execute({"description": "learn Spanish"})
        assert result.success
        mock_store.create_goal.assert_called_once()

    def test_tool_schemas_have_description(self):
        mock_store = AsyncMock()
        for ToolClass in [CreateReminderTool, CreateTodoTool, CreateGoalTool]:
            tool = ToolClass(goal_store=mock_store)
            assert "description" in tool.parameters_schema["properties"]


class TestOpenRouterToolCalling:
    @pytest.mark.asyncio
    async def test_sends_tools_in_payload(self):
        tools = [{"type": "function", "function": {"name": "web_search", "description": "Search", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}}]
        mock_response = httpx.Response(200, json={
            "choices": [{"message": {"content": "Hello", "tool_calls": None}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "model": "test/model", "id": "gen-123",
        })
        provider = OpenRouterProvider(api_key="test-key", default_model="test/model", fallback_model="test/fallback")
        with patch.object(provider._client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            await provider.complete([{"role": "user", "content": "Hello"}], tools=tools)
            call_payload = mock_post.call_args.kwargs["json"]
            assert "tools" in call_payload
            assert call_payload["tools"][0]["function"]["name"] == "web_search"
        await provider.close()

    @pytest.mark.asyncio
    async def test_parses_tool_calls_from_response(self):
        mock_response = httpx.Response(200, json={
            "choices": [{"message": {"content": None, "tool_calls": [{"id": "call_abc", "type": "function", "function": {"name": "web_search", "arguments": '{"query": "python docs"}'}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 15},
            "model": "test/model", "id": "gen-456",
        })
        provider = OpenRouterProvider(api_key="test-key", default_model="test/model", fallback_model="test/fallback")
        with patch.object(provider._client, "post", new_callable=AsyncMock, return_value=mock_response):
            result = await provider.complete(
                [{"role": "user", "content": "Search"}],
                tools=[{"type": "function", "function": {"name": "web_search", "description": "test", "parameters": {}}}],
            )
            assert result.tool_calls is not None
            assert len(result.tool_calls) == 1
            assert result.tool_calls[0].name == "web_search"
            assert result.tool_calls[0].arguments == {"query": "python docs"}
        await provider.close()

    @pytest.mark.asyncio
    async def test_no_tool_calls_returns_none(self):
        mock_response = httpx.Response(200, json={
            "choices": [{"message": {"content": "Just text"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "model": "test/model", "id": "gen-789",
        })
        provider = OpenRouterProvider(api_key="test-key", default_model="test/model", fallback_model="test/fallback")
        with patch.object(provider._client, "post", new_callable=AsyncMock, return_value=mock_response):
            result = await provider.complete([{"role": "user", "content": "Hello"}])
            assert result.tool_calls is None
        await provider.close()
