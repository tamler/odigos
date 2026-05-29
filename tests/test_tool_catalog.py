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
    with pytest.raises(ValueError, match="dup_collide_xyz"):
        cat.build_catalog()
    # Neutralize so later catalog builds in this process aren't poisoned:
    _Dup1.name = None  # type: ignore[assignment]
    _Dup2.name = None  # type: ignore[assignment]
    cat.reset_catalog_cache()
