import pytest

from odigos.tools.base import BaseTool, ToolResult
from odigos.tools.registry import ToolRegistry


class FakeTool(BaseTool):
    name = "fake_tool"
    description = "A tool for testing."

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(success=True, data=f"executed with {params}")


class TestToolResult:
    def test_success_result(self):
        result = ToolResult(success=True, data="hello")
        assert result.success is True
        assert result.data == "hello"
        assert result.error is None

    def test_error_result(self):
        result = ToolResult(success=False, data="", error="something broke")
        assert result.success is False
        assert result.error == "something broke"


class TestToolRegistry:
    def test_register_and_get(self):
        registry = ToolRegistry()
        tool = FakeTool()
        registry.register(tool)

        retrieved = registry.get("fake_tool")
        assert retrieved is tool

    def test_get_unknown_returns_none(self):
        registry = ToolRegistry()
        assert registry.get("nonexistent") is None

    def test_list_tools(self):
        registry = ToolRegistry()
        registry.register(FakeTool())

        tools = registry.list()
        assert len(tools) == 1
        assert tools[0].name == "fake_tool"

    @pytest.mark.asyncio
    async def test_execute_tool(self):
        tool = FakeTool()
        result = await tool.execute({"key": "value"})
        assert result.success is True
        assert "key" in result.data
