# API & CLI Tool Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Standardize tool implementation with `APITool` and `CLITool` base classes, executor-level parameter validation, observation filtering, and a shared HTTP client.

**Architecture:** Two new base classes (`APITool`, `CLITool`) extend `BaseTool`. The executor gains pre-call parameter validation and post-call observation filtering. A shared `httpx.AsyncClient` on the Container replaces per-tool HTTP client creation. Existing image_gen and music_gen tools migrate to `APITool`.

**Tech Stack:** Python 3.12, httpx, jsonschema (already transitive dep), pytest, asyncio

**Spec:** `docs/superpowers/specs/2026-04-04-api-tool-foundation-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `odigos/tools/base.py` | Add `format_for_context()` and forward-compat fields on `ToolResult` |
| `odigos/tools/api_tool.py` | **New** — `APITool`, `ToolAPIError` |
| `odigos/tools/cli_tool.py` | **New** — `CLITool`, `CLIToolError`, `CLIResult`, input hardening |
| `odigos/core/executor.py` | `_coerce_and_validate()`, `_auto_distill()`, integration in `_execute_tool` |
| `odigos/container.py` | `http_client` field |
| `odigos/bootstrap.py` | Create/close shared client, pass to API tools |
| `odigos/tools/image_gen.py` | Migrate to `APITool` base |
| `odigos/tools/music_gen.py` | Migrate to `APITool` base |
| `tests/test_tools.py` | Tests for `BaseTool.format_for_context`, `ToolResult` new fields |
| `tests/test_api_tool.py` | **New** — Tests for `APITool`, `ToolAPIError` |
| `tests/test_cli_tool.py` | **New** — Tests for `CLITool`, input hardening, error classification |
| `tests/test_executor_validation.py` | **New** — Tests for `_coerce_and_validate`, `_auto_distill` |

---

### Task 1: BaseTool — format_for_context and ToolResult forward-compat fields

**Files:**
- Modify: `odigos/tools/base.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write tests for format_for_context and new ToolResult fields**

Add to `tests/test_tools.py`:

```python
class TestFormatForContext:
    def test_default_returns_data(self):
        """BaseTool.format_for_context returns result.data unchanged by default."""
        tool = FakeTool()
        result = ToolResult(success=True, data="some output")
        assert tool.format_for_context(result) == "some output"

    def test_default_returns_empty_on_empty(self):
        tool = FakeTool()
        result = ToolResult(success=True, data="")
        assert tool.format_for_context(result) == ""


class TestAutoDistill:
    def test_short_text_unchanged(self):
        from odigos.tools.base import auto_distill
        assert auto_distill("short") == "short"

    def test_long_text_truncated(self):
        from odigos.tools.base import auto_distill
        lines = [f"line {i}" for i in range(200)]
        text = "\n".join(lines)
        result = auto_distill(text)
        assert len(result) < len(text)
        assert "line 0" in result
        assert "line 199" in result


class TestToolResultForwardCompat:
    def test_status_defaults_none(self):
        result = ToolResult(success=True, data="ok")
        assert result.status is None

    def test_task_id_defaults_none(self):
        result = ToolResult(success=True, data="ok")
        assert result.task_id is None

    def test_status_can_be_set(self):
        result = ToolResult(success=True, data="ok", status="pending", task_id="abc123")
        assert result.status == "pending"
        assert result.task_id == "abc123"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_tools.py::TestFormatForContext -v && python -m pytest tests/test_tools.py::TestToolResultForwardCompat -v`
Expected: FAIL — `format_for_context` not defined, `status`/`task_id` not fields on `ToolResult`

- [ ] **Step 3: Implement changes to base.py**

In `odigos/tools/base.py`, add two fields to `ToolResult`:

```python
@dataclass
class ToolResult:
    success: bool
    data: str
    error: str | None = None
    side_effect: dict | None = None
    failure_category: str | None = None  # transient, input, permission, unavailable, unknown
    status: str | None = None      # forward-compat: "pending", "complete"
    task_id: str | None = None     # forward-compat: for backgroundable tasks
```

Add `format_for_context` method to `BaseTool` and `auto_distill` function (shared utility used by CLITool and executor):

```python
def auto_distill(text: str) -> str:
    """Head-tail with signal extraction for verbose output.

    Used by the executor as a fallback and by CLITool as a default.
    """
    signal_words = {"error", "exception", "fail", "warning", "traceback", "exit"}
    lines = text.splitlines()
    if len(lines) <= 30:
        return text
    head = "\n".join(lines[:15])
    tail = "\n".join(lines[-15:])
    middle_signals = [
        line for line in lines[15:-15]
        if any(w in line.lower() for w in signal_words)
    ]
    mid = "\n".join(middle_signals[:10]) if middle_signals else "[...truncated...]"
    return f"{head}\n\n{mid}\n\n{tail}"


class BaseTool(ABC):
    name: str
    description: str
    category: str = ""
    parameters_schema: dict = {"type": "object", "properties": {}}
    contract: ToolContract = ToolContract()

    @abstractmethod
    async def execute(self, params: dict) -> ToolResult:
        """Execute the tool with the given parameters."""
        ...

    def format_for_context(self, result: ToolResult) -> str:
        """Format tool output for the LLM context window.

        Override to summarize verbose output. Default: return data as-is.
        The executor applies auto-distill if this default is used and output
        exceeds 2000 characters.
        """
        return result.data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_tools.py -v`
Expected: All PASS (existing tests + new tests)

- [ ] **Step 5: Commit**

```bash
git add odigos/tools/base.py tests/test_tools.py
git commit -m "feat(tools): add format_for_context and forward-compat ToolResult fields"
```

---

### Task 2: APITool base class

**Files:**
- Create: `odigos/tools/api_tool.py`
- Create: `tests/test_api_tool.py`

- [ ] **Step 1: Write tests for APITool**

Create `tests/test_api_tool.py`:

