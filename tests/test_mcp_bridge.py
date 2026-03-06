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
