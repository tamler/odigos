from __future__ import annotations

import asyncio
import logging
import shlex

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30

_GWS_ALLOWED_SUBCOMMANDS = {
    "gmail", "calendar", "drive", "sheets", "docs", "slides",
    "forms", "chat", "admin", "tasks", "people", "vault",
}

_DANGEROUS_PATTERNS = ("--output", "../", "..\\")


class GWSTool(BaseTool):
    """Execute Google Workspace commands via the gws CLI."""

    name = "run_gws"
    description = (
        "Run a Google Workspace CLI command. Supports Gmail, Calendar, Drive, "
        "Sheets, and all other Workspace APIs. Pass the gws subcommand and arguments. "
        "Example: drive files list --params '{\"pageSize\": 5}'"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The gws subcommand and arguments to execute.",
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

        if not args or args[0] not in _GWS_ALLOWED_SUBCOMMANDS:
            return ToolResult(
                success=False, data="",
                error=f"Unknown subcommand: {args[0] if args else '(empty)'}. "
                       f"Allowed: {', '.join(sorted(_GWS_ALLOWED_SUBCOMMANDS))}",
            )

        for arg in args:
            if any(pat in arg for pat in _DANGEROUS_PATTERNS):
                return ToolResult(
                    success=False, data="",
                    error=f"Blocked dangerous argument: {arg}",
                )

        try:
            proc = await asyncio.create_subprocess_exec(
                "gws", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout,
            )
        except FileNotFoundError:
            return ToolResult(
                success=False, data="",
                error="gws CLI not found. Install: npm install -g @googleworkspace/cli",
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
                error=stderr.decode() or f"gws exited with code {proc.returncode}",
            )

        return ToolResult(success=True, data=output)