```python
import asyncio
import json

import httpx
import pytest

from odigos.tools.api_tool import APITool, ToolAPIError
from odigos.tools.base import ToolResult


class FakeAPITool(APITool):
    name = "fake_api"
    description = "Test API tool"
    parameters_schema = {"type": "object", "properties": {"query": {"type": "string"}}}

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(success=True, data="ok")


class TestToolAPIError:
    def test_default_category(self):
        err = ToolAPIError(500, "server error")
        assert err.status_code == 500
        assert err.message == "server error"
        assert err.failure_category == "unknown"

    def test_custom_category(self):
        err = ToolAPIError(429, "rate limited", failure_category="transient")
        assert err.failure_category == "transient"

    def test_str(self):
        err = ToolAPIError(404, "not found")
        assert "not found" in str(err)


class TestAPIToolInit:
    def test_stores_http_client(self):
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        assert tool.http is client

    def test_inherits_base_tool(self):
        from odigos.tools.base import BaseTool
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        assert isinstance(tool, BaseTool)


class TestAPIToolPost:
    @pytest.mark.asyncio
    async def test_api_post_success(self, httpx_mock):
        """api_post returns parsed JSON on 200."""
        httpx_mock.add_response(
            url="https://api.example.com/create",
            json={"code": 200, "data": {"id": "abc"}},
            status_code=200,
        )
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        result = await tool.api_post(
            "https://api.example.com/create",
            payload={"prompt": "test"},
            api_key="test-key",
        )
        assert result["data"]["id"] == "abc"
        await client.aclose()

    @pytest.mark.asyncio
    async def test_api_post_raises_on_4xx(self, httpx_mock):
        """api_post raises ToolAPIError on HTTP 4xx."""
        httpx_mock.add_response(
            url="https://api.example.com/create",
            json={"error": "bad request"},
            status_code=400,
        )
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        with pytest.raises(ToolAPIError) as exc_info:
            await tool.api_post(
                "https://api.example.com/create",
                payload={},
                api_key="test-key",
            )
        assert exc_info.value.status_code == 400
        assert "bad request" in exc_info.value.message
        await client.aclose()


class TestAPIToolGet:
    @pytest.mark.asyncio
    async def test_api_get_success(self, httpx_mock):
        httpx_mock.add_response(
            url="https://api.example.com/status",
            json={"status": "done"},
            status_code=200,
        )
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        result = await tool.api_get(
            "https://api.example.com/status",
            api_key="test-key",
            params={"id": "123"},
        )
        assert result["status"] == "done"
        await client.aclose()

    @pytest.mark.asyncio
    async def test_api_get_raises_on_5xx(self, httpx_mock):
        httpx_mock.add_response(
            url="https://api.example.com/status",
            json={"msg": "internal error"},
            status_code=500,
        )
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        with pytest.raises(ToolAPIError) as exc_info:
            await tool.api_get(
                "https://api.example.com/status",
                api_key="test-key",
            )
        assert exc_info.value.status_code == 500
        await client.aclose()


class TestAPIToolPollUntil:
    @pytest.mark.asyncio
    async def test_poll_success(self, httpx_mock):
        """poll_until returns extracted data when success_check passes."""
        # First poll: pending. Second poll: success.
        httpx_mock.add_response(
            url="https://api.example.com/poll",
            json={"status": "pending"},
            status_code=200,
        )
        httpx_mock.add_response(
            url="https://api.example.com/poll",
            json={"status": "done", "result": "image.png"},
            status_code=200,
        )
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        result = await tool.poll_until(
            "https://api.example.com/poll",
            api_key="test-key",
            params={"taskId": "t1"},
            success_check=lambda d: d.get("status") == "done",
            failure_check=lambda d: d.get("status") == "failed",
            extract=lambda d: d["result"],
            initial_delay=0.01,
            max_delay=0.02,
            max_seconds=5,
        )
        assert result == "image.png"
        await client.aclose()

    @pytest.mark.asyncio
    async def test_poll_failure_raises(self, httpx_mock):
        """poll_until raises ToolAPIError when failure_check matches."""
        httpx_mock.add_response(
            url="https://api.example.com/poll",
            json={"status": "failed", "error": "bad input"},
            status_code=200,
        )
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        with pytest.raises(ToolAPIError) as exc_info:
            await tool.poll_until(
                "https://api.example.com/poll",
                api_key="test-key",
                params={},
                success_check=lambda d: d.get("status") == "done",
                failure_check=lambda d: d.get("status") == "failed",
                extract=lambda d: d["result"],
                initial_delay=0.01,
                max_seconds=5,
            )
        assert "Task failed" in exc_info.value.message
        await client.aclose()

    @pytest.mark.asyncio
    async def test_poll_timeout_raises(self, httpx_mock):
        """poll_until raises ToolAPIError when max_seconds exceeded."""
        httpx_mock.add_response(
            url="https://api.example.com/poll",
            json={"status": "pending"},
            status_code=200,
        )
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        with pytest.raises(ToolAPIError) as exc_info:
            await tool.poll_until(
                "https://api.example.com/poll",
                api_key="test-key",
                params={},
                success_check=lambda d: d.get("status") == "done",
                failure_check=lambda d: False,
                extract=lambda d: d,
                initial_delay=0.05,
                max_seconds=0.1,
            )
        assert "timed out" in exc_info.value.message.lower()
        await client.aclose()


class TestAPIToolFormatForContext:
    def test_default_passes_through(self):
        """APITool inherits BaseTool's default format_for_context."""
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        result = ToolResult(success=True, data="raw api response")
        assert tool.format_for_context(result) == "raw api response"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_api_tool.py -v`
Expected: FAIL — `odigos.tools.api_tool` does not exist

- [ ] **Step 3: Check if pytest-httpx is available, install if needed**

Run: `cd /Users/jacob/Projects/odigos && python -c "import pytest_httpx; print('installed')" 2>/dev/null || uv pip install pytest-httpx`

The `httpx_mock` fixture comes from `pytest-httpx`. If it's not installed, add it as a dev dependency.

- [ ] **Step 4: Implement api_tool.py**

Create `odigos/tools/api_tool.py`:

