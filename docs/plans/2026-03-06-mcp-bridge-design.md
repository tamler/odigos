# MCP Bridge Design

## Goal

Connect external MCP (Model Context Protocol) servers as native Odigos tools, so the LLM can call third-party integrations (GitHub, Notion, Slack, etc.) through the same `BaseTool` interface as built-in tools.

## Architecture

Single new file: `odigos/tools/mcp_bridge.py` containing all MCP bridge code.

Components:

- **Transport (Protocol)** — async interface yielding `(read_stream, write_stream)`. Structural typing, no ABC.
- **StdioTransport** — wraps `mcp.client.stdio.stdio_client`. Manages subprocess lifecycle.
- **MCPServer** — owns a `ClientSession` per MCP server. Connects, discovers tools, proxies `call_tool`.
- **MCPToolBridge(BaseTool)** — one instance per MCP tool. Registered in `ToolRegistry`. Delegates `execute()` to its parent `MCPServer`.

Data flow:

1. Startup: read config → create `StdioTransport` per server → `MCPServer.connect()` → `list_tools()` → create `MCPToolBridge` per tool → `ToolRegistry.register()`
2. Runtime: LLM calls `mcp_github_create_issue` → ToolRegistry finds MCPToolBridge → `bridge.execute(params)` → `server.call_tool("create_issue", params)` → `ClientSession.call_tool()` → `ToolResult`
3. Shutdown: `MCPServer.disconnect()` for each server

Tool naming: `mcp_{server_name}_{tool_name}` — prevents collisions with native tools.

## Transport Abstraction

```python
class Transport(Protocol):
    async def connect(self) -> tuple[ReadStream, WriteStream]: ...
    async def disconnect(self) -> None: ...
```

`StdioTransport` satisfies this protocol. Adding SSE later means writing a new class that also satisfies `Transport` — no changes to `MCPServer` or `MCPToolBridge`.

## Configuration

New Pydantic models in `config.py`:

```python
class MCPServerConfig(BaseModel):
    command: str
    args: list[str] = []
    env: dict[str, str] = {}

class MCPConfig(BaseModel):
    servers: dict[str, MCPServerConfig] = {}
```

Added to `Settings` as `mcp: MCPConfig = MCPConfig()`.

Config in `config.yaml`:

```yaml
mcp:
  servers:
    github:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_TOKEN: "${GITHUB_TOKEN}"
```

Environment variable expansion in `env` values at transport creation time.

## Lifecycle

Startup in `main.py` lifespan — after tool registry creation, before agent construction:

- Iterate `settings.mcp.servers`
- Create `StdioTransport` + `MCPServer` per entry
- `await server.connect()` — fails gracefully (log error, skip server)
- `list_tools()` → create and register `MCPToolBridge` instances
- Store server references for shutdown

Shutdown — iterate servers, `await server.disconnect()`. Each wrapped in try/except.

## Error Handling

- Server fails to start: log error, skip that server, continue with others
- `call_tool` fails at runtime: return `ToolResult(success=False, error=...)`. LLM sees the error and can retry or move on.
- No auto-reconnect in Phase 2.

## Testing

- Unit tests for `MCPToolBridge.execute()` with mock `MCPServer`
- Unit tests for `MCPServer.call_tool()` with mock `ClientSession`
- Config tests for `MCPConfig` parsing and env var expansion
- Integration test (optional): spin up simple MCP server subprocess, round-trip a tool call

## Dependencies

- `mcp` Python package (official MCP SDK, v1.25.0+)
