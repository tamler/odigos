# MCP Bridge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect external MCP servers as native Odigos tools via a transport-abstracted bridge.

**Architecture:** A thin `Transport` protocol abstracts stdio (now) vs SSE (later). `MCPServer` owns a `ClientSession` per configured server. `MCPToolBridge(BaseTool)` wraps each discovered MCP tool and registers it in `ToolRegistry`. Config via Pydantic models in `config.py`.

**Tech Stack:** Python 3.12, `mcp` SDK (v1.25.0+), Pydantic, pytest

---

### Task 1: Add MCP configuration models

**Files:**
- Modify: `odigos/config.py:57-93`
- Test: `tests/test_config.py`

**Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
class TestMCPConfig:
    def test_mcp_config_defaults(self):
        """MCPConfig defaults to empty servers dict."""
        from odigos.config import MCPConfig
        cfg = MCPConfig()
        assert cfg.servers == {}

    def test_mcp_server_config_parsing(self):
        """MCPServerConfig parses command, args, env."""
        from odigos.config import MCPServerConfig
        cfg = MCPServerConfig(command="npx", args=["-y", "server"], env={"TOKEN": "abc"})
        assert cfg.command == "npx"
        assert cfg.args == ["-y", "server"]
        assert cfg.env == {"TOKEN": "abc"}

    def test_mcp_server_config_defaults(self):
        """MCPServerConfig has sensible defaults for args and env."""
        from odigos.config import MCPServerConfig
        cfg = MCPServerConfig(command="python")
        assert cfg.args == []
        assert cfg.env == {}

    def test_settings_includes_mcp(self):
        """Settings has mcp field with MCPConfig default."""
        from odigos.config import Settings
        fields = Settings.model_fields
        assert "mcp" in fields
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::TestMCPConfig -v`
Expected: FAIL — `MCPConfig` and `MCPServerConfig` do not exist yet.

**Step 3: Write minimal implementation**

In `odigos/config.py`, add before the `Settings` class:

```python
class MCPServerConfig(BaseModel):
    command: str
    args: list[str] = []
    env: dict[str, str] = {}


class MCPConfig(BaseModel):
    servers: dict[str, MCPServerConfig] = {}
```

Add to `Settings`:

```python
    mcp: MCPConfig = MCPConfig()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py::TestMCPConfig -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/config.py tests/test_config.py
git commit -m "feat: add MCP configuration models to config.py"
```

---

### Task 2: Create mcp_bridge.py — Transport, MCPServer, MCPToolBridge

**Files:**
- Create: `odigos/tools/mcp_bridge.py`
- Test: `tests/test_mcp_bridge.py`

**Step 1: Write the failing tests**

Create `tests/test_mcp_bridge.py`:

```python
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odigos.tools.base import ToolResult


class TestMCPToolBridge:
    async def test_execute_delegates_to_server(self):
        """MCPToolBridge.execute() delegates to MCPServer.call_tool()."""
        from odigos.tools.mcp_bridge import MCPToolBridge, MCPServer

        server = AsyncMock(spec=MCPServer)
        server.call_tool = AsyncMock(return_value=ToolResult(success=True, data="result"))

        # Create a mock MCP tool descriptor
        mcp_tool = MagicMock()
        mcp_tool.name = "create_issue"
        mcp_tool.description = "Create a GitHub issue"
        mcp_tool.inputSchema = {
            "type": "object",
            "properties": {"title": {"type": "string"}},
        }

        bridge = MCPToolBridge(server=server, server_name="github", mcp_tool=mcp_tool)

        assert bridge.name == "mcp_github_create_issue"
        assert bridge.description == "Create a GitHub issue"
        assert bridge.parameters_schema == mcp_tool.inputSchema

        result = await bridge.execute({"title": "Bug report"})
        server.call_tool.assert_called_once_with("create_issue", {"title": "Bug report"})
        assert result.success is True
        assert result.data == "result"

    async def test_execute_returns_error_on_failure(self):
        """MCPToolBridge returns error ToolResult when server.call_tool fails."""
        from odigos.tools.mcp_bridge import MCPToolBridge, MCPServer

        server = AsyncMock(spec=MCPServer)
        server.call_tool = AsyncMock(side_effect=Exception("Connection lost"))

        mcp_tool = MagicMock()
        mcp_tool.name = "list_repos"
        mcp_tool.description = "List repositories"
        mcp_tool.inputSchema = {"type": "object", "properties": {}}

        bridge = MCPToolBridge(server=server, server_name="gh", mcp_tool=mcp_tool)
        result = await bridge.execute({})

        assert result.success is False
        assert "Connection lost" in result.error


