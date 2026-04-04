"""Tests for CLITool base class."""
from __future__ import annotations

import json
import pytest

from odigos.tools.base import BaseTool, ToolResult
from odigos.tools.cli_tool import CLITool, CLIToolError, CLIResult, _validate_cli_arg, _classify_cli_error


class FakeCLITool(CLITool):
    name = "fake_cli"
    description = "Test CLI tool"
    COMMAND = "echo"

    async def execute(self, params: dict) -> ToolResult:
        result = await self.run_cli([params.get("text", "hello")])
        return ToolResult(success=True, data=result.stdout)


class TestCLIToolError:
    def test_default_category(self):
        err = CLIToolError(1, "something failed")
        assert err.exit_code == 1
        assert err.stderr == "something failed"
        assert err.failure_category == "unknown"
        assert str(err) == "something failed"

    def test_custom_category(self):
        err = CLIToolError(2, "bad input", "input")
        assert err.failure_category == "input"


class TestCLIResult:
    def test_fields_work(self):
        result = CLIResult(exit_code=0, stdout="output", stderr="")
        assert result.exit_code == 0
        assert result.stdout == "output"
        assert result.stderr == ""


class TestValidateCLIArg:
    def test_clean_args_pass(self):
        _validate_cli_arg("hello")
        _validate_cli_arg("/usr/local/bin/tool")
        _validate_cli_arg("--flag=value")
        _validate_cli_arg("file.txt")

    def test_path_traversal_rejected(self):
        with pytest.raises(CLIToolError) as exc_info:
            _validate_cli_arg("../etc/passwd")
        assert exc_info.value.failure_category == "input"

    def test_null_byte_rejected(self):
        with pytest.raises(CLIToolError) as exc_info:
            _validate_cli_arg("file\x00name")
        assert exc_info.value.failure_category == "input"

    def test_backtick_rejected(self):
        with pytest.raises(CLIToolError) as exc_info:
            _validate_cli_arg("`whoami`")
        assert exc_info.value.failure_category == "input"

    def test_subshell_rejected(self):
        with pytest.raises(CLIToolError) as exc_info:
            _validate_cli_arg("$(rm -rf /)")
        assert exc_info.value.failure_category == "input"

    def test_newline_rejected(self):
        with pytest.raises(CLIToolError) as exc_info:
            _validate_cli_arg("arg\ninjected")
        assert exc_info.value.failure_category == "input"


class TestClassifyCLIError:
    def test_command_not_found_exit_127(self):
        result = CLIResult(exit_code=127, stdout="", stderr="command not found")
        assert _classify_cli_error(result) == "unavailable"

    def test_not_executable_exit_126(self):
        result = CLIResult(exit_code=126, stdout="", stderr="Permission denied")
        assert _classify_cli_error(result) == "unavailable"

    def test_permission_error(self):
        result = CLIResult(exit_code=1, stdout="", stderr="Permission denied: cannot access file")
        assert _classify_cli_error(result) == "permission"

    def test_timeout_in_stderr(self):
        result = CLIResult(exit_code=1, stdout="", stderr="operation timed out")
        assert _classify_cli_error(result) == "transient"

    def test_unknown(self):
        result = CLIResult(exit_code=1, stdout="", stderr="some random error")
        assert _classify_cli_error(result) == "unknown"


class TestCLIToolRunCli:
    @pytest.mark.asyncio
    async def test_run_echo_captures_output(self):
        tool = FakeCLITool()
        result = await tool.run_cli(["hello world"])
        assert result.exit_code == 0
        assert "hello world" in result.stdout

    @pytest.mark.asyncio
    async def test_timeout_raises_cli_tool_error(self):
        tool = FakeCLITool()
        tool.COMMAND = "sleep"
        with pytest.raises(CLIToolError) as exc_info:
            await tool.run_cli(["10"], timeout=0.05)
        assert exc_info.value.failure_category == "transient"
        assert "Timed out" in exc_info.value.stderr

    @pytest.mark.asyncio
    async def test_dangerous_args_rejected_before_execution(self):
        tool = FakeCLITool()
        with pytest.raises(CLIToolError) as exc_info:
            await tool.run_cli(["../etc/passwd"])
        assert exc_info.value.failure_category == "input"


class TestCLIToolRunJson:
    @pytest.mark.asyncio
    async def test_parses_json_stdout(self):
        tool = FakeCLITool()
        tool.COMMAND = "python3"
        result = await tool.run_json(["-c", 'import json; print(json.dumps({"key": "value"}))'])
        assert result["key"] == "value"

    @pytest.mark.asyncio
    async def test_raises_on_non_zero_exit(self):
        tool = FakeCLITool()
        tool.COMMAND = "python3"
        with pytest.raises(CLIToolError) as exc_info:
            await tool.run_json(["-c", "import sys; sys.exit(1)"])
        assert exc_info.value.exit_code == 1


class TestCLIToolFormatForContext:
    def test_short_output_passes_through(self):
        tool = FakeCLITool()
        result = ToolResult(success=True, data="short output")
        assert tool.format_for_context(result) == "short output"

    def test_long_output_is_distilled(self):
        tool = FakeCLITool()
        # Must be both >2000 chars AND >30 lines to trigger auto_distill truncation
        long_data = "\n".join([f"line {i}: " + "x" * 50 for i in range(100)])
        assert len(long_data) > 2000
        assert len(long_data.splitlines()) > 30
        result = ToolResult(success=True, data=long_data)
        formatted = tool.format_for_context(result)
        assert formatted != long_data
        assert "[...truncated...]" in formatted or len(formatted) < len(long_data)

    def test_inherits_from_base_tool(self):
        assert issubclass(CLITool, BaseTool)
