# Hook/Plugin Lifecycle Design

**Date:** 2026-03-09
**Status:** Approved
**Phase:** 3, item #5

## Context

The trace system (`Tracer.emit()`) fires structured events at every agent decision point. This feature adds a hook/plugin layer on top of the tracer so plugins can subscribe to those events and run custom logic.

## Decisions

1. **Hooks subscribe to trace events** -- `Tracer.emit()` gains a subscriber list. No separate dispatch system.
2. **Explicit registration** -- Plugins export a `hooks` dict mapping event type strings to async callables.
3. **Synchronous with timeout** -- Hooks run inline during `emit()`, each wrapped in `asyncio.wait_for` with a 5-second timeout. On timeout or exception, log warning and continue.
4. **Startup loading** -- `PluginManager` scans `data/plugins/*.py` at startup. `reload()` method allows rescanning without restart.
5. **All 10 event types** -- `step_start`, `tool_call`, `tool_result`, `response`, `reflection`, `correction_detected`, `entity_extracted`, `heartbeat_tick`, `timeout`, `budget_exceeded`.
6. **Sample plugin** -- `log_tools.py` ships as a template and validation.

## Components

### 1. Tracer subscriber mechanism (`odigos/core/trace.py`)

Tracer gains:
- `_subscribers: dict[str, list[Callable]]` -- event type to list of async callbacks
- `subscribe(event_type, callback)` -- adds a subscriber
- `clear_subscribers()` -- for reload support
- `emit()` updated: after DB insert, iterates subscribers, calls each with `asyncio.wait_for(cb(event_type, conversation_id, data), timeout=5.0)`

### 2. Plugin manager (`odigos/core/plugins.py`)

New `PluginManager` class:
- `load_all(plugins_dir)` -- scans `*.py`, imports via `importlib.util`, extracts `hooks` dict, calls `tracer.subscribe()`
- `reload()` -- clears subscribers, invalidates `sys.modules` cache, rescans
- Creates `data/plugins/` if it doesn't exist
- Errors during import or missing `hooks` dict: log and skip

### 3. Hook callback signature

```python
async def callback(event_type: str, conversation_id: str | None, data: dict) -> None
```

### 4. Event types and data

| Event | Data fields |
|-------|-------------|
| `step_start` | `message_preview` |
| `tool_call` | `tool`, `arguments`, `active_skill`? |
| `tool_result` | `tool`, `success`, `error`, `duration_ms`, `active_skill`? |
| `response` | `model`, `tokens_in`, `tokens_out`, `cost_usd` |
| `reflection` | `conversation_id` |
| `correction_detected` | `category` |
| `entity_extracted` | `count` |
| `heartbeat_tick` | `did_work` |
| `timeout` | `conversation_id` |
| `budget_exceeded` | `conversation_id` |

### 5. Sample plugin (`data/plugins/log_tools.py`)

```python
import logging

logger = logging.getLogger("plugin.log_tools")

async def on_tool_call(event_type, conversation_id, data):
    logger.info("Tool called: %s args=%s", data.get("tool"), data.get("arguments"))

async def on_tool_result(event_type, conversation_id, data):
    logger.info("Tool result: %s success=%s duration=%sms",
                data.get("tool"), data.get("success"), data.get("duration_ms"))

hooks = {
    "tool_call": on_tool_call,
    "tool_result": on_tool_result,
}
```

### 6. Wiring (`odigos/main.py`)

After Tracer creation, create PluginManager with tracer reference, call `load_all("data/plugins")`.

### 7. Testing

- **TestTracerSubscribers** -- subscribe, emit, verify callback args. Timeout handling. Exception handling. clear_subscribers.
- **TestPluginManager** -- load from temp dir, verify registration. Missing hooks skipped. Import errors skipped. Reload. Empty dir.
- **TestPluginManagerIntegration** -- load plugin, emit event, verify callback ran.
- **TestSamplePlugin** -- import log_tools, verify hooks dict, call callbacks.
