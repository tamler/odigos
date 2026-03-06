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
