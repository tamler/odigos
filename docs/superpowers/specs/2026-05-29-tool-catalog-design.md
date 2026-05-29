# Tool Catalog with Gate Metadata — Design

**Status:** spec / pre-implementation
**Date:** 2026-05-29
**Related:** [`2026-05-28-brittleness-audit-and-robustness.md`](./2026-05-28-brittleness-audit-and-robustness.md) §3.3, [`anti-patterns.md`](../anti-patterns.md) entry 7
**Motivation:** The skill-tool validator and find_tools coverage gate have no authoritative answer to "does this tool exist in the codebase?" — they only know "what registered this boot." Conditional tools (plugin-gated, service-key-gated, config-gated) are absent from the live registry when their condition isn't met, so the validator can't distinguish "tool doesn't exist" (a real bug) from "tool exists but isn't active this run" (fine). This caused a false hard-fail risk.

---

## 1. Problem

Tools register into a runtime `ToolRegistry` during bootstrap and plugin load. Registration is frequently **conditional**:

- `run_gws` / `run_browser` register only when their plugin is enabled AND the CLI is installed (`plugins/gws`, `plugins/browser`).
- `web_search` registers only when a search provider is configured (`plugins/searxng`).
- `generate_image` / `generate_music` register only when the `kie_ai` service key is set.
- `send_notification`, `message_peer`, STT/TTS tools — each gated on their own config.

The skill-tool validator (brittleness audit Phase B.2) compares each skill's declared `tools:` against the **live registry**. When a skill legitimately references a conditional tool that didn't register this run, the validator can't tell that apart from a typo'd / deleted tool. The interim fix hardcoded a 2-name allowlist (`run_gws`, `run_browser`) — which immediately proved too narrow (it missed `web_search`, `send_notification`, `message_peer`, all real tools), and would have falsely crashed agent startup on the 2026-08-01 hard-fail cutover.

**Root cause:** there is no single source of truth for "every tool that can exist," only "tools active right now."

## 2. Ground truth (verified 2026-05-29)

- **66 tools** declare a static class attribute `name = "..."` — readable without instantiation.
- **2 tools** (`GWSTool` → `run_gws`, `BrowserTool` → `run_browser`) set `self.name` via the `SubprocessTool` constructor (`tool_name=`), so the class has no static `name`.
- ~65 `registry.register(...)` calls in `bootstrap.py`, many behind `if` guards.
- Plugins gate on `settings.<x>.enabled`, `shutil.which(<cli>)`, or `search_provider`.

So the "exists in code" set = 66 static names + 2 dynamic names = **68**. The validator's false positives were purely because it compared against the live registry + a 2-name hardcoded set instead of this full catalog.

## 3. Design

### 3.1 ToolGate — declarative enabling condition

New module `odigos/tools/gate.py` (~40 lines):

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class ToolGate:
    """Declares what must be true for a tool to register/activate.
    Pure metadata — does NOT control registration (tools still register
    exactly as they do today). Used by the catalog to explain why a tool
    isn't active and by validators to distinguish 'missing' from 'inactive'."""
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

    # Convenience constructors
    @staticmethod
    def plugin(key: str) -> "ToolGate": return ToolGate("plugin", key)
    @staticmethod
    def service(key: str) -> "ToolGate": return ToolGate("service", key)
    @staticmethod
    def config(key: str) -> "ToolGate": return ToolGate("config", key)

ALWAYS = ToolGate("always")
```

### 3.2 BaseTool gains a `gate` class attr

```python
class BaseTool(ABC):
    name: str
    gate: ToolGate = ALWAYS   # NEW — default always-on
    ...
```

- The ~50 always-on tools change nothing (inherit `ALWAYS`).
- Conditional tools annotate, e.g.:
  - `GWSTool.gate = ToolGate.plugin("gws")`
  - `BrowserTool.gate = ToolGate.plugin("browser")`
  - `SearchTool.gate = ToolGate.config("search_provider")`
  - `GenerateImageTool.gate = ToolGate.service("kie_ai")`
  - `GenerateMusicTool.gate = ToolGate.service("kie_ai")`
  - (and the remaining conditional tools, identified during implementation by walking the bootstrap `if` guards + plugin register() functions)

### 3.3 Uniform naming for the 2 constructor-named tools

Give `GWSTool` and `BrowserTool` a class-level `name = "run_gws"` / `name = "run_browser"` so all 68 tools self-declare `name` as a class attribute. `SubprocessTool.__init__` continues to accept `tool_name=` for backward compatibility but the class attr is what the catalog reads. (Implementation detail: set the class attr and have the constructor default `tool_name` to it, or keep both — decided in the plan; behavior must not change.)

### 3.4 The catalog builder

New module `odigos/tools/catalog.py` (~50 lines):

```python
def build_catalog() -> dict[str, ToolGate]:
    """Walk BaseTool.__subclasses__() recursively; return {name: gate} for
    every concrete tool class. The authoritative 'what tools exist' set,
    independent of what registered this boot.

    Skips abstract bases (SubprocessTool, APITool, CLITool, etc.) — only
    classes with a concrete `name` are catalog entries.
    """
