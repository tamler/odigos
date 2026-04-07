# Capability Audit Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add file read/write tool, conversation export, remove dead code, create AgentService facade, and convert all opt-in capabilities (including Telegram) to plugins.

**Architecture:** AgentService facade wraps Agent, GoalStore, BudgetTracker, and ApprovalGate behind a single interface. PluginContext gets two-phase loading: tool phase (before Agent) and channel phase (after Agent, with AgentService). All opt-in capabilities become plugins. FileTool with configurable sandboxed paths. Export endpoint on conversations API.

**Tech Stack:** FastAPI, aiosqlite, existing plugin system, existing tool/channel base classes

**Design doc:** `docs/plans/2026-03-12-capability-audit-design.md`

---

### Task 1: Add FileAccessConfig to settings

**Files:**
- Modify: `odigos/config.py` (add FileAccessConfig class + field on Settings)

**Step 1: Write the config class**

In `odigos/config.py`, add after `SandboxConfig`:

```python
class FileAccessConfig(BaseModel):
    allowed_paths: list[str] = ["data/files"]
```

Add to `Settings` class:

```python
    file_access: FileAccessConfig = FileAccessConfig()
```

**Step 2: Verify**

Run: `uv run python -c "from odigos.config import Settings; s = Settings(llm_api_key='test'); print(s.file_access.allowed_paths)"`
Expected: `['data/files']`

**Step 3: Commit**

```bash
git add odigos/config.py
git commit -m "feat: add file_access config with allowed_paths"
```

---

### Task 2: Create FileTool with sandboxed path validation

**Files:**
- Create: `odigos/tools/file.py`
- Create: `tests/test_file_tool.py`

**Step 1: Write the failing tests**

Create `tests/test_file_tool.py`:

```python
import os
import pytest
from odigos.tools.file import FileTool


@pytest.fixture
def file_tool(tmp_path):
    return FileTool(allowed_paths=[str(tmp_path)])


class TestFileTool:
    async def test_write_and_read(self, file_tool, tmp_path):
        result = await file_tool.execute({
            "operation": "write",
            "path": str(tmp_path / "test.txt"),
            "content": "hello world",
        })
        assert result.success
        result = await file_tool.execute({
            "operation": "read",
            "path": str(tmp_path / "test.txt"),
        })
        assert result.success
        assert "hello world" in result.data

    async def test_read_nonexistent(self, file_tool, tmp_path):
        result = await file_tool.execute({
            "operation": "read",
            "path": str(tmp_path / "nope.txt"),
        })
        assert not result.success

    async def test_path_outside_sandbox_rejected(self, file_tool):
        result = await file_tool.execute({
            "operation": "read",
            "path": "/etc/passwd",
        })
        assert not result.success
        assert "not within allowed" in result.error.lower()

    async def test_symlink_escape_blocked(self, file_tool, tmp_path):
        link = tmp_path / "sneaky"
        link.symlink_to("/etc")
        result = await file_tool.execute({
            "operation": "read",
            "path": str(link / "passwd"),
        })
        assert not result.success

    async def test_list_directory(self, file_tool, tmp_path):
        (tmp_path / "a.txt").write_text("aaa")
        (tmp_path / "b.txt").write_text("bbb")
        result = await file_tool.execute({
            "operation": "list",
            "path": str(tmp_path),
        })
        assert result.success
        assert "a.txt" in result.data
        assert "b.txt" in result.data

    async def test_write_creates_parent_dirs(self, file_tool, tmp_path):
        result = await file_tool.execute({
            "operation": "write",
            "path": str(tmp_path / "sub" / "dir" / "file.txt"),
            "content": "nested",
        })
        assert result.success
        assert (tmp_path / "sub" / "dir" / "file.txt").read_text() == "nested"

    async def test_read_binary_rejected(self, file_tool, tmp_path):
        bin_file = tmp_path / "binary.bin"
        bin_file.write_bytes(b"\x00\x01\x02\xff\xfe")
        result = await file_tool.execute({
            "operation": "read",
            "path": str(bin_file),
        })
        assert not result.success

    async def test_missing_operation(self, file_tool):
        result = await file_tool.execute({"path": "/tmp/x"})
        assert not result.success
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_file_tool.py -v`
Expected: FAIL — module not found

