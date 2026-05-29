# Tool Catalog with Gate Metadata — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an authoritative catalog of every tool that exists in the codebase (with declarative gate metadata), so the skill validator can distinguish "tool doesn't exist" (a real bug) from "tool exists but isn't active this run" (fine), making the 2026-08-01 skill-validation hard-fail safe.

**Architecture:** A `ToolGate` dataclass declares each tool's enabling condition (default `ALWAYS`). `BaseTool` gains a `gate` class attr. `build_catalog()` walks `BaseTool.__subclasses__()` and returns `{name: gate}`. Three consumers: the skill validator (replaces a fragile hardcoded allowlist), the find_tools coverage test, and a new catalog-integrity test with a bidirectional drift guard. Gates are pure metadata — tool registration is unchanged.

**Tech Stack:** Python 3.12, dataclasses, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-29-tool-catalog-design.md`

**Test command throughout:** `.venv/bin/python -m pytest <path> -p no:cacheprovider -q`
(The repo's pytest lives in `.venv/bin/python`; the bare `python3` is Xcode's and lacks pytest.)

---

## File Structure

- **Create** `odigos/tools/gate.py` — `ToolGate` dataclass + `ALWAYS` + convenience constructors. ~45 lines. Sole responsibility: declare what makes a tool active and describe it.
- **Create** `odigos/tools/catalog.py` — `build_catalog()` (walk subclasses → `{name: gate}`), memoized, raises on name collision. ~55 lines.
- **Modify** `odigos/tools/base.py` — add `gate: ToolGate = ALWAYS` class attr to `BaseTool`.
- **Modify** `odigos/tools/subprocess_tool.py` — read `tool_name` from the class `name` attr when not passed, so subclasses can declare `name` as a class attr.
- **Modify** `odigos/tools/gws.py`, `odigos/tools/browser.py` — add class-level `name` + `gate`.
- **Modify** ~14 conditional tool files — add `gate = ToolGate.<kind>(...)` class attr.
- **Modify** `odigos/bootstrap.py` — rewrite `validate_skill_tools()` to use the catalog + env override; drop `_PLUGIN_PROVIDED_TOOL_NAMES`.
- **Create** `tests/test_tool_catalog.py` — builder correctness, name uniqueness, gate-key resolution, bidirectional drift guard.
- **Modify** `tests/test_find_tools_coverage.py` — assert every catalog entry is discoverable.

---

## Task 1: ToolGate dataclass

**Files:**
- Create: `odigos/tools/gate.py`
- Test: `tests/test_tool_catalog.py` (created here, extended later)

- [ ] **Step 1: Write the failing test**

Create `tests/test_tool_catalog.py`:

```python
"""Tests for the tool gate model and catalog (spec 2026-05-29)."""
from odigos.tools.gate import ALWAYS, ToolGate


def test_always_gate_describe():
    assert ALWAYS.kind == "always"
    assert ALWAYS.describe() == "always available"


def test_convenience_constructors():
    assert ToolGate.plugin("gws") == ToolGate("plugin", "gws")
    assert ToolGate.service("kie_ai") == ToolGate("service", "kie_ai")
    assert ToolGate.config("search_provider") == ToolGate("config", "search_provider")


def test_describe_strings():
    assert "gws plugin" in ToolGate.plugin("gws").describe()
    assert "kie_ai service" in ToolGate.service("kie_ai").describe()
    assert "search_provider" in ToolGate.config("search_provider").describe()


