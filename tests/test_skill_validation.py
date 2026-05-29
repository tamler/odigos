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
    b.validate_skill_tools()  # must not raise regardless of date


def test_unknown_tool_warns_before_cutover(monkeypatch):
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
