# Tool Catalog with Gate Metadata — Design

**Status:** implemented 2026-05-29 (review pass 1 applied; plan `docs/superpowers/plans/2026-05-29-tool-catalog.md` executed, full suite green)
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

Recursion handles subclass trees (e.g. `APITool` → `GenerateImageTool`). Abstract intermediates without a concrete `name` are skipped.

**Import safety (critical).** The builder imports the **core** tools package (`odigos.tools`) so its subclasses register with the interpreter, then walks `BaseTool.__subclasses__()`. It must NOT force-import plugin packages: plugins (`plugins/gws`, `plugins/browser`, …) import optional third-party deps (the gws/agent-browser CLIs' Python shims, etc.) that may not be installed, and force-importing would crash the catalog build. Consequence: a plugin tool's class is only walkable if its module was already imported this run (which happens when the plugin is enabled). For plugin tools that are NOT active this run, the catalog still needs their `(name, gate)` — see §3.5.

**Timing + memoization.** `build_catalog()` is called from a deliberate point (the validator, the find_tools test, future CLI) — not as an import side-effect. Result is memoized per-process (cleared in tests via a reset hook) since walking subclasses + reading attrs is cheap but called from multiple consumers.

### 3.5 Plugin-tool catalog entries without force-import

Core tools (66) are always importable, so always in the catalog. The 2 plugin-gated subprocess tools (`run_gws`, `run_browser`) live in `odigos/tools/` (NOT in the plugin package) — their classes import cleanly without the CLI present (they only shell out at execute time), so `build_catalog()` picks them up from the core scan too. This is already true today and is why §3.3's class-attr normalization is sufficient: the catalog sees all 68 from the core `odigos.tools` import, with no need to import any `plugins/*` package.

If a future plugin defines a tool class *inside its own package* (importing optional deps at module load), that tool would be invisible to the core scan. The forward-compatible answer (not built now, no such tool exists): such a plugin declares its `(name, gate)` via a lightweight manifest the catalog reads without importing the plugin body. Flagged in §8, not implemented.

## 4. Consumers

### 4.1 Skill validator (replaces the hardcoded set)

`Bootstrapper.validate_skill_tools` (runs after `init_plugins`). Full decision table for each (skill, declared-tool) pair:

| Condition | Outcome |
|-----------|---------|
| tool in **live registry** | OK (active) |
| tool in **catalog** but not live | OK + INFO note: "skill X uses Y (inactive: `<gate.describe()>`)" |
| tool in **neither** | hard problem → WARN now, RAISE on/after 2026-08-01 |
| **catalog build failed/empty** | degrade: WARN once ("skill validation skipped: catalog unavailable"), validate nothing, never RAISE |

This makes the 2026-08-01 hard-fail **safe**: it can only fire on a tool that exists nowhere in the codebase (a genuine typo/deletion), never on a correctly-declared conditional tool.

**Escape hatch.** Env var `ODIGOS_TOOL_VALIDATION` overrides the mode:
- unset / `auto` (default) — table above (warn pre-cutover, raise post-cutover)
- `warn` — force warn-only regardless of date (for staging/emergency boots missing an optional plugin where you've accepted the risk)
- `off` — skip validation entirely

Intended to be rare; the default is the right behavior for production. Documented so an operator with a genuinely broken-but-must-boot environment isn't stuck.

**Gated skills.** A skill that references *only* inactive-but-cataloged tools (e.g. `agent-browser` when the browser plugin is off) produces only INFO notes — never a warning or failure. The skill is simply dormant this run; that's correct, not an error. No special "gated skill" status is needed — the per-tool table already yields the right result.

### 4.2 find_tools coverage test

`tests/test_find_tools_coverage.py` asserts every **catalog** entry (not just live-registry entries) is discoverable via find_tools queries. This structurally covers the 2 dynamic-named tools too, which a class-attr-only scan would miss.

### 4.3 Catalog integrity test (new)

`tests/test_tool_catalog.py`:
- **Name uniqueness (asserted loudly):** no two `BaseTool` subclasses share a `name`. `build_catalog()` itself raises on a collision rather than silently last-wins; the test asserts the clean build.
- **Gate key resolves:** every conditional gate's `key` points at something real:
  - `plugin(k)` → `plugins/<k>/` exists
  - `service(k)` → `k` is a known service name (source confirmed in the plan — §8)
  - `config(k)` → `k` is a real `Settings` field
- **Bidirectional drift guard (the key anti-drift test).** This is what prevents the recurring "forgot the annotation" bug:
  - **Forward:** scan `bootstrap.py` for guarded registrations (`if settings.<x> ...: registry.register(SomeTool(...))`) and each `plugins/*/register()`. Any tool registered conditionally MUST have `gate != ALWAYS`. A new config-gated tool that forgets its gate fails this test.
  - **Reverse:** any catalog tool with `gate != ALWAYS` MUST appear behind a guard in bootstrap or a plugin register(). A stale gate annotation (tool made unconditional but gate left on) fails this test.
  - This is deliberately a *test*, not runtime magic — it runs in CI, points at the exact tool, and never affects boot. Matches the brittleness principle "make drift a loud failure, not silent."

### 4.4 Worked example

Catalog entries:
```python
{
  "read_page":       ToolGate("always"),
  "run_browser":     ToolGate("plugin",  "browser"),
  "run_gws":         ToolGate("plugin",  "gws"),
  "web_search":      ToolGate("config",  "search_provider"),
  "generate_image":  ToolGate("service", "kie_ai"),
}
```
Validator on an agent with no browser plugin, no search provider:
```
INFO  skill 'agent-browser' uses 'run_browser' (inactive: requires the browser plugin (enabled + its CLI installed))
INFO  skill 'compliance-check' uses 'web_search' (inactive: requires search_provider to be configured)
# no WARN, no RAISE — both tools exist in the catalog
```
Typo case (`run_broweser` in a skill), browser plugin disabled:
```
WARNING  Skill tool validation failed: skill 'agent-browser' references unknown tool 'run_broweser' (becomes a hard startup failure on 2026-08-01)
# 'run_broweser' is in neither live nor catalog -> real error, even though the plugin is off
```

## 5. Scope guardrails (YAGNI)

**In scope:** `ToolGate`, `BaseTool.gate`, class-name for the 2 subprocess tools, `build_catalog()`, the three consumers above.

**Explicitly NOT building:**
- A settings/capabilities UI driven by gates.
- Agent self-description ("I could search if you configured a provider") from gates.
- Runtime gate *enforcement* — tools register exactly as they do today via bootstrap guards + plugins. Gates are declarative metadata only; they do not become new control flow. (If we later want registration driven BY the gate, that's a separate design.)

These are deferred until a concrete need appears, per the brittleness spec's own "surface minimalism vs completeness" discipline applied in reverse: don't add machinery nothing consumes.

**Considered in review (2026-05-29) and explicitly rejected as scope creep — recorded so they're not silently re-litigated:**
- *Version skew / catalog git-SHA / "skill bundle from commit N vs binary N+5":* skills live in the **same git repo** as the code and deploy together (`git pull` + restart). There is no skill-bundle-vs-runtime versioning architecture, so there is no skew to solve. If skills ever become independently distributed, revisit.
- *Serialized JSON catalog artifact / "catalog service" abstraction:* runtime rebuild by walking subclasses is microseconds and memoized. No artifact or service layer needed.
- *CLI `odigos tools list` / Web capabilities UI / docs generator / agent-introspection API:* these are the deferred capabilities-UI / agent-self-description features. `find_tools` already IS the agent-facing introspection path. Not building a second one.
- *Third-party / community plugin ecosystem + optional-package versioning:* all 7 plugins are in-repo. No external ecosystem exists. §3.5 leaves a forward-compatible note (manifest) but builds nothing.
- *Multi-criteria gate composition (`AndGate`/`OrGate`):* no current tool needs it (each conditional tool has exactly one gate). The `gate` field is left forward-compatible (a future tool could carry a composite) but composition is not built. See §8.
- *Tool aliases / rename-deprecation windows:* no tool has an alias or a pending rename. YAGNI.

## 6. Testing

- `test_tool_catalog.py` — builder returns all 68, names unique (raises on collision), gates resolve, bidirectional drift guard (§4.3).
- `test_find_tools_coverage.py` — extended to iterate the catalog (§4.2).
- `test_blank_slate.py` / existing bootstrap tests — unchanged, must stay green (validator behavior change is a strict improvement: fewer false positives).

**Acceptance tests (pin the intent):**
1. Browser plugin disabled + validator runs → a skill referencing `run_browser` PASSES (no warn/raise); catalog still contains `run_browser` marked inactive.
2. Typo `run_broweser` in a skill, browser plugin disabled → validator hard-fails post-cutover (in neither live nor catalog), proving the cutover still catches real typos regardless of plugin state.
3. `ODIGOS_TOOL_VALIDATION=warn` with a genuinely-unknown tool post-cutover → WARN, no RAISE (escape hatch works).
4. Two tool classes declaring the same `name` → `build_catalog()` raises; `test_tool_catalog` fails loudly.
5. A new tool added behind `if settings.foo.enabled:` in bootstrap with `gate=ALWAYS` (forgotten annotation) → drift guard test fails, naming the tool.
6. Manual: boot Bob (no GWS/browser/search plugins active) → validator logs `run_gws`, `run_browser`, `web_search` as INFO inactive-notes, zero WARN/RAISE.

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
