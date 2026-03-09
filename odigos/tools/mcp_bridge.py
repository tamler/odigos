from __future__ import annotations

import logging
import os
import re
from typing import Any, Protocol

from mcp import ClientSession, types
from mcp.client.stdio import StdioServerParameters, stdio_client

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class Transport(Protocol):
    """Abstract transport for MCP server connections."""

    async def connect(self) -> tuple[Any, Any]:
        """Return (read_stream, write_stream)."""
        ...

    async def disconnect(self) -> None: ...


class StdioTransport:
    """Wraps mcp.client.stdio for subprocess-based MCP servers."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.command = command
        self.args = args or []
        self.env = env or {}
        self._cm: Any | None = None

    # Only these environment variables are passed to MCP server subprocesses.
    # This prevents leaking secrets (API keys, tokens) to third-party servers.
    SAFE_ENV_KEYS = {"PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "SHELL", "TMPDIR"}

    async def connect(self) -> tuple[Any, Any]:
        # Build a minimal environment -- only safe system vars + explicit overrides
        safe_env = {k: v for k, v in os.environ.items() if k in self.SAFE_ENV_KEYS}
        if self.env:
            expanded = {k: os.path.expandvars(v) for k, v in self.env.items()}
            safe_env.update(expanded)
        merged_env = safe_env
        params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=merged_env,
        )
        self._cm = stdio_client(params)
        read_stream, write_stream = await self._cm.__aenter__()
        return read_stream, write_stream

    async def disconnect(self) -> None:
        if self._cm:
            await self._cm.__aexit__(None, None, None)
            self._cm = None


class MCPServer:
    """Manages a connection to a single MCP server."""

    def __init__(self, name: str, transport: Transport) -> None:
        self.name = name
        self._transport = transport
        self._session: ClientSession | None = None
        self._session_cm: Any | None = None

    async def connect(self) -> None:
        read_stream, write_stream = await self._transport.connect()
        try:
            self._session_cm = ClientSession(read_stream, write_stream)
            self._session = await self._session_cm.__aenter__()
            await self._session.initialize()
        except Exception:
            # Clean up transport/session if initialization fails
            await self.disconnect()
            raise
        logger.info("MCP server '%s' connected", self.name)

    async def disconnect(self) -> None:
        try:
            if self._session_cm:
                await self._session_cm.__aexit__(None, None, None)
                self._session_cm = None
                self._session = None
        finally:
            await self._transport.disconnect()
            logger.info("MCP server '%s' disconnected", self.name)

    async def list_tools(self) -> list:
        if not self._session:
            return []
        result = await self._session.list_tools()
        return result.tools

    async def call_tool(self, tool_name: str, arguments: dict) -> ToolResult:
        if not self._session:
            return ToolResult(success=False, data="", error=f"MCP server '{self.name}' not connected")

        try:
            result = await self._session.call_tool(tool_name, arguments=arguments)
        except Exception as exc:
            return ToolResult(success=False, data="", error=f"MCP call_tool error: {exc}")

        text_parts = []
        for block in result.content:
            if getattr(block, "type", None) == "text" and hasattr(block, "text"):
                text_parts.append(block.text)
            else:
                text_parts.append(str(block))

        data = "\n".join(text_parts)

        if result.isError:
            return ToolResult(success=False, data="", error=data)
        return ToolResult(success=True, data=data)


class MCPToolBridge(BaseTool):
    """Wraps a single MCP tool as a native BaseTool."""

    def __init__(self, server: MCPServer, server_name: str, mcp_tool: Any) -> None:
        safe_server = re.sub(r"[^a-zA-Z0-9_]", "_", server_name)
        safe_tool = re.sub(r"[^a-zA-Z0-9_]", "_", mcp_tool.name)
        self.name = f"mcp_{safe_server}_{safe_tool}"
        self.description = mcp_tool.description or f"MCP tool: {mcp_tool.name}"
        self.parameters_schema = mcp_tool.inputSchema or {"type": "object", "properties": {}}
        self._server = server
        self._mcp_tool_name = mcp_tool.name

    async def execute(self, params: dict) -> ToolResult:
        try:
            return await self._server.call_tool(self._mcp_tool_name, params)
        except Exception as exc:
            return ToolResult(success=False, data="", error=str(exc))
