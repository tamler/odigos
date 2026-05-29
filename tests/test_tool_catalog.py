"""Tests for the tool gate model and catalog (spec 2026-05-29)."""
import pytest
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


def test_basetool_has_default_always_gate():
    from odigos.tools.base import BaseTool
    from odigos.tools.gate import ALWAYS
    assert BaseTool.gate is ALWAYS


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


def test_build_catalog_includes_core_and_conditional_tools():
    from odigos.tools.catalog import build_catalog
    catalog = build_catalog()
    # Spot-check always-on, service-gated, config-gated, plugin-gated:
    assert "read_page" in catalog
    assert "generate_image" in catalog
    assert "check_email" in catalog
    assert "run_gws" in catalog
    assert "run_browser" in catalog
    assert "generate_ics_file" in catalog  # renamed from create_calendar_event to resolve a name collision
    # Reasonable lower bound (66 static + 2 subprocess = 68; allow growth):
    assert len(catalog) >= 60


def test_build_catalog_is_memoized():
    from odigos.tools.catalog import build_catalog
    assert build_catalog() is build_catalog()


def test_build_catalog_rejects_name_collision():
    # Two concrete BaseTool subclasses with the same name must raise.
    import odigos.tools.catalog as cat
    import pytest
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
    try:
        with pytest.raises(ValueError, match="dup_collide_xyz"):
            cat.build_catalog()
    finally:
        # Neutralize the throwaway dup classes so later catalog builds in this
        # process aren't poisoned, even if build_catalog raised unexpectedly.
        _Dup1.name = None  # type: ignore[assignment]
        _Dup2.name = None  # type: ignore[assignment]
        cat.reset_catalog_cache()


import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _known_services() -> set[str]:
    """Canonical service vocabulary = every key passed to service_key("...")."""
    services = set()
    for base in ("odigos", "plugins"):
        for py in (_REPO / base).rglob("*.py"):
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


# condition substring -> tool NAMES registered under it in bootstrap/plugins.
# Single source of truth the drift guard checks the catalog against. When you
# add/remove a guarded registration, update this map AND the tool's gate
# together — the tests below fail loudly if they drift apart.
BOOTSTRAP_GUARDED = {
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


# Exact (kind, key) expected for every conditional tool — guards against a gate
# being changed to the wrong KIND (the drift guards only check always-vs-not).
EXPECTED_GATES = {
    "message_peer":          ("config", "mesh.enabled"),
    "web_platform":          ("config", "opencli"),
    "process_audio":         ("config", "ffmpeg"),
    "generate_image":        ("service", "kie_ai"),
    "generate_music":        ("service", "kie_ai"),
    "publish_to_feed":       ("config", "feed.enabled"),
    "check_calendar":        ("config", "calendar.url"),
    "create_calendar_event": ("config", "calendar.url"),
    "find_free_time":        ("config", "calendar.url"),
    "check_email":           ("config", "email.imap_host"),
    "search_email":          ("config", "email.imap_host"),
    "read_email":            ("config", "email.imap_host"),
    "send_email":            ("config", "email.imap_host"),
    "web_search":            ("config", "search_provider"),
    "run_gws":               ("plugin", "gws"),
    "run_browser":           ("plugin", "browser"),
    "speak":                 ("plugin", "tts"),
    "transcribe_audio":      ("plugin", "stt"),
}


@pytest.mark.parametrize("tool_name,expected", list(EXPECTED_GATES.items()))
def test_conditional_tool_exact_gate(tool_name, expected):
    from odigos.tools.catalog import build_catalog
    catalog = build_catalog()
    assert tool_name in catalog, f"{tool_name} missing from catalog"
    gate = catalog[tool_name]
    assert (gate.kind, gate.key) == expected, f"{tool_name}: ({gate.kind},{gate.key}) != {expected}"
