# Capability Audit: Pre-Release Cleanup

**Date:** 2026-03-12
**Status:** Approved

## Context

Audit of all tools and capabilities to ensure the agent has the minimum valuable set before v1. Target: a configurable base for power users (A) with a simple "just works" experience for others (B). Opt-in capabilities should move to plugins; core capabilities should be complete.

## 1. File Read/Write Tool

New tool `FileTool` in `odigos/tools/file.py` with three operations: `read`, `write`, `list`.

### Config

```yaml
file_access:
  allowed_paths:
    - "data/files"    # default sandbox
    # - "~/notes"     # user adds more
```

### Sandboxing

Every path resolved to absolute, checked against `allowed_paths`. Symlink traversal blocked (resolve real path before checking). Paths outside allowed dirs rejected with clear error. `data/files/` always allowed even if config is empty.

### Operations

- `read_file(path)` — returns text file contents, rejects binary
- `write_file(path, content)` — creates/overwrites, creates parent dirs within allowed paths
- `list_files(path)` — lists directory contents with sizes

Tool is always registered (core utility).

## 2. Conversation Export

### Endpoint

`GET /api/conversations/{id}/export?format=markdown`

### Formats

- `markdown` (default) — human-readable with timestamps and role labels
- `json` — raw messages array with full metadata

Includes all messages ordered by timestamp, conversation title in header. No summary/vector data.

### Dashboard

Export button on conversation view, triggers browser download.

## 3. Dead Code Cleanup

### Remove

- `odigos/core/peers.py` — old `PeerClient`, fully replaced by `AgentClient`
- `tests/test_peer_client.py` — dead tests
- `tests/test_peer_dedup.py` — dead tests

### Fix

- `odigos/tools/peer.py` — update type hint from `PeerClient` to `AgentClient`

## 4. Plugin Conversion

Move four opt-in capabilities from main.py into self-contained plugins.

### Plugins

| Plugin | Contents | Config gate |
|---|---|---|
| `plugins/telegram/` | TelegramChannel setup + registration | `telegram_bot_token` |
| `plugins/searxng/` | SearxngProvider + SearchTool registration | `searxng_url` |
| `plugins/gws/` | GWSTool registration + CLI check | `gws.enabled` |
| `plugins/browser/` | BrowserTool registration + CLI check | `browser.enabled` |

### Pattern

Each plugin implements `register(ctx: PluginContext)`. Checks its own config gate, registers tools/channels, logs result. Same pattern as existing Docling plugin.

### PluginContext

Pass `settings` through the existing `config` dict so plugins can check their own config gates.

### main.py Cleanup

Remove ~80 lines of conditional import/init/register blocks. Core wiring only remains: Database, LLM, Memory, Agent, Evolution, Heartbeat, Web channel, MCP bridge.

## Audit Summary

### Core (always present)
Agent loop, Memory system (hybrid search), Evolution engine, Heartbeat, Goals/Todos/Reminders, Skills, Web channel, Document processing, Code execution, Web scraping, File read/write, LLM/Router/Budget, Plugin system, Personality, Subagents, API, Approval gate

### Opt-in (plugins)
Telegram, SearXNG search, Google Workspace, Browser automation, MCP servers (stays in core as generic extension), Docling (already a plugin)

### Removed
PeerClient (dead code, replaced by AgentClient)

### Future Path
RSS Feed tool as lightweight ingest alternative to full agent mesh networking