**Step 3: Implement FileTool**

Create `odigos/tools/file.py`:

```python
from __future__ import annotations

import logging
from pathlib import Path

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

MAX_READ_SIZE = 500_000  # 500KB


class FileTool(BaseTool):
    """Read, write, and list files within configured allowed paths."""

    name = "file"
    description = (
        "Read, write, or list files. Operations: read (returns text content), "
        "write (creates or overwrites a file), list (shows directory contents). "
        "Only works within allowed directories."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["read", "write", "list"],
                "description": "The file operation to perform",
            },
            "path": {
                "type": "string",
                "description": "File or directory path",
            },
            "content": {
                "type": "string",
                "description": "Content to write (only for write operation)",
            },
        },
        "required": ["operation", "path"],
    }

    def __init__(self, allowed_paths: list[str] | None = None) -> None:
        self._allowed = [
            Path(p).expanduser().resolve() for p in (allowed_paths or ["data/files"])
        ]

    def _validate_path(self, path_str: str) -> tuple[Path, str | None]:
        """Resolve path and check it's within allowed directories."""
        try:
            resolved = Path(path_str).expanduser().resolve()
        except (ValueError, OSError) as e:
            return Path(), f"Invalid path: {e}"

        for allowed in self._allowed:
            try:
                resolved.relative_to(allowed)
                return resolved, None
            except ValueError:
                continue

        return resolved, f"Path not within allowed directories: {self._allowed}"

    async def execute(self, params: dict) -> ToolResult:
        operation = params.get("operation", "").strip()
        path_str = params.get("path", "").strip()

        if not operation:
            return ToolResult(success=False, data="", error="Missing required parameter: operation")
        if not path_str:
            return ToolResult(success=False, data="", error="Missing required parameter: path")

        resolved, err = self._validate_path(path_str)
        if err:
            return ToolResult(success=False, data="", error=err)

        if operation == "read":
            return await self._read(resolved)
        elif operation == "write":
            content = params.get("content", "")
            return await self._write(resolved, content)
        elif operation == "list":
            return await self._list(resolved)
        else:
            return ToolResult(success=False, data="", error=f"Unknown operation: {operation}")

    async def _read(self, path: Path) -> ToolResult:
        if not path.exists():
            return ToolResult(success=False, data="", error=f"File not found: {path}")
        if not path.is_file():
            return ToolResult(success=False, data="", error=f"Not a file: {path}")
        try:
            data = path.read_bytes()
            if b"\x00" in data[:8192]:
                return ToolResult(success=False, data="", error="Binary file — cannot read as text")
            if len(data) > MAX_READ_SIZE:
                text = data[:MAX_READ_SIZE].decode("utf-8", errors="replace")
                return ToolResult(success=True, data=text + "\n\n[truncated]")
            return ToolResult(success=True, data=data.decode("utf-8", errors="replace"))
        except Exception as e:
            return ToolResult(success=False, data="", error=str(e))

    async def _write(self, path: Path, content: str) -> ToolResult:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _, err = self._validate_path(str(path.parent.resolve()))
            if err:
                return ToolResult(success=False, data="", error=err)
            path.write_text(content)
            return ToolResult(success=True, data=f"Written {len(content)} chars to {path}")
        except Exception as e:
            return ToolResult(success=False, data="", error=str(e))

    async def _list(self, path: Path) -> ToolResult:
        if not path.exists():
            return ToolResult(success=False, data="", error=f"Directory not found: {path}")
        if not path.is_dir():
            return ToolResult(success=False, data="", error=f"Not a directory: {path}")
        lines = []
        for entry in sorted(path.iterdir()):
            if entry.is_file():
                size = entry.stat().st_size
                lines.append(f"  {entry.name}  ({size} bytes)")
            elif entry.is_dir():
                lines.append(f"  {entry.name}/")
        if not lines:
            return ToolResult(success=True, data="(empty directory)")
        return ToolResult(success=True, data="\n".join(lines))
```

