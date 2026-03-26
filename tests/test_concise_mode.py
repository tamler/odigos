"""Tests for concise mode prompt injection."""
from odigos.personality.prompt_builder import build_system_prompt


class TestConciseMode:
    def test_concise_instruction_appended(self):
        """When concise_mode is True, the concise instruction should appear in the prompt."""
        prompt = build_system_prompt(sections=[], concise_mode=True)
        assert "Be concise" in prompt

    def test_concise_instruction_absent_by_default(self):
        """When concise_mode is False, no concise instruction."""
        prompt = build_system_prompt(sections=[], concise_mode=False)
        assert "Be concise" not in prompt

    def test_concise_mode_default_is_false(self):
        """Without passing concise_mode, it defaults to False."""
        prompt = build_system_prompt(sections=[])
        assert "Be concise" not in prompt