```python
"""Base class for tools that call external HTTP APIs."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import httpx

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class ToolAPIError(Exception):
    """Raised when an external API returns an error."""

    def __init__(
        self,
        status_code: int,
        message: str,
        failure_category: str = "unknown",
    ):
        self.status_code = status_code
        self.message = message
        self.failure_category = failure_category
        super().__init__(message)


class APITool(BaseTool):
    """Base class for tools that call external HTTP APIs.

    Subclasses receive a shared httpx.AsyncClient from the Container
    and use api_post/api_get/poll_until instead of managing their own clients.
    """

    API_DOCS: str = ""

    def __init__(self, http: httpx.AsyncClient, **kwargs):
        self._http = http

    @property
    def http(self) -> httpx.AsyncClient:
        return self._http

    async def api_post(
        self,
        url: str,
        payload: dict,
        api_key: str,
        **kwargs,
    ) -> dict:
        """POST JSON with Bearer auth. Raises ToolAPIError on HTTP 4xx/5xx."""
        resp = await self.http.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            **kwargs,
        )
        data = resp.json()
        if resp.status_code >= 400:
            msg = data.get("msg") or data.get("error", "Unknown error")
            raise ToolAPIError(resp.status_code, msg)
        return data

    async def api_get(
        self,
        url: str,
        api_key: str,
        params: dict | None = None,
        **kwargs,
    ) -> dict:
        """GET with Bearer auth. Raises ToolAPIError on HTTP 4xx/5xx."""
        resp = await self.http.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            params=params,
            **kwargs,
        )
        data = resp.json()
        if resp.status_code >= 400:
            msg = data.get("msg") or data.get("error", "Unknown error")
            raise ToolAPIError(resp.status_code, msg)
        return data

    async def poll_until(
        self,
        url: str,
        api_key: str,
        params: dict,
        success_check: Callable[[dict], bool],
        failure_check: Callable[[dict], bool],
        extract: Callable[[dict], Any],
        max_seconds: float = 180,
        initial_delay: float = 5.0,
        max_delay: float = 15.0,
    ) -> Any:
        """Poll an API endpoint with exponential backoff.

        Returns extracted result on success. Raises ToolAPIError on
        failure or timeout.
        """
        delay = initial_delay
        elapsed = 0.0
        while elapsed < max_seconds:
            await asyncio.sleep(delay)
            elapsed += delay
            data = await self.api_get(url, api_key, params)
            if success_check(data):
                return extract(data)
            if failure_check(data):
                raise ToolAPIError(0, f"Task failed: {data}")
            delay = min(delay * 1.5, max_delay)
        raise ToolAPIError(0, "Polling timed out")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_api_tool.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add odigos/tools/api_tool.py tests/test_api_tool.py
git commit -m "feat(tools): add APITool base class with shared HTTP client"
```

---

### Task 3: CLITool base class

**Files:**
- Create: `odigos/tools/cli_tool.py`
- Create: `tests/test_cli_tool.py`

- [ ] **Step 1: Write tests for CLITool**

Create `tests/test_cli_tool.py`:

```python
import asyncio
import json

import pytest

from odigos.tools.cli_tool import (
    CLIResult,
    CLITool,
    CLIToolError,
    _classify_cli_error,
    _validate_cli_arg,
)
from odigos.tools.base import BaseTool, ToolResult


class FakeCLITool(CLITool):
    name = "fake_cli"
    description = "Test CLI tool"
    COMMAND = "echo"

    async def execute(self, params: dict) -> ToolResult:
        result = await self.run_cli([params.get("text", "hello")])
        return ToolResult(success=True, data=result.stdout)


class TestCLIToolError:
    def test_default_category(self):
        err = CLIToolError(1, "something failed")
        assert err.exit_code == 1
        assert err.stderr == "something failed"
        assert err.failure_category == "unknown"

    def test_custom_category(self):
        err = CLIToolError(126, "not executable", "unavailable")
        assert err.failure_category == "unavailable"


class TestCLIResult:
    def test_fields(self):
        r = CLIResult(exit_code=0, stdout="output", stderr="")
        assert r.exit_code == 0
        assert r.stdout == "output"
        assert r.stderr == ""


class TestValidateCLIArg:
    def test_clean_arg_passes(self):
        _validate_cli_arg("--output")
        _validate_cli_arg("file.txt")
        _validate_cli_arg("/home/user/file.txt")

    def test_path_traversal_rejected(self):
        with pytest.raises(CLIToolError) as exc_info:
            _validate_cli_arg("../../etc/passwd")
        assert exc_info.value.failure_category == "input"

    def test_null_byte_rejected(self):
        with pytest.raises(CLIToolError) as exc_info:
            _validate_cli_arg("file\x00.txt")
        assert exc_info.value.failure_category == "input"

    def test_backtick_rejected(self):
        with pytest.raises(CLIToolError) as exc_info:
            _validate_cli_arg("`rm -rf /`")
        assert exc_info.value.failure_category == "input"

    def test_subshell_rejected(self):
        with pytest.raises(CLIToolError) as exc_info:
            _validate_cli_arg("$(whoami)")
        assert exc_info.value.failure_category == "input"

    def test_newline_rejected(self):
        with pytest.raises(CLIToolError) as exc_info:
            _validate_cli_arg("arg\ninjected")
        assert exc_info.value.failure_category == "input"


class TestClassifyCLIError:
    def test_command_not_found(self):
        r = CLIResult(exit_code=127, stdout="", stderr="command not found")
        assert _classify_cli_error(r) == "unavailable"

    def test_not_executable(self):
        r = CLIResult(exit_code=126, stdout="", stderr="permission denied")
        assert _classify_cli_error(r) == "unavailable"

    def test_permission_error(self):
        r = CLIResult(exit_code=1, stdout="", stderr="Permission denied: /etc/shadow")
        assert _classify_cli_error(r) == "permission"

    def test_timeout_in_stderr(self):
        r = CLIResult(exit_code=1, stdout="", stderr="connection timed out")
        assert _classify_cli_error(r) == "transient"

    def test_unknown_error(self):
        r = CLIResult(exit_code=1, stdout="", stderr="something else")
        assert _classify_cli_error(r) == "unknown"


class TestCLIToolRunCli:
    @pytest.mark.asyncio
    async def test_run_echo(self):
        """run_cli executes a subprocess and captures output."""
        tool = FakeCLITool()
        result = await tool.run_cli(["hello world"])
        assert result.exit_code == 0
        assert "hello world" in result.stdout

    @pytest.mark.asyncio
    async def test_run_timeout(self):
        """run_cli raises CLIToolError on timeout."""
        tool = FakeCLITool()
        tool.COMMAND = "sleep"
        with pytest.raises(CLIToolError) as exc_info:
            await tool.run_cli(["10"], timeout=0.1)
        assert exc_info.value.failure_category == "transient"
        assert "Timed out" in exc_info.value.stderr

    @pytest.mark.asyncio
    async def test_run_rejects_dangerous_args(self):
        """run_cli validates args before execution."""
        tool = FakeCLITool()
        with pytest.raises(CLIToolError) as exc_info:
            await tool.run_cli(["../../etc/passwd"])
        assert exc_info.value.failure_category == "input"


class TestCLIToolRunJson:
    @pytest.mark.asyncio
    async def test_run_json_parses_output(self):
        """run_json parses JSON stdout."""
        tool = FakeCLITool()
        tool.COMMAND = "echo"
        result = await tool.run_json(['{"key": "value"}'])
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_run_json_raises_on_nonzero_exit(self):
        """run_json raises CLIToolError on non-zero exit code."""
        tool = FakeCLITool()
        tool.COMMAND = "false"
        with pytest.raises(CLIToolError):
            await tool.run_json([])


class TestCLIToolFormatForContext:
    def test_short_output_passes_through(self):
        tool = FakeCLITool()
        result = ToolResult(success=True, data="short output")
        assert tool.format_for_context(result) == "short output"

    def test_long_output_is_distilled(self):
        tool = FakeCLITool()
        long_data = "\n".join([f"line {i}" for i in range(200)])
        result = ToolResult(success=True, data=long_data)
        formatted = tool.format_for_context(result)
        assert len(formatted) < len(long_data)

    def test_inherits_from_base_tool(self):
        from odigos.tools.base import BaseTool
        tool = FakeCLITool()
        assert isinstance(tool, BaseTool)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_cli_tool.py -v`
