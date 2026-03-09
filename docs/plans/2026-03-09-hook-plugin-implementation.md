# Hook/Plugin Lifecycle Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a hook/plugin system that lets plugins subscribe to trace events and run custom logic inline.

**Architecture:** Hooks are a subscriber layer on `Tracer.emit()`. Plugins are Python files in `data/plugins/` that export a `hooks` dict mapping event types to async callables. A `PluginManager` loads plugins at startup and registers their hooks with the Tracer. Each hook call is wrapped in a 5-second timeout.

**Tech Stack:** Python 3.12, asyncio, importlib, pytest

**Design doc:** `docs/plans/2026-03-09-hook-plugin-design.md`

---

### Task 1: Add subscriber mechanism to Tracer

**Files:**
- Modify: `odigos/core/trace.py`
- Modify: `tests/test_trace.py`

**Context:** The `Tracer` class currently has one method `emit()` that inserts a row into the `traces` table. We need to add subscriber support so hooks can be notified when events fire.

**Step 1: Write the failing tests**

Add a new `TestTracerSubscribers` class to `tests/test_trace.py`:

```python
class TestTracerSubscribers:
    async def test_subscribe_receives_event(self, db):
        tracer = Tracer(db)
        received = []

        async def callback(event_type, conversation_id, data):
            received.append((event_type, conversation_id, data))

        tracer.subscribe("step_start", callback)
        await _seed_conversation(db, "conv-1")
        await tracer.emit("step_start", "conv-1", {"msg": "hi"})

        assert len(received) == 1
        assert received[0][0] == "step_start"
        assert received[0][1] == "conv-1"
        assert received[0][2]["msg"] == "hi"

    async def test_subscribe_only_matching_events(self, db):
        tracer = Tracer(db)
        received = []

        async def callback(event_type, conversation_id, data):
            received.append(event_type)

        tracer.subscribe("tool_call", callback)
        await _seed_conversation(db, "conv-1")
        await tracer.emit("step_start", "conv-1", {})
        await tracer.emit("tool_call", "conv-1", {})

        assert received == ["tool_call"]

    async def test_multiple_subscribers(self, db):
        tracer = Tracer(db)
        received_a = []
        received_b = []

        async def cb_a(event_type, conversation_id, data):
            received_a.append(event_type)

        async def cb_b(event_type, conversation_id, data):
            received_b.append(event_type)

        tracer.subscribe("response", cb_a)
        tracer.subscribe("response", cb_b)
        await _seed_conversation(db, "conv-1")
        await tracer.emit("response", "conv-1", {})

        assert len(received_a) == 1
        assert len(received_b) == 1

    async def test_subscriber_timeout(self, db):
        tracer = Tracer(db)

        async def slow_callback(event_type, conversation_id, data):
            await asyncio.sleep(10)

        tracer.subscribe("step_start", slow_callback)
        await _seed_conversation(db, "conv-1")
        # Should not hang -- timeout after 5s
        await asyncio.wait_for(
            tracer.emit("step_start", "conv-1", {}),
            timeout=7,
        )
        # Row still inserted despite subscriber timeout
        row = await db.fetch_one("SELECT * FROM traces WHERE event_type = 'step_start'")
        assert row is not None

    async def test_subscriber_exception_continues(self, db):
        tracer = Tracer(db)
        received = []

        async def bad_callback(event_type, conversation_id, data):
            raise RuntimeError("hook exploded")

        async def good_callback(event_type, conversation_id, data):
            received.append("ok")

        tracer.subscribe("response", bad_callback)
        tracer.subscribe("response", good_callback)
        await _seed_conversation(db, "conv-1")
        await tracer.emit("response", "conv-1", {})

        # Second subscriber still ran
        assert received == ["ok"]

    async def test_clear_subscribers(self, db):
        tracer = Tracer(db)
        received = []

        async def callback(event_type, conversation_id, data):
            received.append(event_type)

        tracer.subscribe("step_start", callback)
        tracer.clear_subscribers()
        await _seed_conversation(db, "conv-1")
        await tracer.emit("step_start", "conv-1", {})

        assert received == []
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_trace.py::TestTracerSubscribers -v`
Expected: FAIL (subscribe/clear_subscribers methods don't exist)

**Step 3: Implement subscriber mechanism in Tracer**

Modify `odigos/core/trace.py`. The full file should become:

```python
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from typing import Callable

from odigos.db import Database

logger = logging.getLogger(__name__)

HOOK_TIMEOUT = 5.0


class Tracer:
    """Structured event tracing with DB persistence and hook subscribers."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """Register a hook callback for an event type."""
        self._subscribers[event_type].append(callback)

    def clear_subscribers(self) -> None:
        """Remove all hook subscribers."""
        self._subscribers.clear()

    async def emit(
        self,
        event_type: str,
        conversation_id: str | None,
        data: dict,
    ) -> str:
        """Emit a trace event. Returns the trace ID."""
        trace_id = str(uuid.uuid4())
        try:
            await self.db.execute(
                "INSERT INTO traces (id, conversation_id, event_type, data_json) "
                "VALUES (?, ?, ?, ?)",
                (trace_id, conversation_id, event_type, json.dumps(data)),
            )
        except Exception:
            logger.debug("Failed to emit trace", exc_info=True)

        # Notify subscribers
        for callback in self._subscribers.get(event_type, []):
            try:
                await asyncio.wait_for(
                    callback(event_type, conversation_id, data),
                    timeout=HOOK_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Hook timed out for event %s: %s", event_type, callback
                )
            except Exception:
                logger.warning(
                    "Hook failed for event %s: %s", event_type, callback,
                    exc_info=True,
                )

        return trace_id
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_trace.py -v`
Expected: ALL PASS (both existing TestTracer tests and new TestTracerSubscribers tests)

**Step 5: Commit**

```bash
git add odigos/core/trace.py tests/test_trace.py
git commit -m "feat: add hook subscriber mechanism to Tracer"
```

---

### Task 2: Create PluginManager

**Files:**
- Create: `odigos/core/plugins.py`
- Create: `tests/test_plugins.py`

**Context:** The `PluginManager` scans a directory for `.py` files, imports each, extracts a `hooks` dict, and registers callbacks with the Tracer. It also supports `reload()` to rescan without restart.

**Step 1: Write the failing tests**

Create `tests/test_plugins.py`:

```python
import asyncio
import json
import logging
from unittest.mock import AsyncMock

import pytest

from odigos.core.plugins import PluginManager
from odigos.core.trace import Tracer
from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path: str):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


def _write_plugin(plugins_dir, name, content):
    """Write a plugin .py file to the plugins directory."""
    path = plugins_dir / f"{name}.py"
    path.write_text(content)
    return path


class TestPluginManager:
    async def test_load_plugin_registers_hooks(self, db, tmp_path):
        tracer = Tracer(db)
        _write_plugin(tmp_path, "my_plugin", '''
import logging
logger = logging.getLogger("test_plugin")

async def on_tool_call(event_type, conversation_id, data):
    logger.info("tool called")

hooks = {"tool_call": on_tool_call}
''')

        manager = PluginManager(tracer=tracer)
        manager.load_all(str(tmp_path))

        assert len(tracer._subscribers["tool_call"]) == 1

    async def test_load_multiple_plugins(self, db, tmp_path):
        tracer = Tracer(db)
        _write_plugin(tmp_path, "plugin_a", '''
async def on_step(event_type, conversation_id, data):
    pass

hooks = {"step_start": on_step}
''')
        _write_plugin(tmp_path, "plugin_b", '''
async def on_response(event_type, conversation_id, data):
    pass

hooks = {"response": on_response}
''')

        manager = PluginManager(tracer=tracer)
        manager.load_all(str(tmp_path))

        assert len(tracer._subscribers["step_start"]) == 1
        assert len(tracer._subscribers["response"]) == 1

    async def test_skip_file_without_hooks(self, db, tmp_path):
        tracer = Tracer(db)
        _write_plugin(tmp_path, "no_hooks", 'x = 42')

        manager = PluginManager(tracer=tracer)
        manager.load_all(str(tmp_path))

        assert len(manager.loaded_plugins) == 0

    async def test_skip_file_with_import_error(self, db, tmp_path):
        tracer = Tracer(db)
        _write_plugin(tmp_path, "broken", 'import nonexistent_module_xyz')

        manager = PluginManager(tracer=tracer)
        manager.load_all(str(tmp_path))

        assert len(manager.loaded_plugins) == 0

    async def test_skip_non_dict_hooks(self, db, tmp_path):
        tracer = Tracer(db)
        _write_plugin(tmp_path, "bad_hooks", 'hooks = "not a dict"')

        manager = PluginManager(tracer=tracer)
        manager.load_all(str(tmp_path))

        assert len(manager.loaded_plugins) == 0

    async def test_skip_non_callable_hook(self, db, tmp_path):
        tracer = Tracer(db)
        _write_plugin(tmp_path, "bad_callable", 'hooks = {"step_start": "not callable"}')

        manager = PluginManager(tracer=tracer)
        manager.load_all(str(tmp_path))

        # Plugin loaded but the non-callable hook was skipped
        assert len(tracer._subscribers.get("step_start", [])) == 0

    async def test_empty_directory(self, db, tmp_path):
        tracer = Tracer(db)
        manager = PluginManager(tracer=tracer)
        manager.load_all(str(tmp_path))

        assert len(manager.loaded_plugins) == 0

    async def test_creates_directory_if_missing(self, db, tmp_path):
        tracer = Tracer(db)
        plugins_dir = tmp_path / "plugins"
        assert not plugins_dir.exists()

        manager = PluginManager(tracer=tracer)
        manager.load_all(str(plugins_dir))

        assert plugins_dir.exists()

    async def test_skips_dunder_files(self, db, tmp_path):
        tracer = Tracer(db)
        _write_plugin(tmp_path, "__init__", 'hooks = {"step_start": lambda *a: None}')
        _write_plugin(tmp_path, "__pycache__", 'hooks = {"step_start": lambda *a: None}')

        manager = PluginManager(tracer=tracer)
        manager.load_all(str(tmp_path))

        assert len(manager.loaded_plugins) == 0

    async def test_reload_clears_and_reloads(self, db, tmp_path):
        tracer = Tracer(db)
        _write_plugin(tmp_path, "my_plugin", '''
async def on_step(event_type, conversation_id, data):
    pass

hooks = {"step_start": on_step}
''')

        manager = PluginManager(tracer=tracer)
        manager.load_all(str(tmp_path))
        assert len(tracer._subscribers["step_start"]) == 1

        # Add a second plugin
        _write_plugin(tmp_path, "plugin_two", '''
async def on_resp(event_type, conversation_id, data):
    pass

hooks = {"response": on_resp}
''')

        manager.reload()
        # Both plugins loaded, old subscribers cleared first
        assert len(tracer._subscribers["step_start"]) == 1
        assert len(tracer._subscribers["response"]) == 1

    async def test_loaded_plugins_metadata(self, db, tmp_path):
        tracer = Tracer(db)
        _write_plugin(tmp_path, "my_plugin", '''
async def on_step(event_type, conversation_id, data):
    pass

async def on_resp(event_type, conversation_id, data):
    pass

hooks = {"step_start": on_step, "response": on_resp}
''')

        manager = PluginManager(tracer=tracer)
        manager.load_all(str(tmp_path))

        assert len(manager.loaded_plugins) == 1
        plugin_info = manager.loaded_plugins[0]
        assert plugin_info["name"] == "my_plugin"
        assert plugin_info["hook_count"] == 2


class TestPluginManagerIntegration:
    async def test_plugin_receives_trace_event(self, db, tmp_path):
        tracer = Tracer(db)
        _write_plugin(tmp_path, "collector", '''
collected = []

async def on_tool_call(event_type, conversation_id, data):
    collected.append({"event": event_type, "tool": data.get("tool")})

hooks = {"tool_call": on_tool_call}
''')

        manager = PluginManager(tracer=tracer)
        manager.load_all(str(tmp_path))

        await tracer.emit("tool_call", "conv-1", {"tool": "web_search"})

        # Access collected data from the loaded module
        import sys
        mod = sys.modules.get("odigos_plugin_collector")
        assert mod is not None
        assert len(mod.collected) == 1
        assert mod.collected[0]["tool"] == "web_search"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_plugins.py -v`
Expected: FAIL (`odigos.core.plugins` does not exist)

**Step 3: Implement PluginManager**

Create `odigos/core/plugins.py`:

```python
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

from odigos.core.trace import Tracer

logger = logging.getLogger(__name__)


class PluginManager:
    """Loads plugins from a directory and registers their hooks with a Tracer."""

    def __init__(self, tracer: Tracer) -> None:
        self.tracer = tracer
        self.loaded_plugins: list[dict] = []
        self._plugins_dir: str | None = None
        self._module_names: list[str] = []

    def load_all(self, plugins_dir: str) -> None:
        """Scan plugins_dir for .py files, import each, register hooks."""
        self._plugins_dir = plugins_dir
        path = Path(plugins_dir)
        path.mkdir(parents=True, exist_ok=True)

        self.loaded_plugins = []

        for py_file in sorted(path.glob("*.py")):
            if py_file.stem.startswith("__"):
                continue
            self._load_plugin(py_file)

    def reload(self) -> None:
        """Clear all subscribers and reload plugins from the same directory."""
        if not self._plugins_dir:
            return

        self.tracer.clear_subscribers()

        # Remove cached modules
        for mod_name in self._module_names:
            sys.modules.pop(mod_name, None)
        self._module_names.clear()

        self.load_all(self._plugins_dir)

    def _load_plugin(self, py_file: Path) -> None:
        """Import a single plugin file and register its hooks."""
        module_name = f"odigos_plugin_{py_file.stem}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                logger.warning("Cannot load plugin: %s", py_file)
                return
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception:
            logger.warning("Failed to import plugin: %s", py_file.name, exc_info=True)
            return

        self._module_names.append(module_name)

        hooks = getattr(module, "hooks", None)
        if not isinstance(hooks, dict):
            if hooks is not None:
                logger.warning("Plugin %s: 'hooks' is not a dict, skipping", py_file.name)
            else:
                logger.debug("Plugin %s: no 'hooks' attribute, skipping", py_file.name)
            return

        hook_count = 0
        for event_type, callback in hooks.items():
            if not callable(callback):
                logger.warning(
                    "Plugin %s: hook for '%s' is not callable, skipping",
                    py_file.name, event_type,
                )
                continue
            self.tracer.subscribe(event_type, callback)
            hook_count += 1

        self.loaded_plugins.append({
            "name": py_file.stem,
            "file": str(py_file),
            "hook_count": hook_count,
        })
        logger.info("Loaded plugin: %s (%d hooks)", py_file.stem, hook_count)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_plugins.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add odigos/core/plugins.py tests/test_plugins.py
git commit -m "feat: add PluginManager for loading hook plugins"
```

---

### Task 3: Create sample plugin

**Files:**
- Create: `data/plugins/log_tools.py`

**Context:** This sample plugin logs every `tool_call` and `tool_result` event. It validates the system works end-to-end and serves as a template.

**Step 1: Create the sample plugin**

Create `data/plugins/log_tools.py`:

```python
"""Sample plugin: logs tool call and result events.

This plugin demonstrates the hook system. Each plugin exports a `hooks` dict
mapping event type strings to async callback functions.

Callback signature: async def callback(event_type, conversation_id, data) -> None
"""
import logging

logger = logging.getLogger("plugin.log_tools")


async def on_tool_call(event_type, conversation_id, data):
    logger.info(
        "[%s] Tool called: %s args=%s",
        conversation_id, data.get("tool"), data.get("arguments"),
    )


async def on_tool_result(event_type, conversation_id, data):
    logger.info(
        "[%s] Tool result: %s success=%s duration=%sms",
        conversation_id, data.get("tool"), data.get("success"), data.get("duration_ms"),
    )


hooks = {
    "tool_call": on_tool_call,
    "tool_result": on_tool_result,
}
```

**Step 2: Write a test for the sample plugin**

Add to `tests/test_plugins.py`:

```python
class TestSamplePlugin:
    def test_hooks_dict_exists(self):
        """The sample plugin has a valid hooks dict."""
        spec = importlib.util.spec_from_file_location(
            "log_tools_test", "data/plugins/log_tools.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert isinstance(module.hooks, dict)
        assert "tool_call" in module.hooks
        assert "tool_result" in module.hooks
        assert callable(module.hooks["tool_call"])
        assert callable(module.hooks["tool_result"])

    async def test_callbacks_run_without_error(self):
        """The sample plugin callbacks execute without raising."""
        spec = importlib.util.spec_from_file_location(
            "log_tools_test2", "data/plugins/log_tools.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        await module.hooks["tool_call"]("tool_call", "conv-1", {"tool": "search", "arguments": {"q": "test"}})
        await module.hooks["tool_result"]("tool_result", "conv-1", {"tool": "search", "success": True, "duration_ms": 150})
```

Add `import importlib.util` to the imports at the top of `tests/test_plugins.py`.

**Step 3: Run tests**

Run: `pytest tests/test_plugins.py::TestSamplePlugin -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add data/plugins/log_tools.py tests/test_plugins.py
git commit -m "feat: add sample log_tools plugin"
```

---

### Task 4: Wire PluginManager into main.py

**Files:**
- Modify: `odigos/main.py:25-63`

**Context:** After the Tracer is created in `main.py`, we create a `PluginManager`, call `load_all("data/plugins")`, and log the result.

**Step 1: Add import and wiring**

In `odigos/main.py`, add import:

```python
from odigos.core.plugins import PluginManager
```

After the tracer initialization block (after line 63 `logger.info("Tracer initialized")`), add:

```python
    # Load plugins
    plugin_manager = PluginManager(tracer=tracer)
    plugin_manager.load_all("data/plugins")
    logger.info("Loaded %d plugins", len(plugin_manager.loaded_plugins))
```

**Step 2: Run the full test suite**

Run: `pytest tests/ -v --ignore=tests/test_mcp_bridge.py`
Expected: ALL PASS (no regressions)

**Step 3: Commit**

```bash
git add odigos/main.py
git commit -m "feat: wire PluginManager into startup"
```

---

### Task 5: Run all tests and verify

**Files:**
- None (verification only)

**Step 1: Run the full test suite**

Run: `pytest tests/ -v --ignore=tests/test_mcp_bridge.py`
Expected: ALL PASS

**Step 2: Verify sample plugin loads**

Run: `python -c "from odigos.core.plugins import PluginManager; from odigos.core.trace import Tracer; print('imports ok')"`
Expected: `imports ok`