**Step 4: Verify syntax**

Run: `uv run python -c "import odigos.tools.file"`

**Step 5: Run tests**

Run: `uv run pytest tests/test_file_tool.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add odigos/tools/file.py tests/test_file_tool.py
git commit -m "feat: add FileTool with sandboxed path validation"
```

---

### Task 3: Register FileTool in main.py

**Files:**
- Modify: `odigos/main.py` (add FileTool registration after code tool block)

**Step 1: Add registration**

After the code tool registration block (after `logger.info("Code tool initialized (sandbox)")`), add:

```python
    # Initialize file tool with configured allowed paths
    from odigos.tools.file import FileTool

    file_tool = FileTool(allowed_paths=settings.file_access.allowed_paths)
    tool_registry.register(file_tool)
    logger.info("File tool initialized (allowed: %s)", settings.file_access.allowed_paths)
```

**Step 2: Verify**

Run: `uv run python -c "import odigos.main"`

**Step 3: Commit**

```bash
git add odigos/main.py
git commit -m "feat: register FileTool in main with configured allowed_paths"
```

---

### Task 4: Conversation export endpoint

**Files:**
- Modify: `odigos/api/conversations.py` (add export functions and endpoint)
- Create: `tests/test_conversation_export.py`

**Step 1: Write the failing tests**

Create `tests/test_conversation_export.py`:

```python
import uuid
import pytest
from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


async def _create_conversation(db, conv_id, title="Test Chat"):
    await db.execute(
        "INSERT INTO conversations (id, channel, title) VALUES (?, ?, ?)",
        (conv_id, "test", title),
    )
    for i in range(4):
        role = "user" if i % 2 == 0 else "assistant"
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), conv_id, role, f"Message {i}"),
        )


class TestConversationExport:
    async def test_export_markdown(self, db):
        from odigos.api.conversations import _export_markdown
        conv_id = "conv-export-1"
        await _create_conversation(db, conv_id, "My Chat")
        result = await _export_markdown(db, conv_id)
        assert "# My Chat" in result
        assert "Message 0" in result
        assert "Message 3" in result

    async def test_export_json(self, db):
        import json
        from odigos.api.conversations import _export_json
        conv_id = "conv-export-2"
        await _create_conversation(db, conv_id)
        result = await _export_json(db, conv_id)
        data = json.loads(result)
        assert "messages" in data
        assert len(data["messages"]) == 4

    async def test_export_nonexistent(self, db):
        from odigos.api.conversations import _export_markdown
        result = await _export_markdown(db, "nope")
        assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_conversation_export.py -v`
Expected: FAIL — functions don't exist

**Step 3: Add export functions and endpoint**

In `odigos/api/conversations.py`, add `import json` and `from fastapi.responses import PlainTextResponse` at the top. Then add at the bottom:

```python
async def _export_markdown(db: Database, conversation_id: str) -> str | None:
    """Export a conversation as markdown."""
    conv = await db.fetch_one(
        "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
    )
    if not conv:
        return None

    title = conv.get("title") or conv["id"]
    messages = await db.fetch_all(
        "SELECT role, content, timestamp FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC",
        (conversation_id,),
    )

    lines = [f"# {title}\n"]
    for msg in messages:
        ts = msg.get("timestamp", "")
        role = msg["role"].capitalize()
        lines.append(f"**{role}** ({ts}):\n{msg['content']}\n")

    return "\n".join(lines)


async def _export_json(db: Database, conversation_id: str) -> str | None:
    """Export a conversation as JSON."""
    conv = await db.fetch_one(
        "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
    )
    if not conv:
        return None

    messages = await db.fetch_all(
        "SELECT id, role, content, timestamp FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC",
        (conversation_id,),
    )

    return json.dumps({
        "conversation_id": conversation_id,
        "title": conv.get("title") or conv["id"],
        "messages": messages,
    }, indent=2, default=str)


@router.get("/conversations/{conversation_id:path}/export")
async def export_conversation(
    conversation_id: str,
    format: str = Query(default="markdown", pattern="^(markdown|json)$"),
    db: Database = Depends(get_db),
):
    """Export a conversation as markdown or JSON."""
    if format == "json":
        result = await _export_json(db, conversation_id)
        media_type = "application/json"
        filename = f"{conversation_id}.json"
    else:
        result = await _export_markdown(db, conversation_id)
        media_type = "text/markdown"
        filename = f"{conversation_id}.md"

    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return PlainTextResponse(
        content=result,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_conversation_export.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add odigos/api/conversations.py tests/test_conversation_export.py
git commit -m "feat: add conversation export endpoint (markdown + JSON)"
```

---

### Task 5: Dead code cleanup — remove PeerClient

**Files:**
- Delete: `odigos/core/peers.py`
- Delete: `tests/test_peer_client.py`
- Delete: `tests/test_peer_dedup.py`
- Modify: `odigos/tools/peer.py` (fix type hint to AgentClient)

**Step 1: Update MessagePeerTool type hint**

In `odigos/tools/peer.py`, change:

```python
if TYPE_CHECKING:
    from odigos.core.peers import PeerClient
```

To:

```python
if TYPE_CHECKING:
    from odigos.core.agent_client import AgentClient
```

And change:

```python
    def __init__(self, peer_client: PeerClient) -> None:
```

To:

```python
    def __init__(self, peer_client: AgentClient) -> None:
```

**Step 2: Delete dead files**

```bash
rm odigos/core/peers.py tests/test_peer_client.py tests/test_peer_dedup.py
```

**Step 3: Verify no remaining references**

Run: `grep -r "from odigos.core.peers" odigos/ tests/` — should return nothing

**Step 4: Run full tests**

Run: `uv run pytest tests/ -q`
Expected: All pass

**Step 5: Commit**

```bash
git rm odigos/core/peers.py tests/test_peer_client.py tests/test_peer_dedup.py
git add odigos/tools/peer.py
git commit -m "chore: remove dead PeerClient code, fix MessagePeerTool type hint"
```

---

### Task 6: Create AgentService facade

**Files:**
- Create: `odigos/core/agent_service.py`
- Create: `tests/test_agent_service.py`

**Step 1: Write the failing tests**

Create `tests/test_agent_service.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from odigos.core.agent_service import AgentService


@pytest.fixture
def service():
    return AgentService(
        agent=AsyncMock(),
        goal_store=AsyncMock(),
        budget_tracker=AsyncMock(),
        approval_gate=MagicMock(),
    )


class TestAgentService:
    async def test_handle_message(self, service):
        service.agent.handle_message.return_value = "Hello!"
        result = await service.handle_message(MagicMock())
        assert result == "Hello!"
        service.agent.handle_message.assert_called_once()

    async def test_list_goals(self, service):
        service.goal_store.list_goals.return_value = [{"id": "g1"}]
        result = await service.list_goals()
        assert len(result) == 1

    async def test_list_todos(self, service):
        service.goal_store.list_todos.return_value = [{"id": "t1"}]
        result = await service.list_todos()
        assert len(result) == 1

    async def test_list_reminders(self, service):
        service.goal_store.list_reminders.return_value = [{"id": "r1"}]
        result = await service.list_reminders()
        assert len(result) == 1

    async def test_cancel_item(self, service):
        service.goal_store.cancel.return_value = True
        result = await service.cancel_item("g1")
        assert result is True

    async def test_check_budget(self, service):
        service.budget_tracker.check_budget.return_value = MagicMock(within_budget=True)
        result = await service.check_budget()
        assert result.within_budget

    async def test_resolve_approval(self, service):
        service.approval_gate.resolve.return_value = True
        result = service.resolve_approval("a1", "approved")
        assert result is True

    async def test_heartbeat_pause_resume(self, service):
        service.agent.heartbeat = MagicMock(paused=False)
        service.pause_heartbeat()
        assert service.agent.heartbeat.paused is True
        service.resume_heartbeat()
        assert service.agent.heartbeat.paused is False

    async def test_no_approval_gate(self):
        service = AgentService(
            agent=AsyncMock(),
            goal_store=AsyncMock(),
            budget_tracker=AsyncMock(),
            approval_gate=None,
        )
        result = service.resolve_approval("a1", "approved")
        assert result is False
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agent_service.py -v`
Expected: FAIL — module not found

