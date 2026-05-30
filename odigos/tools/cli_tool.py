"""Base class for tools that execute CLI commands in a subprocess."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass

from odigos.tools.base import BaseTool, ToolResult, auto_distill

logger = logging.getLogger(__name__)


class CLIToolError(Exception):
    """Raised when a CLI tool execution fails."""

    def __init__(self, exit_code: int, stderr: str, failure_category: str = "unknown"):
        self.exit_code = exit_code
        self.stderr = stderr
        self.failure_category = failure_category
        super().__init__(stderr)


@dataclass
class CLIResult:
    """Output from a CLI subprocess execution."""

    exit_code: int
    stdout: str
    stderr: str


class CLITool(BaseTool):
    """Base class for tools that execute CLI commands in a subprocess."""

    COMMAND: str = ""
    SANDBOX: str = "subprocess"
    SKILL_FILE: str = ""

    def __init__(
        self,
        working_dir: str = "",
        timeout: float = 60.0,
        allowed_paths: list[str] | None = None,
    ):
        self._working_dir = working_dir
        self._timeout = timeout
        self._allowed_paths = allowed_paths or []

    async def run_cli(
        self,
        args: list[str],
        stdin: str | None = None,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
        reject_option_args: bool = False,
    ) -> CLIResult:
        """Execute a CLI command in a subprocess."""
        timeout = timeout or self._timeout
        cmd = [self.COMMAND] + args

        for arg in args:
            _validate_cli_arg(arg, reject_option_args=reject_option_args)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if stdin else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._working_dir or None,
            env={**os.environ, **(env or {})},
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(stdin.encode() if stdin else None),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise CLIToolError(-1, f"Timed out after {timeout}s", "transient")

        return CLIResult(
            exit_code=proc.returncode,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
        )

    async def run_json(self, args: list[str], **kwargs) -> dict:
        """Run a CLI command and parse JSON output."""
        if "--output" not in args and "-o" not in args:
            args = args + ["--output", "json"]
        result = await self.run_cli(args, **kwargs)
        if result.exit_code != 0:
            raise CLIToolError(result.exit_code, result.stderr, _classify_cli_error(result))
        return json.loads(result.stdout)

    def format_for_context(self, result: ToolResult) -> str:
        """CLI output is inherently verbose -- auto-distill by default."""
        if len(result.data) > 2000:
            return auto_distill(result.data)
        return result.data


def _validate_cli_arg(arg: str, *, reject_option_args: bool = False) -> None:
    """Reject dangerous CLI arguments. Agents hallucinate."""
    if ".." in arg and ("/" in arg or "\\" in arg):
        raise CLIToolError(-1, f"Path traversal rejected: {arg}", "input")
    if any(c in arg for c in ("\x00", "\r", "\n", "`", "$(")):
        raise CLIToolError(-1, f"Dangerous characters in argument: {arg!r}", "input")
    if reject_option_args and (arg.startswith("-") or arg.startswith("/")):
        raise CLIToolError(-1, f"Option-style/absolute argument rejected: {arg!r}", "input")


def _classify_cli_error(result: CLIResult) -> str:
    """Map CLI exit codes and stderr to failure categories."""
    if result.exit_code in (126, 127):
        return "unavailable"
    if result.exit_code == 1 and "permission" in result.stderr.lower():
        return "permission"
    if "timeout" in result.stderr.lower() or "timed out" in result.stderr.lower():
        return "transient"
    return "unknown"
