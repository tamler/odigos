# Capability Audit Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add file read/write tool, conversation export, remove dead code, and convert 3 opt-in capabilities to plugins.

**Architecture:** FileTool with configurable sandboxed paths via config.yaml. Export endpoint on existing conversations API. SearXNG, GWS, and Browser move from main.py conditional blocks to `plugins/` using the existing register(ctx) pattern. Telegram stays in main.py (needs Agent instance which doesn't exist at plugin load time).

**Tech Stack:** FastAPI, aiosqlite, existing plugin system, existing tool base classes

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
import os
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
        """Resolve path and check it's within allowed directories.

        Returns (resolved_path, error_message). error_message is None if valid.
        """
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

        # Check for binary content
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
            # Validate parent is still within sandbox after creation
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
- Modify: `odigos/main.py` (add FileTool registration after code tool)

**Step 1: Add registration**

After the code tool registration block (after line ~232), add:

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
- Modify: `odigos/api/conversations.py` (add export endpoint)
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

In `odigos/api/conversations.py`, add at the top:

```python
import json
from fastapi.responses import PlainTextResponse
```

Then add these functions and endpoint at the bottom of the file:

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

And change the constructor:

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

Run: `uv run python -c "from odigos.tools.peer import MessagePeerTool; print('OK')"`
And: `grep -r "from odigos.core.peers" odigos/ tests/` should return nothing.

**Step 4: Run full tests**

Run: `uv run pytest tests/ -q`
Expected: All pass (minus the 2 deleted test files)

**Step 5: Commit**

```bash
git rm odigos/core/peers.py tests/test_peer_client.py tests/test_peer_dedup.py
git add odigos/tools/peer.py
git commit -m "chore: remove dead PeerClient code, fix MessagePeerTool type hint"
```

---

### Task 6: Pass settings to PluginContext

**Files:**
- Modify: `odigos/main.py` (~line 360, plugin_context creation)

**Step 1: Pass settings through config dict**

In `odigos/main.py`, change:

```python
    plugin_context = PluginContext(
        tool_registry=tool_registry,
        channel_registry=channel_registry,
        tracer=tracer,
        config={},  # Will come from settings.plugins when config schema is updated
    )
```

To:

```python
    plugin_context = PluginContext(
        tool_registry=tool_registry,
        channel_registry=channel_registry,
        tracer=tracer,
        config={"settings": settings},
    )
```

**Step 2: Verify**

Run: `uv run python -c "import odigos.main"`

**Step 3: Commit**

```bash
git add odigos/main.py
git commit -m "feat: pass settings to PluginContext for plugin config access"
```

---

### Task 7: Convert SearXNG to plugin

**Files:**
- Create: `plugins/searxng/__init__.py`
- Modify: `odigos/main.py` (remove SearXNG block, lines ~182-194)

**Step 1: Create the plugin**

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

**Step 2: Remove from main.py**

Remove the SearXNG block (lines ~182-194):

```python
    # Add search tool if SearXNG is configured
    if settings.searxng_url:
        from odigos.providers.searxng import SearxngProvider
        from odigos.tools.search import SearchTool

        _searxng = SearxngProvider(
            url=settings.searxng_url,
            username=settings.searxng_username,
            password=settings.searxng_password,
        )
        search_tool = SearchTool(searxng=_searxng)
        tool_registry.register(search_tool)
        logger.info("Search tool initialized (SearXNG: %s)", settings.searxng_url)
```

Also remove `_searxng = None` from module-level (line ~63) and the `_searxng` cleanup in shutdown:

```python
    if _searxng:
        await _searxng.close()
```

Note: The SearxngProvider.close() will need to be handled differently. For now, the provider will be garbage collected on shutdown. If SearxngProvider holds an httpx client, the plugin should store the provider reference for cleanup. Check if this matters — if `SearxngProvider.close()` just closes an httpx client, the GC will handle it. If it's important, add the provider to plugin_context via `register_provider("searxng", searxng)` and close it in shutdown.

**Step 3: Verify**

Run: `uv run python -c "import odigos.main"`

**Step 4: Commit**

```bash
git add plugins/searxng/__init__.py odigos/main.py
git commit -m "refactor: move SearXNG search from main.py to plugin"
```

---

### Task 8: Convert GWS to plugin

**Files:**
- Create: `plugins/gws/__init__.py`
- Modify: `odigos/main.py` (remove GWS block, lines ~234-247)

**Step 1: Create the plugin**

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

**Step 2: Remove from main.py**

Remove the GWS block (lines ~234-247):

```python
    # Register Google Workspace tool if enabled
    if settings.gws.enabled:
        import shutil
        from odigos.tools.gws import GWSTool

        if shutil.which("gws"):
            gws_tool = GWSTool(timeout=settings.gws.timeout)
            tool_registry.register(gws_tool)
            logger.info("Google Workspace tool initialized (gws CLI)")
        else:
            logger.warning(
                "GWS enabled but gws CLI not found. "
                "Install: npm install -g @googleworkspace/cli"
            )
```

**Step 3: Commit**

```bash
git add plugins/gws/__init__.py odigos/main.py
git commit -m "refactor: move Google Workspace from main.py to plugin"
```

---

### Task 9: Convert Browser to plugin

**Files:**
- Create: `plugins/browser/__init__.py`
- Modify: `odigos/main.py` (remove Browser block, lines ~249-262)

**Step 1: Create the plugin**

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

**Step 2: Remove from main.py**

Remove the Browser block (lines ~249-262):

```python
    # Register Agent Browser tool if enabled
    if settings.browser.enabled:
        import shutil
        from odigos.tools.browser import BrowserTool

        if shutil.which("agent-browser"):
            browser_tool = BrowserTool(timeout=settings.browser.timeout)
            tool_registry.register(browser_tool)
            logger.info("Agent Browser tool initialized")
        else:
            logger.warning(
                "Browser enabled but agent-browser CLI not found. "
                "Install: npm install -g @anthropic-ai/agent-browser"
            )
```

**Step 3: Commit**

```bash
git add plugins/browser/__init__.py odigos/main.py
git commit -m "refactor: move Browser automation from main.py to plugin"
```

---

### Task 10: Full test suite + cleanup verification

**Step 1: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 2: Verify no dead imports**

Run: `grep -r "from odigos.core.peers" odigos/ tests/` — should return nothing
Run: `grep -r "_searxng" odigos/main.py` — should return nothing (removed)

**Step 3: Verify plugins load**

Run: `uv run python -c "
from odigos.core.plugins import PluginManager
from odigos.core.plugin_context import PluginContext
from odigos.tools.registry import ToolRegistry
pm = PluginManager(plugin_context=PluginContext(tool_registry=ToolRegistry(), config={}))
pm.load_all('plugins')
print(f'Loaded {len(pm.loaded_plugins)} plugins: {[p[\"name\"] for p in pm.loaded_plugins]}')
"`
Expected: Lists docling, searxng (skipped — no settings), gws (skipped), browser (skipped)

**Step 4: Commit if any fixes were needed**

---

## Summary of Changes

| File | Action |
|------|--------|
| `odigos/config.py` | Add FileAccessConfig |
| `odigos/tools/file.py` | New: FileTool with sandbox |
| `tests/test_file_tool.py` | New: FileTool tests |
| `odigos/main.py` | Register FileTool, pass settings to PluginContext, remove SearXNG/GWS/Browser blocks |
| `odigos/api/conversations.py` | Add export endpoint |
| `tests/test_conversation_export.py` | New: export tests |
| `odigos/core/peers.py` | Delete (dead code) |
| `tests/test_peer_client.py` | Delete (dead tests) |
| `tests/test_peer_dedup.py` | Delete (dead tests) |
| `odigos/tools/peer.py` | Fix type hint to AgentClient |
| `plugins/searxng/__init__.py` | New: SearXNG plugin |
| `plugins/gws/__init__.py` | New: GWS plugin |
| `plugins/browser/__init__.py` | New: Browser plugin |
