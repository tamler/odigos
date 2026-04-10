"""Tests for skill activation framing and overrides."""
from __future__ import annotations

from odigos.skills.registry import Skill


def _make_skill(name: str = "test", overrides: list[str] | None = None) -> Skill:
    return Skill(
        name=name,
        description="Test skill",
        tools=[],
        complexity="standard",
        system_prompt="You are a test specialist.",
        overrides=overrides or [],
    )


class TestSkillOverridesField:
    def test_skill_has_overrides_field(self):
        skill = _make_skill()
        assert skill.overrides == []

    def test_skill_overrides_accepts_list(self):
        skill = _make_skill(overrides=["tone", "concise_mode"])
        assert skill.overrides == ["tone", "concise_mode"]


class TestSkillFramingInjection:
    def test_framing_wrapper_preserves_personality(self):
        """The skill activation message should explicitly say personality still applies."""
        from odigos.core.executor import _build_skill_activation_message

        msg = _build_skill_activation_message("You are a legal expert.", overrides=[])
        assert "additive" in msg.lower() or "still apply" in msg.lower()
        assert "You are a legal expert." in msg

    def test_framing_with_overrides_suppresses(self):
        """When overrides are present, the message lists which personality aspects to suppress."""
        from odigos.core.executor import _build_skill_activation_message

        msg = _build_skill_activation_message(
            "You are a formal legal expert.", overrides=["tone", "concise_mode"]
        )
        assert "suppress" in msg.lower() or "override" in msg.lower()
        assert "tone" in msg
        assert "concise_mode" in msg