class TestMCPServer:
    async def test_call_tool_returns_text_content(self):
        """MCPServer.call_tool() extracts text from MCP TextContent result."""
        from odigos.tools.mcp_bridge import MCPServer

        mock_transport = AsyncMock()

        server = MCPServer(name="test", transport=mock_transport)

        # Mock the session
        mock_session = AsyncMock()
        mock_text_content = MagicMock()
        mock_text_content.type = "text"
        mock_text_content.text = "Tool output here"
        mock_result = MagicMock()
        mock_result.content = [mock_text_content]
        mock_result.isError = False
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        server._session = mock_session

        result = await server.call_tool("my_tool", {"arg": "val"})
        assert result.success is True
        assert result.data == "Tool output here"
        mock_session.call_tool.assert_called_once_with("my_tool", arguments={"arg": "val"})

    async def test_call_tool_handles_error_result(self):
        """MCPServer.call_tool() returns error ToolResult when MCP result.isError is True."""
        from odigos.tools.mcp_bridge import MCPServer

        mock_transport = AsyncMock()
        server = MCPServer(name="test", transport=mock_transport)

        mock_session = AsyncMock()
        mock_text_content = MagicMock()
        mock_text_content.type = "text"
        mock_text_content.text = "Something went wrong"
        mock_result = MagicMock()
        mock_result.content = [mock_text_content]
        mock_result.isError = True
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        server._session = mock_session

        result = await server.call_tool("failing_tool", {})
        assert result.success is False
        assert "Something went wrong" in result.error

    async def test_call_tool_no_session_raises(self):
        """MCPServer.call_tool() returns error if not connected."""
        from odigos.tools.mcp_bridge import MCPServer

        mock_transport = AsyncMock()
        server = MCPServer(name="test", transport=mock_transport)

        result = await server.call_tool("any_tool", {})
        assert result.success is False
        assert "not connected" in result.error.lower()


class TestStdioTransport:
    def test_stores_server_params(self):
        """StdioTransport stores command, args, env."""
        from odigos.tools.mcp_bridge import StdioTransport

        transport = StdioTransport(command="npx", args=["-y", "server"], env={"KEY": "val"})
        assert transport.command == "npx"
        assert transport.args == ["-y", "server"]
        assert transport.env == {"KEY": "val"}
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_bridge.py -v`
Expected: FAIL — `mcp_bridge` module does not exist.

**Step 3: Write the implementation**

Create `odigos/tools/mcp_bridge.py`:

```python
from __future__ import annotations

import logging
import os
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

    async def connect(self) -> tuple[Any, Any]:
        expanded_env = {k: os.path.expandvars(v) for k, v in self.env.items()}
        params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=expanded_env or None,
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
        self._session_cm = ClientSession(read_stream, write_stream)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        logger.info("MCP server '%s' connected", self.name)

    async def disconnect(self) -> None:
        if self._session_cm:
            await self._session_cm.__aexit__(None, None, None)
            self._session_cm = None
            self._session = None
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
            if isinstance(block, types.TextContent):
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
        self.name = f"mcp_{server_name}_{mcp_tool.name}"
        self.description = mcp_tool.description or f"MCP tool: {mcp_tool.name}"
        self.parameters_schema = mcp_tool.inputSchema or {"type": "object", "properties": {}}
        self._server = server
        self._mcp_tool_name = mcp_tool.name

    async def execute(self, params: dict) -> ToolResult:
        try:
            return await self._server.call_tool(self._mcp_tool_name, params)
        except Exception as exc:
            return ToolResult(success=False, data="", error=str(exc))
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_bridge.py -v`
Expected: PASS (all 6 tests)

**Step 5: Commit**

```bash
git add odigos/tools/mcp_bridge.py tests/test_mcp_bridge.py
git commit -m "feat: add MCP bridge with transport abstraction"
```

---

### Task 3: Wire MCP bridge into main.py lifespan

**Files:**
- Modify: `odigos/main.py:43-249`
- Modify: `pyproject.toml:6-17` (add `mcp` dependency)

**Step 1: Add `mcp` to dependencies**

In `pyproject.toml`, add to the `dependencies` list:

```
    "mcp>=1.25.0",