Expected: FAIL — `odigos.tools.cli_tool` does not exist

- [ ] **Step 3: Implement cli_tool.py**

Create `odigos/tools/cli_tool.py`:

```python
"""Base class for tools that execute CLI commands in a subprocess."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class CLIToolError(Exception):
    """Raised when a CLI tool execution fails."""

    def __init__(
        self,
        exit_code: int,
        stderr: str,
        failure_category: str = "unknown",
    ):
        self.exit_code = exit_code
        self.stderr = stderr
        self.failure_category = failure_category
        super().__init__(stderr)


@dataclass
class CLIResult:
    """Output from a CLI subprocess execution."""

    exit_code: int
    stdout: str
    stderr: str


class CLITool(BaseTool):
    """Base class for tools that execute CLI commands in a subprocess.

    Subclasses set COMMAND to the base executable and implement execute()
    using run_cli() or run_json().
    """

    COMMAND: str = ""
    SANDBOX: str = "subprocess"  # "subprocess" | "docker" | "bubblewrap"
    SKILL_FILE: str = ""

    def __init__(
        self,
        working_dir: str = "",
        timeout: float = 60.0,
        allowed_paths: list[str] | None = None,
    ):
        self._working_dir = working_dir
        self._timeout = timeout
        self._allowed_paths = allowed_paths or []

    async def run_cli(
        self,
        args: list[str],
        stdin: str | None = None,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
    ) -> CLIResult:
        """Execute a CLI command in a subprocess.

        Returns CLIResult with stdout, stderr, exit_code.
        Raises CLIToolError on timeout or dangerous input.
        """
        timeout = timeout or self._timeout
        cmd = [self.COMMAND] + args

        for arg in args:
            _validate_cli_arg(arg)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if stdin else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._working_dir or None,
            env={**os.environ, **(env or {})},
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(stdin.encode() if stdin else None),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise CLIToolError(-1, f"Timed out after {timeout}s", "transient")

        return CLIResult(
            exit_code=proc.returncode,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
        )

    async def run_json(self, args: list[str], **kwargs) -> dict:
        """Run a CLI command and parse JSON output.

        Appends --output json if not already present.
        Raises CLIToolError on non-zero exit.
        """
        if "--output" not in args and "-o" not in args:
            args = args + ["--output", "json"]
        result = await self.run_cli(args, **kwargs)
        if result.exit_code != 0:
            raise CLIToolError(
                result.exit_code,
                result.stderr,
                _classify_cli_error(result),
            )
        return json.loads(result.stdout)

    def format_for_context(self, result: ToolResult) -> str:
        """CLI output is inherently verbose -- auto-distill by default."""
        if len(result.data) > 2000:
            from odigos.tools.base import auto_distill
            return auto_distill(result.data)
        return result.data


def _validate_cli_arg(arg: str) -> None:
    """Reject dangerous CLI arguments. Agents hallucinate."""
    if ".." in arg and ("/" in arg or "\\" in arg):
        raise CLIToolError(-1, f"Path traversal rejected: {arg}", "input")
    if any(c in arg for c in ("\x00", "\r", "\n", "`", "$(")):
        raise CLIToolError(
            -1, f"Dangerous characters in argument: {arg!r}", "input"
        )


def _classify_cli_error(result: CLIResult) -> str:
    """Map CLI exit codes and stderr to failure categories."""
    if result.exit_code in (126, 127):
        return "unavailable"
    if result.exit_code == 1 and "permission" in result.stderr.lower():
        return "permission"
    if "timeout" in result.stderr.lower() or "timed out" in result.stderr.lower():
        return "transient"
    return "unknown"


def _auto_distill(text: str) -> str:
    """Head-tail with signal extraction for verbose output."""
    signal_words = {"error", "exception", "fail", "warning", "traceback", "exit"}
    lines = text.splitlines()
    head = "\n".join(lines[:15])
    tail = "\n".join(lines[-15:])
    middle_signals = [
        line
        for line in lines[15:-15]
        if any(w in line.lower() for w in signal_words)
    ]
    mid = (
        "\n".join(middle_signals[:10]) if middle_signals else "[...truncated...]"
    )
    return f"{head}\n\n{mid}\n\n{tail}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_cli_tool.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add odigos/tools/cli_tool.py tests/test_cli_tool.py
git commit -m "feat(tools): add CLITool base class with input hardening and auto-distill"
```

---

### Task 4: Parameter validation and observation filtering in executor

**Files:**
- Modify: `odigos/core/executor.py`
- Create: `tests/test_executor_validation.py`

- [ ] **Step 1: Write tests for _coerce_and_validate**

Create `tests/test_executor_validation.py`:

```python
import pytest
import jsonschema

from odigos.core.executor import _coerce_and_validate


class TestCoerceAndValidate:
    def test_boolean_coercion_true(self):
        schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}}
        result = _coerce_and_validate({"flag": "true"}, schema)
        assert result["flag"] is True

    def test_boolean_coercion_false(self):
        schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}}
        result = _coerce_and_validate({"flag": "false"}, schema)
        assert result["flag"] is False

    def test_integer_coercion(self):
        schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
        result = _coerce_and_validate({"count": "42"}, schema)
        assert result["count"] == 42

    def test_number_coercion(self):
        schema = {"type": "object", "properties": {"rate": {"type": "number"}}}
        result = _coerce_and_validate({"rate": "3.14"}, schema)
        assert result["rate"] == 3.14

    def test_string_passthrough(self):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        result = _coerce_and_validate({"name": "hello"}, schema)
        assert result["name"] == "hello"

    def test_enum_validation_passes(self):
        schema = {
            "type": "object",
            "properties": {"ratio": {"type": "string", "enum": ["1:1", "4:3"]}},
        }
        result = _coerce_and_validate({"ratio": "1:1"}, schema)
        assert result["ratio"] == "1:1"

    def test_enum_validation_rejects(self):
        schema = {
            "type": "object",
            "properties": {"ratio": {"type": "string", "enum": ["1:1", "4:3"]}},
        }
        with pytest.raises(jsonschema.ValidationError):
            _coerce_and_validate({"ratio": "invalid"}, schema)

    def test_required_field_rejects(self):
        schema = {
            "type": "object",
            "properties": {"prompt": {"type": "string"}},
            "required": ["prompt"],
        }
        with pytest.raises(jsonschema.ValidationError):
            _coerce_and_validate({}, schema)

    def test_unknown_keys_pass_through(self):
        """Extra params not in schema are preserved (LLM may send extras)."""
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        result = _coerce_and_validate({"a": "ok", "b": "extra"}, schema)
        assert result["b"] == "extra"

    def test_does_not_mutate_original(self):
        schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}}
        original = {"flag": "true"}
        _coerce_and_validate(original, schema)
        assert original["flag"] == "true"

    def test_invalid_integer_caught_by_validation(self):
        schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
        with pytest.raises(jsonschema.ValidationError):
            _coerce_and_validate({"count": "not_a_number"}, schema)


