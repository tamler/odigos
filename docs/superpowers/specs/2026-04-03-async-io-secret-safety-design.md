# Async I/O Safety & Secret Handling Hardening

**Date:** 2026-04-03
**Status:** Draft
**Goal:** Eliminate synchronous blocking I/O in async context and close secret exposure gaps.

## Problem

1. **Sync file I/O in async functions.** Multiple route handlers and bootstrap code call `open()`, `yaml.safe_load()`, `yaml.dump()`, `Path.read_text()`, `shutil.rmtree()` directly inside async functions. This blocks the event loop and stalls all concurrent requests while disk I/O completes. The codebase already uses `asyncio.to_thread` correctly in some places (embeddings init, email IMAP tests, CalDAV tests) but misses many others.

2. **Secrets exposed in API responses.** The GET /api/settings endpoint masks `llm_api_key`, `api_key`, and `services` keys, but returns `email.password` unmasked. Error messages from IMAP/SMTP/CalDAV connection tests are returned raw to the client and may contain auth details.

## Design

### 1. Async File I/O Wrapper

Create a small helper module that wraps common sync file operations:

```python
# odigos/aio.py
import asyncio
from pathlib import Path
from typing import Any

import yaml


async def read_text(path: str | Path) -> str:
    return await asyncio.to_thread(Path(path).read_text)


async def write_text(path: str | Path, content: str) -> None:
    await asyncio.to_thread(Path(path).write_text, content)


async def read_yaml(path: str | Path) -> dict:
    def _read():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return await asyncio.to_thread(_read)


async def write_yaml(path: str | Path, data: dict) -> None:
    def _write():
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)
    await asyncio.to_thread(_write)


async def append_text(path: str | Path, content: str) -> None:
    def _append():
        with open(path, "a") as f:
            f.write(content)
    await asyncio.to_thread(_append)


async def remove_tree(path: str | Path) -> None:
    import shutil
    await asyncio.to_thread(shutil.rmtree, str(path))


async def write_bytes(path: str | Path, data: bytes) -> None:
    def _write():
        with open(path, "wb") as f:
            f.write(data)
    await asyncio.to_thread(_write)
```

### 2. Files to Migrate

| File | Lines | Current | Fix |
|------|-------|---------|-----|
| `odigos/bootstrap.py` | init_database ~77 | `open(.env, "a")` | `aio.append_text` |
| `odigos/bootstrap.py` | _persist_generated_api_key | `open(config) + yaml.safe_load/dump` | `aio.read_yaml / aio.write_yaml` |
| `odigos/bootstrap.py` | _seed_user | `_seed_path.read_text()` | `aio.read_text` |
| `odigos/api/settings.py` | update_settings_endpoint | `open(config) + yaml` x2 | `aio.read_yaml / aio.write_yaml` |
| `odigos/api/settings.py` | apply_profile | `open(config) + yaml` x2 | `aio.read_yaml / aio.write_yaml` |
| `odigos/api/settings.py` | _update_env_file | `open(.env) + readlines/writelines` | `aio.read_text / aio.write_text` |
| `odigos/api/plugins.py` | configure_plugin | `open(config) + yaml` x2 | `aio.read_yaml / aio.write_yaml` |
| `odigos/api/upload.py` | upload_file | `open(dest, "wb")` | `aio.write_bytes` |
| `odigos/api/artifacts.py` | get_artifact_content | `file_path.read_text()` | `aio.read_text` |
| `odigos/api/artifacts.py` | update_artifact_content | `file_path.write_text()` | `aio.write_text` |
| `odigos/api/artifacts.py` | get_thumbnail | `Image.open()` | `asyncio.to_thread` |
| `odigos/api/artifacts.py` | delete_artifact | `shutil.rmtree()` | `aio.remove_tree` |

### 3. Secret Masking Fixes

**GET /api/settings response:**

Current code (settings.py:51-71) masks `llm_api_key`, `api_key`, and `services` but returns `email` unmasked. Fix:

```python
# Mask sensitive fields in email config
email_data = settings.email.model_dump()
for key in ("password",):
    if email_data.get(key):
        email_data[key] = "****"

# Mask sensitive fields in voice config
voice_data = settings.voice.model_dump()
for key in ("api_key",):
    if voice_data.get(key):
        voice_data[key] = "****"
```

**Error message sanitization for connection tests:**

The IMAP/SMTP/CalDAV test endpoints return raw exception strings. These could contain server hostnames, auth error details, or protocol-level information. Fix:

```python
# Instead of: return str(exc)
# Use a sanitizer that strips credentials from error messages

def _sanitize_error(exc: Exception) -> str:
    """Return error message with potential credentials stripped."""
    msg = str(exc)
    # Strip anything that looks like a credential in the error
    # Common patterns: "LOGIN failed", "Authentication failed for user@host"
    # Truncate to 200 chars max
    return msg[:200]
```

This is acceptable since these are admin-only endpoints behind auth. The main risk is accidental logging or display of passwords in IMAP auth error messages. Truncation to 200 chars (already done for CalDAV) should be applied uniformly.

### 4. Pydantic SecretStr for Sensitive Fields

Mark sensitive config fields with `SecretStr` so they don't accidentally serialize:

```python
from pydantic import SecretStr

class EmailConfig(BaseModel):
    password: SecretStr = SecretStr("")

class Settings(BaseSettings):
    llm_api_key: SecretStr = SecretStr("")
    api_key: SecretStr = SecretStr("")
    session_secret: SecretStr = SecretStr("")
```

This requires updating all code that reads these values to call `.get_secret_value()`. It's a larger change but prevents accidental serialization in logs, responses, or debug output.

**Decision:** Skip SecretStr for now. The masking in the settings endpoint is sufficient, and SecretStr would require touching every consumer. Can revisit if we add structured logging.

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `odigos/aio.py` | Create | Async file I/O wrapper functions |
| `odigos/bootstrap.py` | Modify | Replace sync file I/O with aio.* calls |
| `odigos/api/settings.py` | Modify | Async file I/O + mask email password + sanitize errors |
| `odigos/api/plugins.py` | Modify | Async file I/O for config read/write |
| `odigos/api/upload.py` | Modify | Async file write for uploads |
| `odigos/api/artifacts.py` | Modify | Async file read/write/delete + thumbnail |

## Migration Strategy

1. Create `odigos/aio.py` helper module
2. Migrate bootstrap.py (startup path, highest impact)
3. Migrate settings.py (most file I/O, plus secret masking fixes)
4. Migrate remaining route handlers (plugins, upload, artifacts)
5. Run full test suite

## What This Does NOT Change

- Config file format (still YAML)
- API response shapes (except email.password now masked)
- .env file format
- Settings update behavior
- Test fixtures (they don't do real file I/O)
