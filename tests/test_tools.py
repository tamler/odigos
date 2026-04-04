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


class TestJITToolInjection:
    def test_tool_definitions_without_injection(self):
        """Without inject_tools, returns only find_tools."""
        registry = ToolRegistry()
        find = FakeTool()
        find.name = "find_tools"
        find.description = "Find tools"
        registry.register(find)
        registry.register(FakeTool())  # fake_tool

        defs = registry.tool_definitions()
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "find_tools"

    def test_tool_definitions_with_injection(self):
        """With inject_tools, returns find_tools + injected tools."""
        registry = ToolRegistry()
        find = FakeTool()
        find.name = "find_tools"
        find.description = "Find tools"
        registry.register(find)

        search = FakeTool()
        search.name = "search_web"
        search.description = "Search the web"
        registry.register(search)

        code = FakeTool()
        code.name = "run_code"
        code.description = "Run code"
        registry.register(code)

        defs = registry.tool_definitions(inject_tools=["search_web", "run_code"])
        names = [d["function"]["name"] for d in defs]
        assert "find_tools" in names
        assert "search_web" in names
        assert "run_code" in names
        assert len(defs) == 3

    def test_injection_skips_unknown_tools(self):
        """Injected tool names that don't exist are silently skipped."""
        registry = ToolRegistry()
        find = FakeTool()
        find.name = "find_tools"
        registry.register(find)

        defs = registry.tool_definitions(inject_tools=["nonexistent_tool"])
        assert len(defs) == 1  # only find_tools

    def test_injection_capped_at_5(self):
        """At most 5 tools injected to limit token cost."""
        registry = ToolRegistry()
        find = FakeTool()
        find.name = "find_tools"
        registry.register(find)

        for i in range(10):
            t = FakeTool()
            t.name = f"tool_{i}"
            registry.register(t)

        defs = registry.tool_definitions(inject_tools=[f"tool_{i}" for i in range(10)])
        assert len(defs) == 6  # find_tools + 5 injected

    def test_injection_deduplicates_find_tools(self):
        """If inject_tools includes find_tools, don't duplicate it."""
        registry = ToolRegistry()
        find = FakeTool()
        find.name = "find_tools"
        registry.register(find)

        defs = registry.tool_definitions(inject_tools=["find_tools"])
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "find_tools"


class TestFormatForContext:
    def test_default_returns_data(self):
        """BaseTool.format_for_context returns result.data unchanged by default."""
        tool = FakeTool()
        result = ToolResult(success=True, data="some output")
        assert tool.format_for_context(result) == "some output"

    def test_default_returns_empty_on_empty(self):
        tool = FakeTool()
        result = ToolResult(success=True, data="")
        assert tool.format_for_context(result) == ""


class TestAutoDistill:
    def test_short_text_unchanged(self):
        from odigos.tools.base import auto_distill
        assert auto_distill("short") == "short"

    def test_long_text_truncated(self):
        from odigos.tools.base import auto_distill
        lines = [f"line {i}" for i in range(200)]
        text = "\n".join(lines)
        result = auto_distill(text)
        assert len(result) < len(text)
        assert "line 0" in result
        assert "line 199" in result


class TestToolResultForwardCompat:
    def test_status_defaults_none(self):
        result = ToolResult(success=True, data="ok")
        assert result.status is None

    def test_task_id_defaults_none(self):
        result = ToolResult(success=True, data="ok")
        assert result.task_id is None

    def test_status_can_be_set(self):
        result = ToolResult(success=True, data="ok", status="pending", task_id="abc123")
        assert result.status == "pending"
        assert result.task_id == "abc123"
