from __future__ import annotations

import asyncio
import logging
import shlex

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 120


class BrowserTool(BaseTool):
    """Execute browser automation commands via the agent-browser CLI."""

    name = "run_browser"
    description = (
        "Control a headless browser to interact with web pages. Supports navigating, "
        "clicking, typing, scrolling, taking screenshots, and extracting page content. "
        "Pass the agent-browser subcommand and arguments. "
        "Example: navigate --url 'https://example.com'"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The agent-browser subcommand and arguments to execute.",
            },
        },
        "required": ["command"],
    }

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout

    async def execute(self, params: dict) -> ToolResult:
        command = params.get("command", "").strip()
        if not command:
            return ToolResult(
                success=False, data="",
                error="Missing required parameter: command",
            )

        try:
            args = shlex.split(command)
        except ValueError as exc:
            return ToolResult(
                success=False, data="",
                error=f"Invalid command syntax: {exc}",
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                "agent-browser", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout,
            )
        except FileNotFoundError:
            return ToolResult(
                success=False, data="",
                error="agent-browser CLI not found. Install: npm install -g @anthropic-ai/agent-browser",
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult(
                success=False, data="",
                error=f"Command timed out after {self._timeout}s",
            )

        output = stdout.decode()
        if proc.returncode != 0:
            return ToolResult(
                success=False, data=output,
                error=stderr.decode() or f"agent-browser exited with code {proc.returncode}",
            )

        return ToolResult(success=True, data=output)
