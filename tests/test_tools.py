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


class TestAlwaysLoadedTools:
    def test_tool_definitions_returns_only_find_tools(self):
        """tool_definitions returns only find_tools."""
        registry = ToolRegistry()
        for name in ["find_tools", "search_web", "generate_music", "run_code"]:
            t = FakeTool()
            t.name = name
            t.description = f"{name} description"
            registry.register(t)

        defs = registry.tool_definitions()
        names = {d["function"]["name"] for d in defs}
        assert names == {"find_tools"}
        assert "search_web" not in names
        assert "generate_music" not in names

    def test_tool_definitions_skips_missing_always_loaded(self):
        """If an always-loaded tool is not registered, it is silently skipped."""
        registry = ToolRegistry()
        find = FakeTool()
        find.name = "find_tools"
        find.description = "Find tools"
        registry.register(find)

        defs = registry.tool_definitions()
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "find_tools"

    def test_tool_definitions_empty_registry(self):
        """Empty registry returns no definitions."""
        registry = ToolRegistry()
        defs = registry.tool_definitions()
        assert defs == []

    def test_non_always_loaded_tools_excluded(self):
        """Tools not in the always-loaded set are not returned."""
        registry = ToolRegistry()
        for name in ["generate_image", "send_email", "check_calendar"]:
            t = FakeTool()
            t.name = name
            registry.register(t)

        defs = registry.tool_definitions()
        assert defs == []


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
