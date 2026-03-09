# Google Workspace Integration Design

**Date:** 2026-03-09
**Status:** Approved
**Phase:** 4

## Context

Phase 4 calls for Google integration (Gmail, Calendar, Drive). Instead of building OAuth2 + API wrappers for each service, we use the `gws` CLI (`@googleworkspace/cli`) which provides a single interface to all Google Workspace APIs with dynamic discovery, structured JSON output, and built-in auth.

## Decisions

1. **Single `run_gws` tool** -- One tool that takes a raw `gws` command string and executes it. Preserves dynamic API discovery, zero maintenance as APIs change.
2. **Direct subprocess** -- `asyncio.create_subprocess_exec("gws", ...)` with timeout. No sandbox -- `gws` needs real filesystem (credentials) and network (Google APIs).
3. **Manual auth** -- `gws auth setup` + `gws auth login` done once on the server. No auth logic in our code.
4. **Skill-based guidance** -- `google-workspace` skill provides `gws` command reference. Agent activates it when handling Google-related requests.
5. **Config-driven enablement** -- `gws.enabled` flag in config.yaml. Startup checks if `gws` is on PATH when enabled.

## Components

### 1. GWSTool (`odigos/tools/gws.py`)

```python
class GWSTool(BaseTool):
    name = "run_gws"
    # execute(): shlex.split(command), asyncio.create_subprocess_exec("gws", *args),
    # capture stdout/stderr, return JSON output
    # Handles: FileNotFoundError (not installed), TimeoutError (kill + error),
    # non-zero exit (return stderr as error)
```

Parameters: `command` (required string). Timeout configurable (default 30s).

### 2. Skill (`data/skills/google-workspace.md`)

Provides `gws` command patterns for Gmail, Calendar, Drive, Sheets. Includes discovery commands (`gws schema ...`) so the agent can learn new APIs at runtime. Tools: `[run_gws]`.

### 3. Config (`odigos/config.py`)

```python
class GWSSettings:
    enabled: bool = False
    timeout: int = 30
```

### 4. Wiring (`odigos/main.py`)

When `settings.gws.enabled`:
1. Check `gws` on PATH via `shutil.which("gws")`
2. If found: register `GWSTool`, log success
3. If not found: log warning with install instructions, skip registration

### 5. Testing

- **TestGWSTool** -- mock subprocess: successful command, failure, missing param, gws not found, timeout, tool metadata
- **TestGWSConfig** -- config parsing with gws.enabled flag
- **TestGWSSkill** -- skill file loads correctly with proper frontmatter
