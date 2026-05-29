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