```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_executor_validation.py -v`
Expected: FAIL — `_coerce_and_validate` not importable from executor

- [ ] **Step 3: Implement _coerce_and_validate in executor.py**

Add this function and import to the top of `odigos/core/executor.py` (after existing imports):

```python
import jsonschema
from odigos.tools.base import auto_distill


def _coerce_and_validate(params: dict, schema: dict) -> dict:
    """Coerce LLM string params to schema types, then validate constraints."""
    properties = schema.get("properties", {})
    coerced = dict(params)

    for key, spec in properties.items():
        if key not in coerced:
            continue
        val = coerced[key]
        if spec.get("type") == "boolean":
            coerced[key] = str(val).lower() == "true"
        elif spec.get("type") == "integer":
            try:
                coerced[key] = int(val)
            except (ValueError, TypeError):
                pass
        elif spec.get("type") == "number":
            try:
                coerced[key] = float(val)
            except (ValueError, TypeError):
                pass

    jsonschema.validate(coerced, schema)
    return coerced
```

Note: `auto_distill` is imported from `odigos.tools.base` (defined in Task 1), not redefined here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_executor_validation.py -v`
Expected: All PASS

- [ ] **Step 5: Integrate into _execute_tool method**

In `odigos/core/executor.py`, in the `_execute_tool` method, add validation before `tool.execute(args)` (around line 562, after `args = {**tool_call.arguments, ...}`):

Before the `while True:` retry loop, add:

```python
        # Parameter validation: strip internal params, coerce types, validate schema
        internal = {k: args.pop(k) for k in list(args) if k.startswith("_")}
        try:
            args = _coerce_and_validate(args, tool.parameters_schema)
        except jsonschema.ValidationError as e:
            logger.warning("Tool %s: invalid params: %s", tool_call.name, e.message)
            await self._emit_trace(
                conversation_id, "tool_result",
                {"tool": tool_call.name, "success": False, "error": f"Invalid parameters: {e.message}"},
            )
            return f"Error: Invalid parameters for {tool_call.name}: {e.message}"
        args.update(internal)
```

After the result is returned (around line 664, where `return result.data` is), replace the final return block:

```python
            if result.success:
                display = tool.format_for_context(result)
                if display == result.data and len(display) > 2000:
                    display = auto_distill(display)
                return display
            return f"Error: {result.error}"
```

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_executor_validation.py tests/test_tools.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add odigos/core/executor.py tests/test_executor_validation.py
git commit -m "feat(executor): add parameter validation and observation filtering"
```

---

### Task 5: Shared HTTP client on Container and Bootstrap

**Files:**
- Modify: `odigos/container.py`
- Modify: `odigos/bootstrap.py`

- [ ] **Step 1: Add http_client field to Container**

In `odigos/container.py`, add to the imports:

```python
if TYPE_CHECKING:
    import httpx
```

Add the field after `tool_registry` (in the Phase 5 section):

```python
    # Phase 5: Tools
    tool_registry: ToolRegistry | None = None
    http_client: httpx.AsyncClient | None = None
```

- [ ] **Step 2: Add shutdown for http_client**

In `odigos/container.py`, in the `shutdown` method, add before the `self.embeddings` cleanup (around line 128):

```python
        if self.http_client:
            await self.http_client.aclose()
```

- [ ] **Step 3: Create http_client in bootstrap Phase 1**

In `odigos/bootstrap.py`, in `init_database` (Phase 1), add after `ensure_dirs()` (around line 39):

```python
        import httpx
        self.container.http_client = httpx.AsyncClient(
            timeout=30,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
```

- [ ] **Step 4: Verify node --check equivalent (syntax check)**

Run: `cd /Users/jacob/Projects/odigos && python -c "from odigos.container import Container; print('OK')" && python -c "from odigos.bootstrap import Bootstrapper; print('OK')"`
Expected: Both print "OK"

- [ ] **Step 5: Commit**

```bash
git add odigos/container.py odigos/bootstrap.py
git commit -m "feat(infra): add shared httpx client to Container with lifecycle management"
```

---

### Task 6: Migrate image_gen to APITool

**Files:**
- Modify: `odigos/tools/image_gen.py`
- Modify: `odigos/bootstrap.py` (registration)