def test_gate_is_frozen_hashable():
    # frozen dataclass -> usable in sets/dicts, equal by value
    s = {ToolGate.plugin("gws"), ToolGate.plugin("gws")}
    assert len(s) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_tool_catalog.py -p no:cacheprovider -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'odigos.tools.gate'`

- [ ] **Step 3: Write the implementation**

Create `odigos/tools/gate.py`:

```python
"""Declarative tool gate metadata (spec 2026-05-29-tool-catalog).

A ToolGate describes what must be true for a tool to register/activate.
It is PURE METADATA — it does not control registration (tools register
exactly as they do today via bootstrap guards + plugins). The catalog and
skill validator use it to distinguish 'tool is missing' from 'tool exists
but is inactive this run', and to explain why a tool is inactive.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ToolGate:
    kind: Literal["always", "plugin", "service", "config"] = "always"
    key: str = ""  # e.g. "gws", "kie_ai", "search_provider"

    def describe(self) -> str:
        if self.kind == "always":
            return "always available"
        if self.kind == "plugin":
            return f"requires the {self.key} plugin (enabled + its CLI installed)"
        if self.kind == "service":
            return f"requires the {self.key} service key"
        if self.kind == "config":
            return f"requires {self.key} to be configured"
        return self.kind

    @staticmethod
    def plugin(key: str) -> "ToolGate":
        return ToolGate("plugin", key)

    @staticmethod
    def service(key: str) -> "ToolGate":
        return ToolGate("service", key)

    @staticmethod
    def config(key: str) -> "ToolGate":
        return ToolGate("config", key)


ALWAYS = ToolGate("always")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_tool_catalog.py -p no:cacheprovider -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add odigos/tools/gate.py tests/test_tool_catalog.py
git commit -m "feat(tools): ToolGate declarative gate metadata (catalog task 1)"
```

---

## Task 2: BaseTool gains a gate attr

**Files:**
- Modify: `odigos/tools/base.py`
- Test: `tests/test_tool_catalog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tool_catalog.py`:

```python
def test_basetool_has_default_always_gate():
    from odigos.tools.base import BaseTool
    from odigos.tools.gate import ALWAYS
    assert BaseTool.gate is ALWAYS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_tool_catalog.py::test_basetool_has_default_always_gate -p no:cacheprovider -q`
Expected: FAIL with `AttributeError: type object 'BaseTool' has no attribute 'gate'`

- [ ] **Step 3: Write the implementation**

In `odigos/tools/base.py`, add the import near the top (after the existing `from dataclasses import ...` line):

```python
from odigos.tools.gate import ALWAYS, ToolGate
```

Then in the `BaseTool` class body, add the `gate` attr right after `name`:

```python
class BaseTool(ABC):
    name: str
    gate: ToolGate = ALWAYS  # declarative enabling condition; see odigos/tools/gate.py
    description: str
    category: str = ""  # One of the CATEGORY_* constants
    parameters_schema: dict = {"type": "object", "properties": {}}
    contract: ToolContract = ToolContract()
```

Note: confirm no circular import — `gate.py` imports only stdlib, so `base.py` importing `gate` is safe.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_tool_catalog.py -p no:cacheprovider -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the existing tool tests to confirm no import breakage**

Run: `.venv/bin/python -m pytest tests/test_kanban_tools.py tests/test_text_analysis.py -p no:cacheprovider -q`
Expected: PASS (no import errors from the new base.py import)

- [ ] **Step 6: Commit**

```bash
git add odigos/tools/base.py tests/test_tool_catalog.py
git commit -m "feat(tools): BaseTool.gate class attr, default ALWAYS (catalog task 2)"
```

---

## Task 3: Class-level name for the 2 subprocess tools

**Files:**
- Modify: `odigos/tools/subprocess_tool.py:14-41`
- Modify: `odigos/tools/gws.py`
- Modify: `odigos/tools/browser.py`
- Test: `tests/test_tool_catalog.py`, `tests/test_gws.py`

Currently `SubprocessTool.__init__` sets `self.name = tool_name` (instance attr); the class has no `name`. We make the class attr the source of truth so the catalog can read it without instantiation, while keeping `tool_name=` working.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tool_catalog.py`:

```python
def test_subprocess_tools_have_class_level_name():
    # run_gws / run_browser must declare name as a CLASS attr (not just set in
    # __init__) so the catalog can read it without instantiating (and without
    # importing the optional CLI deps).
    from odigos.tools.gws import GWSTool
    from odigos.tools.browser import BrowserTool
    assert GWSTool.name == "run_gws"
    assert BrowserTool.name == "run_browser"
    from odigos.tools.gate import ToolGate
    assert GWSTool.gate == ToolGate.plugin("gws")
    assert BrowserTool.gate == ToolGate.plugin("browser")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_tool_catalog.py::test_subprocess_tools_have_class_level_name -p no:cacheprovider -q`
Expected: FAIL — `GWSTool.name` is the abstract annotation, not `"run_gws"` (AttributeError or annotation object).

- [ ] **Step 3: Make SubprocessTool default tool_name to the class attr**

Read `odigos/tools/subprocess_tool.py` around lines 14-41. The `__init__` signature has `tool_name: str` (required) and does `self.name = tool_name`. Change `tool_name` to optional, defaulting to the class-level `name` when present:

```python
    def __init__(
        self,
        binary_name: str,
        tool_name: str | None = None,
        description: str = "",
        ...
    ) -> None:
        # Prefer an explicitly-passed tool_name; otherwise use the class-level
        # `name` attr (set by subclasses so the catalog can read it statically).
        resolved = tool_name or getattr(type(self), "name", None)
        if not resolved:
            raise ValueError("SubprocessTool requires tool_name= or a class-level name attr")
        self.name = resolved
        ...
```

(Keep all other constructor logic identical — only the `tool_name` resolution changes. Match the file's existing parameter names and order; the snippet above shows only the changed lines plus enough context.)

- [ ] **Step 4: Add class-level name + gate to GWSTool**

In `odigos/tools/gws.py`, add `name` and `gate` as class attributes and drop the now-redundant `tool_name=` (optional — leaving it is harmless, but removing avoids duplication):

```python
from odigos.tools.gate import ToolGate
from odigos.tools.subprocess_tool import SubprocessTool

_GWS_ALLOWED_SUBCOMMANDS = { ... }  # unchanged


class GWSTool(SubprocessTool):
    """Execute Google Workspace commands via the gws CLI."""

    name = "run_gws"
    gate = ToolGate.plugin("gws")

    def __init__(self, timeout: int = 30) -> None:
        super().__init__(
            binary_name="gws",
            description=(
                "Run a Google Workspace CLI command. Supports Gmail, Calendar, Drive, "
                "Sheets, and all other Workspace APIs. Pass the gws subcommand and arguments. "
                "Example: drive files list --params '{\"pageSize\": 5}'"
            ),
            default_timeout=timeout,
            allowed_subcommands=_GWS_ALLOWED_SUBCOMMANDS,
            install_hint="npm install -g @googleworkspace/cli",
        )
```

- [ ] **Step 5: Add class-level name + gate to BrowserTool**

Read `odigos/tools/browser.py` first to match its constructor exactly. Add:

```python
from odigos.tools.gate import ToolGate
```

and in the class body:

```python
class BrowserTool(SubprocessTool):
    name = "run_browser"
    gate = ToolGate.plugin("browser")

    def __init__(self, timeout: int = ...) -> None:
        super().__init__(
            binary_name="agent-browser",
            # tool_name no longer required — class attr provides it
            ...
        )
```

(Remove the `tool_name="run_browser"` arg from the `super().__init__` call, keeping everything else identical to the current file.)

- [ ] **Step 6: Run the catalog test + gws test**

Run: `.venv/bin/python -m pytest tests/test_tool_catalog.py tests/test_gws.py -p no:cacheprovider -q`
Expected: PASS (test_gws still 13/13 — its `test_tool_metadata` asserts `tool.name == "run_gws"`, which still holds after instantiation)

- [ ] **Step 7: Commit**

```bash
git add odigos/tools/subprocess_tool.py odigos/tools/gws.py odigos/tools/browser.py tests/test_tool_catalog.py
git commit -m "refactor(tools): class-level name+gate for run_gws/run_browser (catalog task 3)"
```

---

## Task 4: Annotate the conditional core tools with gates

**Files:** (add a `gate = ToolGate.<...>` class attr to each)
- Modify: `odigos/tools/peer.py` (`MessagePeerTool` → `config("mesh.enabled")`)
- Modify: `odigos/tools/opencli.py` (`WebPlatformTool` → `config("opencli")`)
- Modify: `odigos/tools/audio_process.py` (`ProcessAudioTool` → `config("ffmpeg")`)
- Modify: `odigos/tools/image_gen.py` (`GenerateImageTool` → `service("kie_ai")`)
- Modify: `odigos/tools/music_gen.py` (`GenerateMusicTool` → `service("kie_ai")`)
- Modify: `odigos/tools/feed_publish.py` (`PublishToFeedTool` → `config("feed.enabled")`)
- Modify: `odigos/tools/calendar.py` (`CheckCalendarTool`, `CreateCalendarEventTool`, `FindFreeTimeTool` → `config("calendar.url")`)
- Modify: `odigos/tools/email.py` (`CheckEmailTool`, `SearchEmailTool`, `ReadEmailTool`, `SendEmailTool` → `config("email.imap_host")`)
- Modify: `odigos/tools/search.py` (`SearchTool` → `config("search_provider")`)
- Test: `tests/test_tool_catalog.py`

Note on gate `kind`: only `kie_ai` is a service-key (`service_key("kie_ai")`). Everything else is a config/environment flag — use `config(...)` with the literal condition string the bootstrap guard uses (`mesh.enabled`, `feed.enabled`, `calendar.url`, `email.imap_host`, `search_provider`, `opencli`, `ffmpeg`). `gws`/`browser` are `plugin(...)` (done in Task 3). STT/TTS plugin tools (`speak`, `transcribe_audio`) are handled in Task 5.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tool_catalog.py`:

```python
import pytest

# Expected gate per conditional tool name. Always-on tools are intentionally
# omitted (they inherit ALWAYS). Keep this in sync with bootstrap guards —
# the drift guard test (Task 7) enforces the sync.
EXPECTED_GATES = {
    "message_peer":         ("config", "mesh.enabled"),
    "web_platform":         ("config", "opencli"),
    "process_audio":        ("config", "ffmpeg"),
    "generate_image":       ("service", "kie_ai"),
    "generate_music":       ("service", "kie_ai"),
    "publish_to_feed":      ("config", "feed.enabled"),
    "check_calendar":       ("config", "calendar.url"),
    "create_calendar_event":("config", "calendar.url"),
    "find_free_time":       ("config", "calendar.url"),
    "check_email":          ("config", "email.imap_host"),
    "search_email":         ("config", "email.imap_host"),
    "read_email":           ("config", "email.imap_host"),
    "send_email":           ("config", "email.imap_host"),
    "web_search":           ("config", "search_provider"),
    "run_gws":              ("plugin",  "gws"),
    "run_browser":          ("plugin",  "browser"),
    "speak":                ("plugin",  "tts"),
    "transcribe_audio":     ("plugin",  "stt"),
}


@pytest.mark.parametrize("tool_name,expected", list(EXPECTED_GATES.items()))
def test_conditional_tool_has_expected_gate(tool_name, expected):
    from odigos.tools.catalog import build_catalog
    catalog = build_catalog()
    assert tool_name in catalog, f"{tool_name} missing from catalog"
    gate = catalog[tool_name]
    assert (gate.kind, gate.key) == expected
```

(This test will fail to import `build_catalog` until Task 6 — that's fine; it's also exercised then. To check Task 4 in isolation, temporarily assert directly on the classes, e.g. `from odigos.tools.image_gen import GenerateImageTool; assert GenerateImageTool.gate == ToolGate.service("kie_ai")`. Optional.)

- [ ] **Step 2: Add the gate attr to each tool class**

For each file/class above, add `from odigos.tools.gate import ToolGate` (if not present) and a class attr. Example for `image_gen.py`:

```python
class GenerateImageTool(APITool):
    name = "generate_image"
    gate = ToolGate.service("kie_ai")
    category = "create"
    ...
```

Example for `email.py` (all four classes get the same gate):

```python
class CheckEmailTool(BaseTool):
    name = "check_email"
    gate = ToolGate.config("email.imap_host")
    ...
```

Apply the same pattern to every (class → gate) pair in EXPECTED_GATES that lives in a core tools file (all except `speak`/`transcribe_audio`, done in Task 5, and `run_gws`/`run_browser`, done in Task 3).

- [ ] **Step 3: Verify class-level gates (pre-catalog spot check)**

Run a quick inline check (catalog not built yet):

```bash
.venv/bin/python -c "
from odigos.tools.image_gen import GenerateImageTool
from odigos.tools.email import CheckEmailTool
from odigos.tools.search import SearchTool
from odigos.tools.gate import ToolGate
assert GenerateImageTool.gate == ToolGate.service('kie_ai')
assert CheckEmailTool.gate == ToolGate.config('email.imap_host')
assert SearchTool.gate == ToolGate.config('search_provider')
print('gates OK')
"
```
Expected: `gates OK`

- [ ] **Step 4: Commit**

```bash
git add odigos/tools/peer.py odigos/tools/opencli.py odigos/tools/audio_process.py odigos/tools/image_gen.py odigos/tools/music_gen.py odigos/tools/feed_publish.py odigos/tools/calendar.py odigos/tools/email.py odigos/tools/search.py tests/test_tool_catalog.py
git commit -m "feat(tools): annotate conditional core tools with gates (catalog task 4)"
```

---

## Task 5: Gate the STT/TTS plugin tools

**Files:**
- Modify: `odigos/tools/speak.py` (`SpeakTool` → `plugin("tts")`)
- Modify: `odigos/tools/transcribe.py` (`TranscribeAudioTool` → `plugin("stt")`)

`SpeakTool` (`odigos/tools/speak.py`, name `speak`) and `TranscribeAudioTool` (`odigos/tools/transcribe.py`, name `transcribe_audio`) are registered by `plugins/tts` and `plugins/stt` (gated on `settings.tts.enabled` / `settings.stt.enabled`). They live in `odigos/tools/` and import cleanly, so they're catalog-visible. Gate them as `plugin("tts")` / `plugin("stt")` to match the plugin that registers them.

- [ ] **Step 1: Add the gate attrs**

In each file, add `from odigos.tools.gate import ToolGate` and the class attr:

```python
class SpeakTool(BaseTool):
    name = "speak"
    gate = ToolGate.plugin("tts")
    ...

class TranscribeAudioTool(BaseTool):
    name = "transcribe_audio"
    gate = ToolGate.plugin("stt")
    ...
```

- [ ] **Step 2: Verify**

```bash
.venv/bin/python -c "
from odigos.tools.speak import SpeakTool
from odigos.tools.transcribe import TranscribeAudioTool
from odigos.tools.gate import ToolGate
assert SpeakTool.gate == ToolGate.plugin('tts')
assert TranscribeAudioTool.gate == ToolGate.plugin('stt')
print('stt/tts gates OK')
"
```
Expected: `stt/tts gates OK`

- [ ] **Step 3: Commit**

```bash
git add -A odigos/tools/
git commit -m "feat(tools): gate speak/transcribe_audio as plugin tts/stt (catalog task 5)"
```

---

## Task 6: build_catalog()

**Files:**
- Create: `odigos/tools/catalog.py`
- Test: `tests/test_tool_catalog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tool_catalog.py`:

```python
def test_build_catalog_includes_core_and_conditional_tools():
    from odigos.tools.catalog import build_catalog
    catalog = build_catalog()
    # Spot-check always-on, service-gated, config-gated, plugin-gated:
    assert "read_page" in catalog
    assert "generate_image" in catalog
    assert "check_email" in catalog
    assert "run_gws" in catalog
    assert "run_browser" in catalog
    # Reasonable lower bound (66 static + 2 subprocess = 68; allow growth):
    assert len(catalog) >= 60


def test_build_catalog_is_memoized():
    from odigos.tools.catalog import build_catalog
    assert build_catalog() is build_catalog()


def test_build_catalog_rejects_name_collision(monkeypatch):
    # Two concrete BaseTool subclasses with the same name must raise.
    import odigos.tools.catalog as cat
    from odigos.tools.base import BaseTool, ToolResult

    class _Dup1(BaseTool):
        name = "dup_collide_xyz"
        async def execute(self, params: dict) -> ToolResult:  # pragma: no cover
            return ToolResult(success=True, data="")

    class _Dup2(BaseTool):
        name = "dup_collide_xyz"
        async def execute(self, params: dict) -> ToolResult:  # pragma: no cover
            return ToolResult(success=True, data="")

    cat.reset_catalog_cache()
    with pytest.raises(ValueError, match="dup_collide_xyz"):
        cat.build_catalog()
    cat.reset_catalog_cache()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_tool_catalog.py::test_build_catalog_includes_core_and_conditional_tools -p no:cacheprovider -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'odigos.tools.catalog'`

- [ ] **Step 3: Write the implementation**

Create `odigos/tools/catalog.py`:

```python
"""Authoritative catalog of every tool that exists in the codebase.