**Step 3: Implement AgentService**

Create `odigos/core/agent_service.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from odigos.channels.base import UniversalMessage
    from odigos.core.agent import Agent
    from odigos.core.approval import ApprovalGate
    from odigos.core.budget import BudgetTracker
    from odigos.core.goal_store import GoalStore


class AgentService:
    """Facade providing a single entry point for all interaction interfaces.

    Wraps Agent, GoalStore, BudgetTracker, and ApprovalGate so that channels
    and plugins don't need to know about each individual dependency.
    """

    def __init__(
        self,
        agent: Agent,
        goal_store: GoalStore,
        budget_tracker: BudgetTracker,
        approval_gate: ApprovalGate | None = None,
    ) -> None:
        self.agent = agent
        self.goal_store = goal_store
        self.budget_tracker = budget_tracker
        self.approval_gate = approval_gate

    # -- Message handling --

    async def handle_message(self, message: UniversalMessage) -> str:
        """Send a message to the agent and return the response."""
        return await self.agent.handle_message(message)

    # -- Goals / Todos / Reminders --

    async def list_goals(self) -> list[dict]:
        return await self.goal_store.list_goals()

    async def list_todos(self) -> list[dict]:
        return await self.goal_store.list_todos()

    async def list_reminders(self) -> list[dict]:
        return await self.goal_store.list_reminders()

    async def cancel_item(self, item_id: str) -> bool:
        return await self.goal_store.cancel(item_id)

    # -- Budget --

    async def check_budget(self) -> Any:
        return await self.budget_tracker.check_budget()

    # -- Approvals --

    def resolve_approval(self, approval_id: str, decision: str) -> bool:
        if not self.approval_gate:
            return False
        return self.approval_gate.resolve(approval_id, decision)

    # -- Heartbeat --

    def pause_heartbeat(self) -> None:
        if self.agent.heartbeat:
            self.agent.heartbeat.paused = True

    def resume_heartbeat(self) -> None:
        if self.agent.heartbeat:
            self.agent.heartbeat.paused = False

    @property
    def heartbeat_paused(self) -> bool | None:
        if self.agent.heartbeat:
            return self.agent.heartbeat.paused
        return None
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_agent_service.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add odigos/core/agent_service.py tests/test_agent_service.py
git commit -m "feat: add AgentService facade for interaction interfaces"
```

---

### Task 7: Two-phase plugin loading — add AgentService to PluginContext

**Files:**
- Modify: `odigos/core/plugin_context.py` (add set_service method)
- Modify: `odigos/core/plugins.py` (add load_channels phase)
- Modify: `odigos/main.py` (create AgentService, pass settings, call channel phase)

**Step 1: Add set_service to PluginContext**

In `odigos/core/plugin_context.py`, add to the TYPE_CHECKING block:

```python
    from odigos.core.agent_service import AgentService
```

Add a field in `__init__`:

```python
        self.service: AgentService | None = None
```

Add a method:

```python
    def set_service(self, service: AgentService) -> None:
        """Set the AgentService after agent initialization (phase 2)."""
        self.service = service
```

**Step 2: Add channel-phase loading to PluginManager**

In `odigos/core/plugins.py`, add a new method to `PluginManager`:

```python
    def load_channels(self, plugins_dir: str) -> None:
        """Phase 2: Load channel plugins that need AgentService.

        Scans for plugins in a 'channels' subdirectory.
        These are loaded after the Agent is created and AgentService is set on the context.
        """
        channels_path = Path(plugins_dir) / "channels"
        if not channels_path.exists():
            return

        for subdir in sorted(channels_path.iterdir()):
            if subdir.is_dir() and not subdir.name.startswith("__"):
                init = subdir / "__init__.py"
                if init.exists():
                    self._load_plugin(init, name_override=subdir.name)
            elif subdir.suffix == ".py" and not subdir.name.startswith("__"):
                self._load_plugin(subdir)
```

**Step 3: Wire into main.py**

In `odigos/main.py`:

1. Pass settings to plugin_context (replace `config={}`):

```python
    plugin_context = PluginContext(
        tool_registry=tool_registry,
        channel_registry=channel_registry,
        tracer=tracer,
        config={"settings": settings},
    )
```

2. After Agent creation and Telegram block, create AgentService and set on context. Add import at the top imports area or inline:

```python
    from odigos.core.agent_service import AgentService

    agent_service = AgentService(
        agent=agent,
        goal_store=goal_store,
        budget_tracker=budget_tracker,
        approval_gate=approval_gate,
    )
    plugin_context.set_service(agent_service)
    app.state.agent_service = agent_service
```

3. After setting the service, load channel plugins:

```python
    plugin_manager.load_channels("plugins")
    logger.info("Channel plugins loaded")
```

**Step 4: Verify**

Run: `uv run python -c "import odigos.main"`

**Step 5: Run full tests**

Run: `uv run pytest tests/ -q`
Expected: All pass

**Step 6: Commit**

```bash
git add odigos/core/plugin_context.py odigos/core/plugins.py odigos/main.py
git commit -m "feat: two-phase plugin loading with AgentService on PluginContext"
```

---

### Task 8: Convert SearXNG, GWS, and Browser to plugins

**Files:**
- Create: `plugins/searxng/__init__.py`
- Create: `plugins/gws/__init__.py`
- Create: `plugins/browser/__init__.py`
- Modify: `odigos/main.py` (remove all three conditional blocks)

**Step 1: Create SearXNG plugin**

Create `plugins/searxng/__init__.py`:

```python
"""SearXNG web search plugin.

Registers the web_search tool when searxng_url is configured.
Requires a running SearXNG instance.
"""
import logging

logger = logging.getLogger(__name__)


def register(ctx):
    settings = ctx.config.get("settings")
    if not settings or not settings.searxng_url:
        return

    from odigos.providers.searxng import SearxngProvider
    from odigos.tools.search import SearchTool

    searxng = SearxngProvider(
        url=settings.searxng_url,
        username=settings.searxng_username,
        password=settings.searxng_password,
    )
    search_tool = SearchTool(searxng=searxng)
    ctx.register_tool(search_tool)
    logger.info("SearXNG search plugin loaded (%s)", settings.searxng_url)
```

**Step 2: Create GWS plugin**

Create `plugins/gws/__init__.py`:

```python
"""Google Workspace plugin.

Registers the run_gws tool when gws.enabled is true and the gws CLI is installed.
Install CLI: npm install -g @googleworkspace/cli
"""
import logging
import shutil

logger = logging.getLogger(__name__)


def register(ctx):
    settings = ctx.config.get("settings")
    if not settings or not settings.gws.enabled:
        return

    if not shutil.which("gws"):
        logger.warning(
            "GWS enabled but gws CLI not found. "
            "Install: npm install -g @googleworkspace/cli"
        )
        return

    from odigos.tools.gws import GWSTool

    gws_tool = GWSTool(timeout=settings.gws.timeout)
    ctx.register_tool(gws_tool)
    logger.info("Google Workspace plugin loaded (gws CLI)")
```

**Step 3: Create Browser plugin**

Create `plugins/browser/__init__.py`:

```python
"""Agent Browser automation plugin.

Registers the run_browser tool when browser.enabled is true and agent-browser CLI is installed.
Install CLI: npm install -g @anthropic-ai/agent-browser
"""
import logging
import shutil

logger = logging.getLogger(__name__)


def register(ctx):
    settings = ctx.config.get("settings")
    if not settings or not settings.browser.enabled:
        return

    if not shutil.which("agent-browser"):
        logger.warning(
            "Browser enabled but agent-browser CLI not found. "
            "Install: npm install -g @anthropic-ai/agent-browser"
        )
        return

    from odigos.tools.browser import BrowserTool

    browser_tool = BrowserTool(timeout=settings.browser.timeout)
    ctx.register_tool(browser_tool)
    logger.info("Agent Browser plugin loaded")
```

**Step 4: Remove from main.py**

Remove these three blocks from `odigos/main.py`:

1. The SearXNG block (~lines 182-194):
```python
    # Add search tool if SearXNG is configured
    if settings.searxng_url:
        ...
```

2. The GWS block (~lines 234-247):
```python
    # Register Google Workspace tool if enabled
    if settings.gws.enabled:
        ...
```

3. The Browser block (~lines 249-262):
```python
    # Register Agent Browser tool if enabled
    if settings.browser.enabled:
        ...
```

Also clean up module-level references and shutdown:
- Remove `_searxng = None` from module-level globals
- Remove `_searxng` from the `global` declaration in lifespan
- Remove `if _searxng: await _searxng.close()` from shutdown

**Step 5: Run full tests**

Run: `uv run pytest tests/ -q`
Expected: All pass

**Step 6: Commit**

```bash
git add plugins/searxng/__init__.py plugins/gws/__init__.py plugins/browser/__init__.py odigos/main.py
git commit -m "refactor: move SearXNG, GWS, Browser from main.py to plugins"
```

---

### Task 9: Convert Telegram to channel plugin

**Files:**
- Create: `plugins/channels/telegram/__init__.py`
- Modify: `odigos/main.py` (remove Telegram block and import)

**Step 1: Create the Telegram channel plugin**

Create `plugins/channels/telegram/__init__.py`:

```python
"""Telegram bot channel plugin.

Registers the Telegram channel when telegram_bot_token is configured.
Loaded in phase 2 (after AgentService is available).
"""
import logging

logger = logging.getLogger(__name__)


def register(ctx):
    settings = ctx.config.get("settings")
    if not settings or not settings.telegram_bot_token:
        logger.info("Telegram plugin skipped: no telegram_bot_token configured")
        return

    if not ctx.service:
        logger.warning("Telegram plugin skipped: AgentService not available (wrong loading phase?)")
        return

    from odigos.channels.telegram import TelegramChannel

    telegram_channel = TelegramChannel(
        token=settings.telegram_bot_token,
        service=ctx.service,
        mode=settings.telegram.mode,
        webhook_url=settings.telegram.webhook_url,
    )
    ctx.register_channel("telegram", telegram_channel)
    logger.info("Telegram channel plugin loaded")
```

**Step 2: Refactor TelegramChannel to use AgentService**

In `odigos/channels/telegram.py`, change the constructor and all references:

Replace the import and constructor:

```python
from odigos.core.agent import Agent
```
becomes:
```python
from odigos.core.agent_service import AgentService
```

Replace `__init__`:
```python
    def __init__(
        self,
        token: str,
        service: AgentService,
        mode: str = "polling",
        webhook_url: str = "",
    ) -> None:
        self.token = token
        self.service = service
        self.mode = mode
        self.webhook_url = webhook_url
        self._app: Application | None = None
```

