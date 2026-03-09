# Google Workspace Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate Google Workspace (Gmail, Calendar, Drive, Sheets) via the `gws` CLI as a single `run_gws` tool.

**Architecture:** A `GWSTool` shells out to the `gws` CLI via `asyncio.create_subprocess_exec`, returning JSON output. A `google-workspace` skill provides command reference. Config flag `gws.enabled` controls registration.

**Tech Stack:** Python 3.12, asyncio, shlex, shutil, pytest

**Design doc:** `docs/plans/2026-03-09-gws-integration-design.md`

---

### Task 1: GWSTool and tests

**Files:**
- Create: `odigos/tools/gws.py`
- Create: `tests/test_gws.py`

**Context:** The `GWSTool` wraps the `gws` CLI. It extends `BaseTool` (from `odigos/tools/base.py`) which requires `name`, `description`, `parameters_schema`, and `async execute(params) -> ToolResult`. The tool uses `asyncio.create_subprocess_exec` to run `gws` commands and returns stdout as the result.

**Step 1: Write the failing tests**

Create `tests/test_gws.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odigos.tools.gws import GWSTool


class TestGWSTool:
    def test_tool_metadata(self):
        tool = GWSTool()
        assert tool.name == "run_gws"
        assert "command" in tool.parameters_schema["properties"]
        assert "command" in tool.parameters_schema["required"]

    async def test_missing_command(self):
        tool = GWSTool()
        result = await tool.execute({})
        assert result.success is False
        assert "command" in result.error.lower()

    async def test_empty_command(self):
        tool = GWSTool()
        result = await tool.execute({"command": ""})
        assert result.success is False

    @patch("odigos.tools.gws.asyncio.create_subprocess_exec")
    async def test_successful_command(self, mock_exec):
        proc = AsyncMock()
        proc.communicate = AsyncMock(
            return_value=(b'{"files": []}', b"")
        )
        proc.returncode = 0
        mock_exec.return_value = proc

        tool = GWSTool()
        result = await tool.execute({"command": "drive files list"})

        assert result.success is True
        assert '{"files": []}' in result.data
        mock_exec.assert_called_once_with(
            "gws", "drive", "files", "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    @patch("odigos.tools.gws.asyncio.create_subprocess_exec")
    async def test_command_failure(self, mock_exec):
        proc = AsyncMock()
        proc.communicate = AsyncMock(
            return_value=(b"", b"Error: not authenticated")
        )
        proc.returncode = 1
        mock_exec.return_value = proc

        tool = GWSTool()
        result = await tool.execute({"command": "drive files list"})

        assert result.success is False
        assert "not authenticated" in result.error

    @patch("odigos.tools.gws.asyncio.create_subprocess_exec")
    async def test_gws_not_found(self, mock_exec):
        mock_exec.side_effect = FileNotFoundError()

        tool = GWSTool()
        result = await tool.execute({"command": "drive files list"})

        assert result.success is False
        assert "npm install" in result.error

    @patch("odigos.tools.gws.asyncio.create_subprocess_exec")
    async def test_timeout(self, mock_exec):
        proc = AsyncMock()

        async def slow_communicate():
            await asyncio.sleep(60)
            return b"", b""

        proc.communicate = slow_communicate
        proc.kill = MagicMock()
        mock_exec.return_value = proc

        tool = GWSTool(timeout=1)
        result = await tool.execute({"command": "drive files list"})

        assert result.success is False
        assert "timed out" in result.error.lower()
        proc.kill.assert_called_once()

    @patch("odigos.tools.gws.asyncio.create_subprocess_exec")
    async def test_quoted_params(self, mock_exec):
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b'{}', b""))
        proc.returncode = 0
        mock_exec.return_value = proc

        tool = GWSTool()
        await tool.execute({"command": '''drive files list --params '{"pageSize": 5}' '''})

        mock_exec.assert_called_once_with(
            "gws", "drive", "files", "list", "--params", '{"pageSize": 5}',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    @patch("odigos.tools.gws.asyncio.create_subprocess_exec")
    async def test_custom_timeout(self, mock_exec):
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b'{}', b""))
        proc.returncode = 0
        mock_exec.return_value = proc

        tool = GWSTool(timeout=60)
        assert tool._timeout == 60
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gws.py -v`
Expected: FAIL (`odigos.tools.gws` does not exist)

**Step 3: Implement GWSTool**

Create `odigos/tools/gws.py`:

```python
from __future__ import annotations

import asyncio
import logging
import shlex

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30


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

        args = shlex.split(command)

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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gws.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add odigos/tools/gws.py tests/test_gws.py
git commit -m "feat: add GWSTool for Google Workspace CLI integration"
```

---

### Task 2: Google Workspace skill and config

**Files:**
- Create: `skills/google-workspace.md`
- Modify: `odigos/config.py:82-103`

**Context:** The skill provides `gws` command reference for the agent. The config adds a `gws` section with `enabled` and `timeout` fields.

**Step 1: Create the skill file**

Create `skills/google-workspace.md`:

```markdown
---
name: google-workspace
description: Interact with Google Workspace (Gmail, Calendar, Drive, Sheets) via the gws CLI
tools: [run_gws]
complexity: standard
---
You have access to Google Workspace via the `run_gws` tool. Pass gws CLI commands.

## Command patterns

**Gmail:**
- `gmail users messages list --params '{"userId": "me", "maxResults": 10}'`
- `gmail users messages get --params '{"userId": "me", "id": "MSG_ID"}'`
- `gmail users messages send --params '{"userId": "me"}' --json '{"raw": "BASE64_ENCODED_EMAIL"}'`
- `gmail users labels list --params '{"userId": "me"}'`

**Calendar:**
- `calendar events list --params '{"calendarId": "primary", "timeMin": "2026-03-09T00:00:00Z", "maxResults": 10}'`
- `calendar events insert --params '{"calendarId": "primary"}' --json '{"summary": "Meeting", "start": {"dateTime": "2026-03-10T10:00:00Z"}, "end": {"dateTime": "2026-03-10T11:00:00Z"}}'`
- `calendar events delete --params '{"calendarId": "primary", "eventId": "EVENT_ID"}'`

**Drive:**
- `drive files list --params '{"pageSize": 10}'`
- `drive files get --params '{"fileId": "FILE_ID"}'`
- `drive files create --json '{"name": "document.txt"}' --upload ./file.txt`

**Sheets:**
- `sheets spreadsheets create --json '{"properties": {"title": "My Sheet"}}'`
- `sheets spreadsheets values get --params '{"spreadsheetId": "ID", "range": "Sheet1!A1:B10"}'`
- `sheets spreadsheets values update --params '{"spreadsheetId": "ID", "range": "Sheet1!A1", "valueInputOption": "RAW"}' --json '{"values": [["hello"]]}'`

## Tips

- Use `gws schema <method>` to discover full request/response schema for any API method
- Add `--dry-run` to preview a request without executing it
- Use `--params` for URL/query parameters, `--json` for request body
- All commands return JSON
- For pagination: add `--page-all` to stream all pages
```

**Step 2: Add GWSConfig to config.py**

In `odigos/config.py`, add the config class before `Settings`:

```python
class GWSConfig(BaseModel):
    enabled: bool = False
    timeout: int = 30
```

Add to `Settings` class:

```python
    gws: GWSConfig = GWSConfig()
```

**Step 3: Write config test**

Add to `tests/test_gws.py`:

```python
from odigos.config import GWSConfig, Settings


class TestGWSConfig:
    def test_default_disabled(self):
        config = GWSConfig()
        assert config.enabled is False
        assert config.timeout == 30

    def test_enabled(self):
        config = GWSConfig(enabled=True, timeout=60)
        assert config.enabled is True
        assert config.timeout == 60
```

**Step 4: Write skill test**

Add to `tests/test_gws.py`:

```python
from odigos.skills.registry import SkillRegistry


class TestGWSSkill:
    def test_skill_loads(self):
        registry = SkillRegistry()
        registry.load_all("skills")
        skill = registry.get("google-workspace")
        assert skill is not None
        assert "run_gws" in skill.tools
        assert skill.complexity == "standard"
        assert "gmail" in skill.system_prompt.lower()
```

**Step 5: Run tests**

Run: `pytest tests/test_gws.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add skills/google-workspace.md odigos/config.py tests/test_gws.py
git commit -m "feat: add google-workspace skill and GWS config"
```

---

### Task 3: Wire into main.py

**Files:**
- Modify: `odigos/main.py`

**Context:** When `settings.gws.enabled`, check if `gws` is on PATH, register `GWSTool` with the configured timeout.

**Step 1: Add wiring**

In `odigos/main.py`, after the sandbox/code tool registration block (after `logger.info("Code tool initialized (sandbox)")`), add:

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

**Step 2: Run tests**

Run: `pytest tests/test_gws.py -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add odigos/main.py
git commit -m "feat: wire GWSTool into main.py with config flag"
```