```

Recursion handles subclass trees (e.g. `APITool` → `GenerateImageTool`). Abstract intermediates without a `name` are skipped. Import side: the builder imports the tools package so all subclasses are registered with the interpreter before walking `__subclasses__()`.

## 4. Consumers

### 4.1 Skill validator (replaces the hardcoded set)

`Bootstrapper.validate_skill_tools` (runs after `init_plugins`):

```
catalog = build_catalog()           # all declarable tools
live    = {t.name for t in registry.list()}   # active this run
for each skill tool:
    in live            -> active, OK
    in catalog only    -> soft INFO: "skill X uses Y (inactive: <gate.describe()>)"
    in neither         -> hard problem (WARN now, RAISE on 2026-08-01)
```

This makes the 2026-08-01 hard-fail **safe**: it can only fire on a tool that exists nowhere in the codebase (a genuine typo/deletion), never on a correctly-declared conditional tool.

### 4.2 find_tools coverage test

`tests/test_find_tools_coverage.py` asserts every **catalog** entry (not just live-registry entries) is discoverable via find_tools queries. This structurally covers the 2 dynamic-named tools too, which a class-attr-only scan would miss.

### 4.3 Catalog integrity test (new)

`tests/test_tool_catalog.py`:
- Every catalog name is unique (no two tools share a name).
- Every conditional gate's `key` resolves to something real:
  - `plugin(k)` → `plugins/<k>/` exists
  - `service(k)` → `k` is a known service name (cross-check against the services the config/`service_key` accepts)
  - `config(k)` → `k` is a real Settings field
- Catches gate-drift (a tool declaring `service("kie_ia")` typo, or a plugin folder rename).

## 5. Scope guardrails (YAGNI)

**In scope:** `ToolGate`, `BaseTool.gate`, class-name for the 2 subprocess tools, `build_catalog()`, the three consumers above.

**Explicitly NOT building:**
- A settings/capabilities UI driven by gates.
- Agent self-description ("I could search if you configured a provider") from gates.
- Runtime gate *enforcement* — tools register exactly as they do today via bootstrap guards + plugins. Gates are declarative metadata only; they do not become new control flow. (If we later want registration driven BY the gate, that's a separate design.)

These are deferred until a concrete need appears, per the brittleness spec's own "surface minimalism vs completeness" discipline applied in reverse: don't add machinery nothing consumes.

## 6. Testing

- `test_tool_catalog.py` — builder returns all 68, names unique, gates resolve (§4.3).
- `test_find_tools_coverage.py` — extended to iterate the catalog (§4.2).
- `test_blank_slate.py` / existing bootstrap tests — unchanged, must stay green (validator behavior change is a strict improvement: fewer false positives).
- Manual: boot Bob (no GWS/browser/search plugins active) → validator logs `run_gws`, `run_browser`, `web_search`, etc. as INFO inactive-notes, zero WARN/RAISE.

## 7. Migration / rollout

- Pure addition; no data migration. No change to tool execution or registration.
- The validator change only *narrows* what counts as an error, so it cannot newly break a currently-booting agent.
- Deploy to Bob + Jessica, confirm clean boot logs (inactive-notes, no false WARN).

## 8. Open questions

- **Which exact tools are conditional, and their precise gate?** Enumerated during implementation by reading every guarded `registry.register` in bootstrap.py and each `plugins/*/register()`. The plan will produce the full annotated list; this spec fixes the *mechanism*, not the per-tool inventory.
- **`service` key validation source.** §4.3 needs the canonical list of valid service names — confirm whether that's an enum, the `services:` config schema, or just the set referenced by `service_key(...)` calls. Resolve in the plan.

## 9. Disposition

Fixes the validator false-positive class permanently and makes the 2026-08-01 skill-validation hard-fail safe to keep. Foundation a future capabilities UI could build on, without committing to that now.

Tags: `robustness`, `tools-design`, `pre-launch`, `brittleness-followup`.
