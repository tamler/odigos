import pytest
from odigos.providers.base import LLMResponse, ToolCall
from odigos.tools.base import BaseTool, ToolResult
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
