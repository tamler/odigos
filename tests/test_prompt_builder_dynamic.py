"""Test that prompt builder uses dynamic sections."""
from odigos.personality.prompt_builder import build_system_prompt
from odigos.personality.section_registry import PromptSection


def test_build_with_dynamic_sections():
    sections = [
        PromptSection(name="identity", content="You are Odigos.", priority=10),
        PromptSection(name="voice", content="Be concise.", priority=20),
    ]
    result = build_system_prompt(
        sections=sections,
        memory_context="User likes Python.",
        corrections_context="",
    )
    assert "You are Odigos." in result
    assert "Be concise." in result
    assert "User likes Python." in result