```

**Step 2: Add MCP startup to main.py lifespan**

Add a module-level global:

```python
_mcp_servers: list = []
```

Add to the `global` statement at the top of `lifespan`:

```python
global _db, _provider, _embedder, _telegram, _searxng, _scraper, _router, _heartbeat, _mcp_servers
```

After the skill activation tool registration block (line ~174) and before the agent creation, add:

```python
    # Connect MCP servers and register bridged tools
    if settings.mcp.servers:
        from odigos.tools.mcp_bridge import MCPServer, MCPToolBridge, StdioTransport

        for server_name, server_cfg in settings.mcp.servers.items():
            transport = StdioTransport(
                command=server_cfg.command,
                args=server_cfg.args,
                env=server_cfg.env,
            )
            server = MCPServer(name=server_name, transport=transport)
            try:
                await server.connect()
                mcp_tools = await server.list_tools()
                for mcp_tool in mcp_tools:
                    bridge = MCPToolBridge(
                        server=server, server_name=server_name, mcp_tool=mcp_tool
                    )
                    tool_registry.register(bridge)
                    logger.info("Registered MCP tool: %s", bridge.name)
                _mcp_servers.append(server)
                logger.info(
                    "MCP server '%s' connected (%d tools)",
                    server_name,
                    len(mcp_tools),
                )
            except Exception:
                logger.exception("Failed to connect MCP server: %s", server_name)
```

Add to shutdown block, before the scraper cleanup:

```python
    for server in _mcp_servers:
        try:
            await server.disconnect()
        except Exception:
            logger.exception("Error disconnecting MCP server: %s", server.name)
    _mcp_servers.clear()
```

**Step 3: Run the full test suite**

Run: `pytest tests/ -v`
Expected: All existing tests still pass (MCP code is gated behind `settings.mcp.servers` which defaults to empty).

**Step 4: Commit**

```bash
git add pyproject.toml odigos/main.py
git commit -m "feat: wire MCP bridge into main.py lifespan"
```

---

### Task 4: Integration test with mock MCP server

**Files:**
- Modify: `tests/test_mcp_bridge.py`

**Step 1: Write the integration test**

Add to `tests/test_mcp_bridge.py`:

```python
class TestMCPBridgeIntegration:
    async def test_full_bridge_lifecycle_with_mocks(self):
        """Full lifecycle: connect, list_tools, bridge, execute, disconnect."""
        from unittest.mock import AsyncMock, MagicMock
        from odigos.tools.mcp_bridge import MCPServer, MCPToolBridge, StdioTransport

        # Mock transport
        mock_transport = AsyncMock()
        mock_read = MagicMock()
        mock_write = MagicMock()
        mock_transport.connect = AsyncMock(return_value=(mock_read, mock_write))
        mock_transport.disconnect = AsyncMock()

        server = MCPServer(name="test_server", transport=mock_transport)

        # Mock the ClientSession at the module level
        mock_session = AsyncMock()

        # Mock list_tools response
        mock_tool_info = MagicMock()
        mock_tool_info.name = "echo"
        mock_tool_info.description = "Echo input back"
        mock_tool_info.inputSchema = {
            "type": "object",
            "properties": {"message": {"type": "string"}},
        }
        mock_list_result = MagicMock()
        mock_list_result.tools = [mock_tool_info]
        mock_session.list_tools = AsyncMock(return_value=mock_list_result)
        mock_session.initialize = AsyncMock()

        # Mock call_tool response
        mock_text = MagicMock()
        mock_text.type = "text"
        mock_text.text = "echoed: hello"
        mock_call_result = MagicMock()
        mock_call_result.content = [mock_text]
        mock_call_result.isError = False
        mock_session.call_tool = AsyncMock(return_value=mock_call_result)

        # Inject mock session
        server._session = mock_session

        # List tools and create bridges
        tools = await server.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "echo"

        bridge = MCPToolBridge(server=server, server_name="test_server", mcp_tool=tools[0])
        assert bridge.name == "mcp_test_server_echo"

        # Execute through the bridge
        result = await bridge.execute({"message": "hello"})
        assert result.success is True
        assert result.data == "echoed: hello"

        # Disconnect
        server._session_cm = None
        server._session = None
        await mock_transport.disconnect()
        mock_transport.disconnect.assert_called_once()
```

**Step 2: Run tests**

Run: `pytest tests/test_mcp_bridge.py -v`
Expected: All tests PASS

**Step 3: Run full suite**

Run: `pytest tests/ -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add tests/test_mcp_bridge.py
git commit -m "test: add MCP bridge integration test"
```
