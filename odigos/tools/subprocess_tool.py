from __future__ import annotations

import asyncio
import logging
import shlex

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_DANGEROUS_PATTERNS = ("--output", "../", "..\\")


class SubprocessTool(BaseTool):
    """Base class for tools that wrap a CLI binary with subcommand validation."""

    def __init__(
        self,
        *,
        binary_name: str,
        tool_name: str,
        description: str,
        default_timeout: int,
        allowed_subcommands: set[str],
        install_hint: str = "",
    ) -> None:
        self.name = tool_name
        self.description = description
        self.parameters_schema = {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": f"The {binary_name} subcommand and arguments to execute.",
                },
            },
            "required": ["command"],
        }
        self._binary_name = binary_name
        self._timeout = default_timeout
        self._allowed_subcommands = allowed_subcommands
        self._install_hint = install_hint

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

        if not args or args[0] not in self._allowed_subcommands:
            return ToolResult(
                success=False, data="",
                error=f"Unknown subcommand: {args[0] if args else '(empty)'}. "
                       f"Allowed: {', '.join(sorted(self._allowed_subcommands))}",
            )

        for arg in args:
            if any(pat in arg for pat in _DANGEROUS_PATTERNS):
                return ToolResult(
                    success=False, data="",
                    error=f"Blocked dangerous argument: {arg}",
                )

        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary_name, *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout,
            )
        except FileNotFoundError:
            hint = f" Install: {self._install_hint}" if self._install_hint else ""
            return ToolResult(
                success=False, data="",
                error=f"{self._binary_name} CLI not found.{hint}",
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
                error=stderr.decode() or f"{self._binary_name} exited with code {proc.returncode}",
            )

        return ToolResult(success=True, data=output)