Independent of what registered this boot — built by walking BaseTool
subclasses and reading their (name, gate) class attrs. See spec
docs/superpowers/specs/2026-05-29-tool-catalog-design.md.

Import safety: imports only the CORE odigos.tools package so its tool
classes register with the interpreter. It does NOT import plugins/* (they
pull optional third-party deps that may be absent). Plugin-gated tools whose
classes live in odigos.tools (run_gws, run_browser, speak, transcribe_audio,
generate_image, ...) are still visible because their modules import cleanly.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil

from odigos.tools.base import BaseTool
from odigos.tools.gate import ToolGate

logger = logging.getLogger(__name__)

_CACHE: dict[str, ToolGate] | None = None


def _import_all_tool_modules() -> None:
    """Import every module in odigos.tools so all BaseTool subclasses exist."""
    import odigos.tools as tools_pkg
    for mod in pkgutil.iter_modules(tools_pkg.__path__):
        if mod.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"odigos.tools.{mod.name}")
        except Exception as e:  # optional deps in a tool module — skip, log
            logger.debug("catalog: skipping odigos.tools.%s (%s)", mod.name, e)


def _walk_subclasses(cls: type) -> list[type]:
    out: list[type] = []
    for sub in cls.__subclasses__():
        out.append(sub)
        out.extend(_walk_subclasses(sub))
    return out


def build_catalog() -> dict[str, ToolGate]:
    """Return {tool_name: gate} for every concrete tool class. Memoized.

    Raises ValueError on a duplicate tool name (two classes claiming the
    same name is always a bug)."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    _import_all_tool_modules()
    catalog: dict[str, ToolGate] = {}
    for cls in _walk_subclasses(BaseTool):
        name = cls.__dict__.get("name")  # class's OWN name, not inherited
        if not isinstance(name, str) or not name:
            continue  # abstract intermediate (APITool, SubprocessTool, ...)
        gate = getattr(cls, "gate", None)
        if not isinstance(gate, ToolGate):
            from odigos.tools.gate import ALWAYS
            gate = ALWAYS
        if name in catalog:
            raise ValueError(f"Duplicate tool name in catalog: {name!r}")
        catalog[name] = gate

    _CACHE = catalog
    return _CACHE


def reset_catalog_cache() -> None:
    """Clear the memoized catalog (tests only)."""
    global _CACHE
    _CACHE = None
```

Note on `cls.__dict__.get("name")`: this reads the class's OWN `name`, so a subclass that doesn't redefine `name` (an abstract base) is correctly skipped rather than inheriting a parent's name.

- [ ] **Step 4: Run the catalog tests**

Run: `.venv/bin/python -m pytest tests/test_tool_catalog.py -p no:cacheprovider -q`
Expected: PASS — including the parametrized `EXPECTED_GATES` cases from Task 4 and the collision test.

- [ ] **Step 5: Commit**

```bash
git add odigos/tools/catalog.py tests/test_tool_catalog.py
git commit -m "feat(tools): build_catalog() walks BaseTool subclasses, memoized (catalog task 6)"
```

---

## Task 7: Catalog integrity — gate-key resolution + bidirectional drift guard

**Files:**
- Test: `tests/test_tool_catalog.py`

This is the anti-drift centerpiece (spec §4.3).

- [ ] **Step 1: Write the gate-key resolution test**

Append to `tests/test_tool_catalog.py`:

```python
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent

# Canonical service vocabulary = the keys passed to service_key("...") anywhere.
def _known_services() -> set[str]:
    services = set()
    for py in (_REPO / "odigos").rglob("*.py"):
        services |= set(re.findall(r'service_key\("([a-z_]+)"\)', py.read_text()))
    for py in (_REPO / "plugins").rglob("*.py"):
        services |= set(re.findall(r'service_key\("([a-z_]+)"\)', py.read_text()))
    return services


def test_gate_keys_resolve():
    from odigos.tools.catalog import build_catalog
    catalog = build_catalog()
    known_services = _known_services()
    for name, gate in catalog.items():
        if gate.kind == "plugin":
            assert (_REPO / "plugins" / gate.key).is_dir(), \
                f"{name}: plugin '{gate.key}' has no plugins/{gate.key}/ dir"
        elif gate.kind == "service":
            assert gate.key in known_services, \
                f"{name}: service '{gate.key}' not in {sorted(known_services)}"
        # 'config' keys are free-form condition strings (e.g. 'email.imap_host',
        # 'ffmpeg', 'opencli') — validated by the drift guard below, not here.
```

- [ ] **Step 2: Write the bidirectional drift guard test**

Append to `tests/test_tool_catalog.py`:

```python
# Map condition-string -> the tool CLASS names registered under it in bootstrap.
# This is the single source of truth the drift guard checks the catalog against.
# When you add/remove a guarded registration in bootstrap.py, update this and
# the tool's gate together — the test fails loudly if they drift apart.
BOOTSTRAP_GUARDED = {
    # condition substring in bootstrap (or plugin) -> set of tool NAMES
    "mesh.enabled":     {"message_peer"},
    "opencli":          {"web_platform"},
    "ffmpeg":           {"process_audio"},
    "kie_ai":           {"generate_image", "generate_music"},
    "feed.enabled":     {"publish_to_feed"},
    "calendar.url":     {"check_calendar", "create_calendar_event", "find_free_time"},
    "email.imap_host":  {"check_email", "search_email", "read_email", "send_email"},
    "search_provider":  {"web_search"},
    "gws":              {"run_gws"},
    "browser":          {"run_browser"},
    "tts":              {"speak"},
    "stt":              {"transcribe_audio"},
}


def test_every_conditional_tool_is_gated():
    """Forward drift guard: every tool we KNOW is conditionally registered
    must carry a non-ALWAYS gate in the catalog."""
    from odigos.tools.catalog import build_catalog
    from odigos.tools.gate import ALWAYS
    catalog = build_catalog()
    for cond, names in BOOTSTRAP_GUARDED.items():
        for name in names:
            assert name in catalog, f"{name} (cond {cond}) missing from catalog"
            assert catalog[name] is not ALWAYS and catalog[name].kind != "always", \
                f"{name} is conditionally registered (cond {cond}) but gate=ALWAYS"


def test_gated_tools_match_known_conditions():
    """Reverse drift guard: every non-ALWAYS tool in the catalog must appear
    in BOOTSTRAP_GUARDED (i.e. there's a real registration guard for it)."""
    from odigos.tools.catalog import build_catalog
    catalog = build_catalog()
    all_guarded_names = set().union(*BOOTSTRAP_GUARDED.values())
    for name, gate in catalog.items():
        if gate.kind != "always":
            assert name in all_guarded_names, \
                f"{name} has gate {gate} but no entry in BOOTSTRAP_GUARDED — " \
                f"stale gate, or add it to the map when you add the guard"
```

- [ ] **Step 3: Run the integrity tests**

Run: `.venv/bin/python -m pytest tests/test_tool_catalog.py -p no:cacheprovider -q`
Expected: PASS. If `test_gated_tools_match_known_conditions` fails, a tool has a gate with no matching bootstrap guard entry — fix the gate or the map. If `test_every_conditional_tool_is_gated` fails, a guarded tool is missing its gate annotation (go back to Task 4/5).

- [ ] **Step 4: Commit**

```bash
git add tests/test_tool_catalog.py
git commit -m "test(tools): catalog gate-key resolution + bidirectional drift guard (catalog task 7)"
```

---

## Task 8: Rewrite the skill validator to use the catalog

**Files:**
- Modify: `odigos/bootstrap.py` (`validate_skill_tools` + `_PLUGIN_PROVIDED_TOOL_NAMES`)
- Test: `tests/test_skill_validation.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_skill_validation.py`:

```python
"""Tests for Bootstrapper.validate_skill_tools (catalog-backed)."""
import pytest

from odigos.bootstrap import Bootstrapper


class _FakeTool:
    def __init__(self, name):
        self.name = name


class _FakeRegistry:
    def __init__(self, names):
        self._tools = [_FakeTool(n) for n in names]
    def list(self):
        return self._tools


class _FakeSkill:
    def __init__(self, name, tools):
        self.name = name
        self.tools = tools


class _FakeSkillRegistry:
    def __init__(self, skills):
        self._skills = skills
    def list(self):
        return self._skills


def _make_bootstrapper(live_tool_names, skills):
    from tests.conftest import make_test_settings
    b = Bootstrapper(settings=make_test_settings())
    b.container.tool_registry = _FakeRegistry(live_tool_names)
    b.container.skill_registry = _FakeSkillRegistry(skills)
    return b


def test_inactive_plugin_tool_is_not_an_error(monkeypatch):
    # run_gws is in the catalog (plugin-gated) but not live this run -> OK.
    monkeypatch.setenv("ODIGOS_TOOL_VALIDATION", "auto")
    b = _make_bootstrapper(
        live_tool_names=["read_page"],
        skills=[_FakeSkill("google-workspace", ["run_gws"])],
    )
    # Should not raise regardless of date (run_gws exists in catalog).
    b.validate_skill_tools()


def test_unknown_tool_warns_before_cutover(monkeypatch, caplog):
    monkeypatch.setenv("ODIGOS_TOOL_VALIDATION", "auto")
    monkeypatch.setattr(
        "odigos.bootstrap._skill_validation_today",
        lambda: __import__("datetime").date(2026, 7, 1),
    )
    b = _make_bootstrapper(
        live_tool_names=["read_page"],
        skills=[_FakeSkill("x", ["totally_bogus_tool"])],
    )
    b.validate_skill_tools()  # warns, does not raise


def test_unknown_tool_raises_after_cutover(monkeypatch):
    monkeypatch.setenv("ODIGOS_TOOL_VALIDATION", "auto")
    monkeypatch.setattr(
        "odigos.bootstrap._skill_validation_today",
        lambda: __import__("datetime").date(2026, 9, 1),
    )
    b = _make_bootstrapper(
        live_tool_names=["read_page"],
        skills=[_FakeSkill("x", ["totally_bogus_tool"])],
    )
    with pytest.raises(RuntimeError, match="totally_bogus_tool"):
        b.validate_skill_tools()


def test_env_warn_overrides_cutover(monkeypatch):
    monkeypatch.setenv("ODIGOS_TOOL_VALIDATION", "warn")
    monkeypatch.setattr(
        "odigos.bootstrap._skill_validation_today",
        lambda: __import__("datetime").date(2026, 9, 1),
    )
    b = _make_bootstrapper(
        live_tool_names=["read_page"],
        skills=[_FakeSkill("x", ["totally_bogus_tool"])],
    )
    b.validate_skill_tools()  # warn mode -> no raise even post-cutover


def test_env_off_skips(monkeypatch):
    monkeypatch.setenv("ODIGOS_TOOL_VALIDATION", "off")
    monkeypatch.setattr(
        "odigos.bootstrap._skill_validation_today",
        lambda: __import__("datetime").date(2026, 9, 1),
    )
    b = _make_bootstrapper(
        live_tool_names=[],
        skills=[_FakeSkill("x", ["totally_bogus_tool"])],
    )
    b.validate_skill_tools()  # off -> no raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_skill_validation.py -p no:cacheprovider -q`
Expected: FAIL — `_skill_validation_today` doesn't exist; current `validate_skill_tools` uses `_PLUGIN_PROVIDED_TOOL_NAMES` and an inline date.

- [ ] **Step 3: Rewrite validate_skill_tools**

In `odigos/bootstrap.py`: remove the `_PLUGIN_PROVIDED_TOOL_NAMES` class attr. Add a module-level helper (so tests can monkeypatch the date) near the top of the file:

```python
def _skill_validation_today():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).date()
```

Replace the `validate_skill_tools` method body with:

```python
    def validate_skill_tools(self) -> None:
        """Validate every skill's declared tools against the tool catalog
        (spec 2026-05-29). A tool is OK if it's live OR in the catalog
        (exists but inactive this run). A tool in neither is a hard problem:
        WARN before the cutover, RAISE on/after it. Env ODIGOS_TOOL_VALIDATION
        overrides: 'warn' = never raise, 'off' = skip entirely."""
        import os
        from datetime import date

        mode = os.environ.get("ODIGOS_TOOL_VALIDATION", "auto").lower()
        if mode == "off":
            return

        skill_registry = getattr(self.container, "skill_registry", None)
        registry = getattr(self.container, "tool_registry", None)
        if skill_registry is None or registry is None:
            return

        try:
            from odigos.tools.catalog import build_catalog
            catalog = build_catalog()
        except Exception:
            logger.warning("Skill validation skipped: tool catalog unavailable", exc_info=True)
            return
        if not catalog:
            logger.warning("Skill validation skipped: tool catalog empty")
            return

        live = {t.name for t in registry.list()}
        _CUTOVER = date(2026, 8, 1)
        hard: list[str] = []
        inactive: list[str] = []
        for skill in skill_registry.list():
            for tool_name in skill.tools:
                if tool_name in live:
                    continue
                if tool_name in catalog:
                    inactive.append(
                        f"skill '{skill.name}' uses '{tool_name}' "
                        f"(inactive: {catalog[tool_name].describe()})"
                    )
                else:
                    hard.append(
                        f"skill '{skill.name}' references unknown tool '{tool_name}'"
                    )

        if inactive:
            logger.info("Skill tool validation (inactive): %s", "; ".join(inactive))
        if hard:
            msg = "Skill tool validation failed: " + "; ".join(hard)
            if mode != "warn" and _skill_validation_today() >= _CUTOVER:
                raise RuntimeError(msg)
            logger.warning("%s (hard failure on/after %s unless ODIGOS_TOOL_VALIDATION=warn)",
                           msg, _CUTOVER.isoformat())
```

- [ ] **Step 4: Run the validator tests**

Run: `.venv/bin/python -m pytest tests/test_skill_validation.py -p no:cacheprovider -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Run bootstrap-touching tests to confirm no breakage**

Run: `.venv/bin/python -m pytest tests/test_find_tools_coverage.py -p no:cacheprovider -q`
Expected: PASS (still discovers all tools; bootstrap import unaffected)

- [ ] **Step 6: Commit**

```bash
git add odigos/bootstrap.py tests/test_skill_validation.py
git commit -m "feat(bootstrap): catalog-backed skill validation + env override (catalog task 8)"
```

---

## Task 9: find_tools coverage test iterates the catalog

**Files:**
- Modify: `tests/test_find_tools_coverage.py`

Currently the coverage test builds the registry from the live boot. Switch its "set of all tools that must be discoverable" to the catalog, so the 2 subprocess + any inactive tools are covered too.

- [ ] **Step 1: Read the current test**

Run: `sed -n '1,60p' tests/test_find_tools_coverage.py` and note how it computes `all_tools` (currently `{t.name for t in registry.list()}`).

- [ ] **Step 2: Update the discoverable-set source**

Change the test so the set of names that must be discoverable comes from the catalog, while find_tools still searches the live registry. Replace the `all_tools = {t.name for t in registry.list()}` line with:

```python
    from odigos.tools.catalog import build_catalog
    all_tools = set(build_catalog().keys())
```

Keep the rest (the query loop, the assertion that each name appears in some query result) unchanged. Note: find_tools searches the live registry, so a cataloged-but-inactive tool (e.g. run_gws when its plugin is off) will NOT appear in find_tools output during the test. Handle this by registering all catalog tools for the coverage check OR by asserting discoverability only for tools that are live. Decision: assert discoverability for the **live** set, but assert the **catalog** set is a superset and log any cataloged-but-inactive tools as informational — the coverage guarantee is about discoverability of *active* tools, while the catalog guarantees *existence*. Concretely:

```python
    live_names = {t.name for t in registry.list()}
    catalog_names = set(build_catalog().keys())
    # Every cataloged tool must be known to the system (sanity):
    assert catalog_names >= live_names
    # Discoverability is asserted for tools that are actually active this run:
    covered = set()
    for q in QUERIES:
        res = await finder.execute({"query": q})
        if not res.success:
            continue
        for name in live_names:
            if name in res.data:
                covered.add(name)
    uncovered = sorted(live_names - covered)
    assert not uncovered, (
        f"{len(uncovered)} active tool(s) not discoverable via find_tools: {uncovered}. "
        "Add >=3 seed queries for each to QUERIES in this file."
    )
```

- [ ] **Step 3: Run the coverage test**

Run: `.venv/bin/python -m pytest tests/test_find_tools_coverage.py -p no:cacheprovider -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_find_tools_coverage.py
git commit -m "test(find_tools): coverage gate cross-checks the tool catalog (catalog task 9)"
```

---

## Task 10: Full-suite verification + deploy

**Files:** none (verification + rollout)

- [ ] **Step 1: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -p no:cacheprovider --ignore=tests/e2e -m "not slow and not network" -q`
Expected: all pass (baseline was `1483 passed, 2 skipped`; this adds the new catalog/validation tests, 0 failures).

- [ ] **Step 2: Run the slow find_tools coverage test explicitly**

Run: `.venv/bin/python -m pytest tests/test_find_tools_coverage.py -p no:cacheprovider -q -m slow`
Expected: PASS

- [ ] **Step 3: Push**

```bash
git push origin main
```

- [ ] **Step 4: Deploy to Bob + Jessica and verify clean boot**

```bash
ssh odigos 'for spec in "/opt/odigos:odigos_jacob" "/opt/odigos-jessica:odigos_jessica"; do
  ROOT=${spec%%:*}; USR=${spec##*:}
  sudo -u "$USR" bash -c "cd $ROOT && git checkout -- uv.lock 2>/dev/null; git pull --rebase -q | tail -1"
done
sudo systemctl restart odigos odigos-jessica
sleep 18
echo "Bob: $(curl -sf -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/) Jessica: $(curl -sf -o /dev/null -w "%{http_code}" http://127.0.0.1:8002/)"'
```
Expected: `Bob: 200 Jessica: 200`

- [ ] **Step 5: Confirm validator logs inactive-notes, not false errors**

```bash
ssh odigos 'sudo journalctl -u odigos --no-pager --since "2 min ago" | grep -iE "Skill tool validation"'
```
Expected: INFO line listing `run_gws`, `run_browser`, `web_search`, `speak`, `transcribe_audio` etc. as inactive (depending on what's configured), and **zero** "references unknown tool" WARNINGs.

- [ ] **Step 6: Update spec status + anti-pattern entry 7**

In `docs/superpowers/specs/2026-05-29-tool-catalog-design.md`, change Status to `implemented 2026-05-29`. In `docs/superpowers/anti-patterns.md` entry 7, append: "Resolved structurally by the tool catalog (spec 2026-05-29): the validator now distinguishes inactive-but-cataloged from truly-unknown, and a bidirectional drift guard test enforces gate↔registration consistency."

```bash
git add docs/superpowers/specs/2026-05-29-tool-catalog-design.md docs/superpowers/anti-patterns.md
git commit -m "docs: mark tool-catalog implemented; close anti-pattern entry 7 (catalog task 10)"
git push origin main
```

---

## Notes for the implementer

- **`make_test_settings`** is in `tests/conftest.py` — it provides a minimal Settings with provider/model plumbing. The validator tests use fake registries so they don't need a real boot.
- **Bootstrapper construction:** `Bootstrapper(settings=...)` is the constructor; `self.container` exists after construction (it's created in `__init__`). If `container.tool_registry` / `skill_registry` aren't set in `__init__`, the validator tests set them directly on the fake — confirm by reading `Bootstrapper.__init__` and adjust the test helper if needed.
- **Do not** change how any tool registers in bootstrap or plugins. Gates are metadata only.
- **If the drift guard test fails during Task 7** it's doing its job — reconcile the gate annotation with the real bootstrap guard rather than weakening the test.