- [ ] **Step 1: Rewrite image_gen.py onto APITool base**

Replace the contents of `odigos/tools/image_gen.py`:

```python
"""Image generation via Kie.ai Z-Image API."""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import httpx

from odigos.tools.api_tool import APITool, ToolAPIError
from odigos.tools.base import ToolContract, ToolResult

logger = logging.getLogger(__name__)

KIE_BASE = "https://api.kie.ai/api/v1"
VALID_RATIOS = {"1:1", "4:3", "3:4", "16:9", "9:16"}


class GenerateImageTool(APITool):
    name = "generate_image"
    category = "create"
    contract = ToolContract(
        timeout_seconds=180,
        max_retries={"transient": 2, "input": 0, "permission": 0, "unavailable": 0, "unknown": 1},
    )
    description = (
        "Generate an image from a text description using Z-Image AI. "
        "Provide a detailed prompt describing the image you want. "
        "The prompt should include subject, setting, lighting, "
        "style, and composition details for best results. "
        "Supports aspect ratios: 1:1, 4:3, 3:4, 16:9, 9:16."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": (
                    "Detailed image description. Include subject, "
                    "setting, lighting, style, composition. "
                    "Max 1000 characters."
                ),
            },
            "aspect_ratio": {
                "type": "string",
                "enum": ["1:1", "4:3", "3:4", "16:9", "9:16"],
                "description": (
                    "Image aspect ratio: 1:1, 4:3, 3:4, 16:9, "
                    "or 9:16. Default: 1:1"
                ),
            },
        },
        "required": ["prompt"],
    }
    API_DOCS = "https://docs.kie.ai/api/z-image"

    def __init__(
        self,
        http: httpx.AsyncClient,
        api_key: str,
        default_ratio: str = "1:1",
        nsfw_filter: bool = True,
        max_poll_seconds: int = 120,
        output_dir: str = "",
        db=None,
    ):
        super().__init__(http=http)
        self._api_key = api_key
        self._default_ratio = default_ratio
        self._nsfw_filter = nsfw_filter
        self._max_poll = max_poll_seconds
        from odigos.storage import FILES_DIR
        self._output_dir = output_dir or str(FILES_DIR)
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        conversation_id = params.pop("_conversation_id", None)
        prompt = (params.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(success=False, data="", error="No prompt provided")

        if len(prompt) > 1000:
            prompt = prompt[:1000]

        ratio = params.get("aspect_ratio", self._default_ratio)
        if ratio not in VALID_RATIOS:
            ratio = self._default_ratio

        try:
            task_id = await self._create_task(prompt, ratio)
            image_url = await self._poll_result(task_id)

            artifact_id = uuid.uuid4().hex
            slug = re.sub(r"[^a-z0-9]+", "_", prompt[:60].lower()).strip("_")
            filename = f"{slug}_{artifact_id[:8]}.png"
            filepath = await self._download_image(image_url, filename)
            file_size = os.path.getsize(filepath)

            if self._db:
                now = datetime.now(timezone.utc).isoformat()
                await self._db.execute(
                    "INSERT INTO artifacts "
                    "(id, conversation_id, filename, content_type, "
                    "file_size, file_path, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (artifact_id, conversation_id, filename,
                     "image/png", file_size, filepath, now),
                )

            return ToolResult(
                success=True,
                data=f"Image generated: {filename} ({file_size} bytes)",
                side_effect={
                    "artifact": {
                        "id": artifact_id,
                        "filename": filename,
                        "content_type": "image/png",
                        "file_size": file_size,
                        "download_url": f"/api/artifacts/{artifact_id}/download",
                        "path": filepath,
                    }
                },
            )
        except ToolAPIError as e:
            logger.error("Image generation API error: %s", e.message)
            return ToolResult(
                success=False, data="", error=e.message,
                failure_category=e.failure_category,
            )
        except Exception as e:
            logger.error("Image generation failed: %s", e)
            return ToolResult(success=False, data="", error=str(e))

    async def _create_task(self, prompt: str, ratio: str) -> str:
        """Submit image generation task. Returns taskId."""
        data = await self.api_post(
            f"{KIE_BASE}/jobs/createTask",
            payload={
                "model": "z-image",
                "input": {
                    "prompt": prompt,
                    "aspect_ratio": ratio,
                    "nsfw_checker": self._nsfw_filter,
                },
            },
            api_key=self._api_key,
        )
        # Kie.ai returns HTTP 200 with code field for app-level status
        if data.get("code") != 200:
            raise ToolAPIError(0, data.get("msg", "Create task failed"), "transient")
        return data["data"]["taskId"]

    async def _poll_result(self, task_id: str) -> str:
        """Poll for task completion. Returns image URL."""
        return await self.poll_until(
            f"{KIE_BASE}/jobs/recordInfo",
            api_key=self._api_key,
            params={"taskId": task_id},
            success_check=lambda d: (
                d.get("code") == 200
                and d.get("data", {}).get("state") == "success"
            ),
            failure_check=lambda d: (
                d.get("code") == 200
                and d.get("data", {}).get("state") == "fail"
            ),
            extract=lambda d: json.loads(
                d["data"].get("resultJson", "{}")
            ).get("resultUrls", [None])[0],
            max_seconds=self._max_poll,
            initial_delay=2.0,
            max_delay=10.0,
        )

    async def _download_image(self, url: str, filename: str) -> str:
        """Download image and save to output directory."""
        os.makedirs(self._output_dir, exist_ok=True)
        filepath = os.path.join(self._output_dir, filename)

        resp = await self.http.get(url, timeout=httpx.Timeout(60))
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)

        logger.info("Downloaded image: %s (%d bytes)", filepath, os.path.getsize(filepath))
        return filepath

    def format_for_context(self, result: ToolResult) -> str:
        if result.success:
            return result.data  # already concise: "Image generated: file.png (N bytes)"
        return f"Image generation failed: {result.error}"
```

- [ ] **Step 2: Update bootstrap registration to pass http client**

In `odigos/bootstrap.py`, update `_register_media_tools` (around line 507):

Replace:
```python
            from odigos.tools.image_gen import GenerateImageTool
            registry.register(GenerateImageTool(
                api_key=kie_api_key,
                default_ratio=settings.image_generation.default_aspect_ratio,
                nsfw_filter=settings.image_generation.nsfw_filter,
                max_poll_seconds=settings.image_generation.max_poll_seconds,
                db=db,
            ))
```