Then update all method bodies:
- `self.agent.handle_message(message)` -> `self.service.handle_message(message)`
- `self.goal_store.list_goals()` -> `self.service.list_goals()`
- `self.goal_store.list_todos()` -> `self.service.list_todos()`
- `self.goal_store.list_reminders()` -> `self.service.list_reminders()`
- `self.goal_store.cancel(...)` -> `self.service.cancel_item(...)`
- `self.budget_tracker.check_budget()` -> `self.service.check_budget()`
- `self.approval_gate.resolve(...)` -> `self.service.resolve_approval(...)`
- `self.agent.heartbeat.paused = True` -> `self.service.pause_heartbeat()`
- `self.agent.heartbeat.paused = False` -> `self.service.resume_heartbeat()`
- `self.agent.heartbeat.paused` (read) -> `self.service.heartbeat_paused`
- `self.agent.heartbeat` (truthiness check) -> `self.service.heartbeat_paused is not None`

**Step 3: Remove Telegram block from main.py**

Remove:
```python
from odigos.channels.telegram import TelegramChannel
```
from the imports.

Remove the Telegram initialization block:
```python
    # Initialize Telegram channel (optional — skipped if no token)
    if settings.telegram_bot_token:
        telegram_channel = TelegramChannel(
            ...
        )
        channel_registry.register("telegram", telegram_channel)
    else:
        logger.warning("No TELEGRAM_BOT_TOKEN set — Telegram channel disabled")
```

**Step 4: Run full tests**

Run: `uv run pytest tests/ -q`
Expected: All pass

**Step 5: Commit**

```bash
git add plugins/channels/telegram/__init__.py odigos/channels/telegram.py odigos/main.py
git commit -m "refactor: convert Telegram channel to plugin using AgentService"
```

---

### Task 10: Full test suite + cleanup verification

**Step 1: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 2: Verify no dead imports**

Run: `grep -r "from odigos.core.peers" odigos/ tests/` — should return nothing
Run: `grep -r "_searxng" odigos/main.py` — should return nothing

**Step 3: Verify plugins load**

Run: `uv run python -c "
from odigos.core.plugins import PluginManager
from odigos.core.plugin_context import PluginContext
from odigos.tools.registry import ToolRegistry
from odigos.channels.base import ChannelRegistry
pm = PluginManager(plugin_context=PluginContext(tool_registry=ToolRegistry(), channel_registry=ChannelRegistry(), config={}))
pm.load_all('plugins')
print(f'Phase 1 plugins: {[p[\"name\"] for p in pm.loaded_plugins]}')
pm.load_channels('plugins')
print(f'All plugins: {[p[\"name\"] for p in pm.loaded_plugins]}')
"`
Expected: Lists docling, searxng (skipped), gws (skipped), browser (skipped) in phase 1; telegram (skipped — no service) in phase 2

**Step 4: Commit if any fixes were needed**

---

## Summary of Changes

| File | Action |
|------|--------|
| `odigos/config.py` | Add FileAccessConfig |
| `odigos/tools/file.py` | New: FileTool with sandbox |
| `tests/test_file_tool.py` | New: FileTool tests |
| `odigos/api/conversations.py` | Add export endpoint |
| `tests/test_conversation_export.py` | New: export tests |
| `odigos/core/peers.py` | Delete (dead code) |
| `tests/test_peer_client.py` | Delete (dead tests) |
| `tests/test_peer_dedup.py` | Delete (dead tests) |
| `odigos/tools/peer.py` | Fix type hint to AgentClient |
| `odigos/core/agent_service.py` | New: AgentService facade |
| `tests/test_agent_service.py` | New: AgentService tests |
| `odigos/core/plugin_context.py` | Add set_service, service field |
| `odigos/core/plugins.py` | Add load_channels phase 2 method |
| `odigos/main.py` | Register FileTool, create AgentService, pass settings to PluginContext, two-phase loading, remove SearXNG/GWS/Browser/Telegram blocks |
| `odigos/channels/telegram.py` | Refactor to use AgentService instead of individual deps |
| `plugins/searxng/__init__.py` | New: SearXNG plugin |
| `plugins/gws/__init__.py` | New: GWS plugin |
| `plugins/browser/__init__.py` | New: Browser plugin |
| `plugins/channels/telegram/__init__.py` | New: Telegram channel plugin |
