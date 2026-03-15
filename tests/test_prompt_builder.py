"""Tests for the simplified prompt builder."""
from odigos.personality.prompt_builder import build_system_prompt
from odigos.personality.section_registry import PromptSection


class TestBuildSystemPrompt:
    def test_builds_from_sections(self):
        sections = [
            PromptSection(name="identity", content="You are {name}.", priority=10),
            PromptSection(name="voice", content="Be concise.", priority=20),
        ]
        result = build_system_prompt(sections=sections, agent_name="TestBot")
        assert "You are TestBot." in result
        assert "Be concise." in result

    def test_sections_sorted_by_priority(self):
        sections = [
            PromptSection(name="voice", content="VOICE", priority=20),
            PromptSection(name="identity", content="IDENTITY", priority=10),
        ]
        result = build_system_prompt(sections=sections)
        assert result.index("IDENTITY") < result.index("VOICE")

    def test_memory_context_included(self):
        sections = [PromptSection(name="id", content="You are Odigos.", priority=10)]
        result = build_system_prompt(
            sections=sections,
            memory_context="## Relevant memories\n- Alice prefers mornings.",
        )
        assert "Alice prefers mornings" in result

    def test_memory_context_omitted_when_empty(self):
        sections = [PromptSection(name="id", content="Agent.", priority=10)]
        result = build_system_prompt(sections=sections, memory_context="")
        assert "Relevant memories" not in result

    def test_corrections_context_included(self):
        sections = [PromptSection(name="id", content="Agent.", priority=10)]
        corrections = "## Learned corrections\n- Be more casual"
        result = build_system_prompt(sections=sections, corrections_context=corrections)
        assert "Be more casual" in result

    def test_skill_catalog_included(self):
        sections = [PromptSection(name="id", content="Agent.", priority=10)]
        result = build_system_prompt(
            sections=sections,
            skill_catalog="## Skills\n- research",
        )
        assert "research" in result

    def test_empty_sections_still_works(self):
        result = build_system_prompt(sections=[])
        assert isinstance(result, str)

    def test_name_replacement_in_content(self):
        sections = [PromptSection(name="id", content="I am {name}.", priority=10)]
        result = build_system_prompt(sections=sections, agent_name="Athena")
        assert "I am Athena." in result
        assert "{name}" not in result