With:
```python
            from odigos.tools.image_gen import GenerateImageTool
            registry.register(GenerateImageTool(
                http=self.container.http_client,
                api_key=kie_api_key,
                default_ratio=settings.image_generation.default_aspect_ratio,
                nsfw_filter=settings.image_generation.nsfw_filter,
                max_poll_seconds=settings.image_generation.max_poll_seconds,
                db=db,
            ))
```

- [ ] **Step 3: Verify syntax**

Run: `cd /Users/jacob/Projects/odigos && python -c "from odigos.tools.image_gen import GenerateImageTool; print('OK')"`
Expected: "OK"

- [ ] **Step 4: Commit**

```bash
git add odigos/tools/image_gen.py odigos/bootstrap.py
git commit -m "refactor(image_gen): migrate to APITool base class"
```

---

### Task 7: Migrate music_gen to APITool

**Files:**
- Modify: `odigos/tools/music_gen.py`
- Modify: `odigos/bootstrap.py` (registration)

- [ ] **Step 1: Rewrite music_gen.py onto APITool base**

Replace the contents of `odigos/tools/music_gen.py`:

```python
"""Music generation via Kie.ai Suno API."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

import httpx

from odigos.tools.api_tool import APITool, ToolAPIError
from odigos.tools.base import ToolContract, ToolResult

logger = logging.getLogger(__name__)

KIE_BASE = "https://api.kie.ai/api/v1"

FAILURE_STATES = {
    "CREATE_TASK_FAILED",
    "GENERATE_AUDIO_FAILED",
    "SENSITIVE_WORD_ERROR",
    "CALLBACK_EXCEPTION",
}


class GenerateMusicTool(APITool):
    name = "generate_music"
    category = "create"
    contract = ToolContract(
        timeout_seconds=240,
        max_retries={"transient": 2, "input": 0, "permission": 0, "unavailable": 0, "unknown": 1},
    )
    description = (
        "Generate a music track from lyrics or a description. "
        "Returns playable audio. For lyrics review before generating, "
        "write them to a notebook first and let the user edit."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Lyrics or description of the music to generate (max 5000 chars)",
            },
            "style": {
                "type": "string",
                "description": "Musical style/genre (e.g., 'indie folk, acoustic'). Max 1000 chars.",
            },
            "title": {
                "type": "string",
                "description": "Song title (max 80 chars)",
            },
            "instrumental": {
                "type": "boolean",
                "description": "Instrumental only, no vocals (default false)",
            },
            "vocal_gender": {
                "type": "string",
                "enum": ["", "m", "f"],
                "description": "Preferred vocal gender",
            },
        },
        "required": ["prompt"],
    }
    API_DOCS = "https://docs.kie.ai/suno-api/generate-music"

    def __init__(
        self,
        http: httpx.AsyncClient,
        api_key: str,
        model: str = "V5_5",
        max_poll_seconds: int = 180,
        output_dir: str = "",
        db=None,
    ):
        super().__init__(http=http)
        self._api_key = api_key
        self._model = model
        self._max_poll = max_poll_seconds
        from odigos.storage import FILES_DIR
        self._output_dir = output_dir or str(FILES_DIR)
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        conversation_id = params.pop("_conversation_id", None)
        prompt = (params.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(success=False, data="", error="No prompt provided")

        style = (params.get("style") or "").strip()[:1000]
        title = (params.get("title") or "").strip()[:80]
        # instrumental is now a bool (coerced by executor)
        instrumental = params.get("instrumental", False)
        if isinstance(instrumental, str):
            instrumental = instrumental.lower() == "true"
        vocal_gender = params.get("vocal_gender", "")
        if vocal_gender not in ("m", "f"):
            vocal_gender = ""

        try:
            task_id = await self._create_task(
                prompt=prompt, style=style, title=title,
                instrumental=instrumental, vocal_gender=vocal_gender,
            )
            tracks = await self._poll_result(task_id)

            artifacts = []
            for i, track in enumerate(tracks):
                audio_url = track.get("audio_url") or track.get("audioUrl", "")
                if not audio_url:
                    continue

                track_id = uuid.uuid4().hex
                track_title = track.get("title") or title or f"track_{i + 1}"
                safe_title = "".join(
                    c if c.isalnum() or c in "-_ " else ""
                    for c in track_title
                ).strip().replace(" ", "_")
                filename = f"{safe_title}_{track_id[:12]}.mp3"

                filepath = await self._download_audio(audio_url, filename)
                file_size = os.path.getsize(filepath)

                if self._db:
                    now = datetime.now(timezone.utc).isoformat()
                    await self._db.execute(
                        "INSERT INTO artifacts "
                        "(id, conversation_id, filename, content_type, "
                        "file_size, file_path, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (track_id, conversation_id, filename,
                         "audio/mpeg", file_size, filepath, now),
                    )

                artifacts.append({
                    "id": track_id,
                    "filename": filename,
                    "content_type": "audio/mpeg",
                    "file_size": file_size,
                    "download_url": f"/api/artifacts/{track_id}/download",
                    "path": filepath,
                    "title": track_title,
                    "duration": track.get("duration", 0),
                })

            if not artifacts:
                return ToolResult(
                    success=False, data="",
                    error="No audio tracks returned from generation",
                )

            summary_parts = []
            for art in artifacts:
                duration = art.get("duration", 0)
                dur_str = f" ({duration:.0f}s)" if duration else ""
                summary_parts.append(f"{art['filename']}{dur_str}")

            return ToolResult(
                success=True,
                data="Generated tracks: " + ", ".join(summary_parts),
                side_effect={"artifacts": artifacts},
            )
        except ToolAPIError as e:
            logger.error("Music generation API error: %s", e.message)
            return ToolResult(
                success=False, data="", error=e.message,
                failure_category=e.failure_category,
            )
        except Exception as e:
            logger.error("Music generation failed: %s", e)
            return ToolResult(success=False, data="", error=str(e))

    async def _create_task(
        self,
        prompt: str,
        style: str = "",
        title: str = "",
        instrumental: bool = False,
        vocal_gender: str = "",
    ) -> str:
        """Submit music generation task. Returns taskId."""
        custom_mode = bool(style or title)
        payload: dict = {
            "prompt": prompt[:5000],
            "model": self._model,
            "customMode": custom_mode,
            "instrumental": instrumental,
            "callBackUrl": "",
        }
        if custom_mode:
            if style:
                payload["style"] = style
            if title:
                payload["title"] = title
        if vocal_gender:
            payload["vocalGender"] = vocal_gender

        data = await self.api_post(
            f"{KIE_BASE}/generate",
            payload=payload,
            api_key=self._api_key,
        )
        if data.get("code") != 200:
            raise ToolAPIError(0, data.get("msg", "Create task failed"), "transient")
        return data["data"]["taskId"]

    async def _poll_result(self, task_id: str) -> list[dict]:
        """Poll for music generation completion. Returns track list."""
        raw = await self.poll_until(
            f"{KIE_BASE}/generate/record-info",
            api_key=self._api_key,
            params={"taskId": task_id},
            success_check=lambda d: (
                d.get("code") == 200
                and (d.get("data", {}).get("status") or d.get("data", {}).get("state", ""))
                == "SUCCESS"
            ),
            failure_check=lambda d: (
                d.get("code") == 200
                and (d.get("data", {}).get("status") or d.get("data", {}).get("state", ""))
                in FAILURE_STATES
            ),
            extract=lambda d: d.get("data", {}).get("response", {}),
            max_seconds=self._max_poll,
            initial_delay=5.0,
            max_delay=15.0,
        )
        return self._extract_tracks(raw)

    @staticmethod
    def _extract_tracks(response: object) -> list[dict]:
        """Extract audio tracks from API response."""
        if isinstance(response, list):
            return [t for t in response if isinstance(t, dict) and (t.get("audioUrl") or t.get("audio_url"))]
        if isinstance(response, dict):
            for value in response.values():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    tracks = [t for t in value if t.get("audioUrl") or t.get("audio_url")]
                    if tracks:
                        return tracks
        return []

    async def _download_audio(self, url: str, filename: str) -> str:
        """Download audio file and save to output directory."""
        from odigos import aio
        os.makedirs(self._output_dir, exist_ok=True)
        filepath = os.path.join(self._output_dir, filename)

        resp = await self.http.get(url, timeout=httpx.Timeout(120))
        resp.raise_for_status()
        await aio.write_bytes(filepath, resp.content)

        logger.info("Downloaded audio: %s (%d bytes)", filepath, os.path.getsize(filepath))
        return filepath

    def format_for_context(self, result: ToolResult) -> str:
        if result.success:
            return result.data  # already concise: "Generated tracks: file1.mp3, file2.mp3"
        return f"Music generation failed: {result.error}"
```

Note the key change: `instrumental` field in `parameters_schema` is now `"type": "boolean"` instead of `"type": "string", "enum": ["true", "false"]`. The executor's `_coerce_and_validate` handles the string-to-bool conversion, so the tool receives a real Python `bool`. The defensive `isinstance` check in `execute()` handles the transition period.

- [ ] **Step 2: Update bootstrap registration to pass http client**

In `odigos/bootstrap.py`, update the music_gen registration (around line 518):

Replace:
```python
            from odigos.tools.music_gen import GenerateMusicTool
            registry.register(GenerateMusicTool(
                api_key=kie_api_key,
                model=settings.music_generation.model,
                max_poll_seconds=settings.music_generation.max_poll_seconds,
                db=db,
            ))
```

With:
```python
            from odigos.tools.music_gen import GenerateMusicTool
            registry.register(GenerateMusicTool(
                http=self.container.http_client,
                api_key=kie_api_key,
                model=settings.music_generation.model,
                max_poll_seconds=settings.music_generation.max_poll_seconds,
                db=db,
            ))
```

- [ ] **Step 3: Verify syntax**

Run: `cd /Users/jacob/Projects/odigos && python -c "from odigos.tools.music_gen import GenerateMusicTool; print('OK')"`
Expected: "OK"

- [ ] **Step 4: Commit**

```bash
git add odigos/tools/music_gen.py odigos/bootstrap.py
git commit -m "refactor(music_gen): migrate to APITool base class"
```

---

### Task 8: Add jsonschema to explicit dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Check current jsonschema version**

Run: `cd /Users/jacob/Projects/odigos && uv pip show jsonschema 2>/dev/null | grep Version`

- [ ] **Step 2: Add jsonschema to pyproject.toml dependencies**

Add `"jsonschema>=4.0"` to the `dependencies` list in `pyproject.toml`. Even though it's currently a transitive dependency, making it explicit ensures it won't disappear if an upstream package drops it.

- [ ] **Step 3: Verify install**

Run: `cd /Users/jacob/Projects/odigos && uv sync`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add jsonschema as explicit dependency"
```

---

### Task 9: Full integration verification

- [ ] **Step 1: Run complete test suite**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x -q`
Expected: All tests pass

- [ ] **Step 2: Verify imports chain**

Run:
```bash
cd /Users/jacob/Projects/odigos && python -c "
from odigos.tools.base import BaseTool, ToolResult
from odigos.tools.api_tool import APITool, ToolAPIError
from odigos.tools.cli_tool import CLITool, CLIToolError, CLIResult
from odigos.core.executor import _coerce_and_validate
from odigos.tools.base import auto_distill
print('All imports OK')
print(f'APITool bases: {[c.__name__ for c in APITool.__mro__]}')
print(f'CLITool bases: {[c.__name__ for c in CLITool.__mro__]}')
print(f'ToolResult fields: {[f.name for f in ToolResult.__dataclass_fields__.values()]}')
"
```

Expected:
```
All imports OK
APITool bases: ['APITool', 'BaseTool', 'ABC', 'object']
CLITool bases: ['CLITool', 'BaseTool', 'ABC', 'object']
ToolResult fields: ['success', 'data', 'error', 'side_effect', 'failure_category', 'status', 'task_id']
```

- [ ] **Step 3: Verify no ruff lint issues**

Run: `cd /Users/jacob/Projects/odigos && ruff check odigos/tools/api_tool.py odigos/tools/cli_tool.py odigos/tools/base.py odigos/tools/image_gen.py odigos/tools/music_gen.py odigos/core/executor.py`
Expected: No errors (or only pre-existing ones)

- [ ] **Step 4: Final commit if any lint fixes needed**

```bash
git add -A
git commit -m "fix: lint cleanup for tool foundation"
```
