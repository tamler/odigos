from odigos.personality.loader import Personality
from odigos.personality.prompt_builder import (
    CORRECTION_DETECTION_INSTRUCTION,
    ENTITY_EXTRACTION_INSTRUCTION,
    SKILL_CREATION_INSTRUCTION,
    build_system_prompt,
)


class TestCorrectionsInPrompt:
    def test_corrections_section_included_when_provided(self):
        """Corrections context appears in the system prompt when provided."""
        personality = Personality()
        corrections = "## Learned corrections\nApply these lessons from past feedback:\n- [tone] Be more casual"

        prompt = build_system_prompt(personality, corrections_context=corrections)

        assert "Learned corrections" in prompt
        assert "Be more casual" in prompt

    def test_corrections_section_omitted_when_empty(self):
        """No corrections section when corrections_context is empty."""
        personality = Personality()

        prompt = build_system_prompt(personality, corrections_context="")

        assert "Learned corrections" not in prompt

    def test_correction_detection_instructions_always_present(self):
        """Correction detection instruction block is always in the prompt."""
        personality = Personality()

        prompt = build_system_prompt(personality)

        assert "<!--correction" in prompt
        assert "correction block" in prompt.lower()

    def test_corrections_appear_before_entity_extraction(self):
        """Corrections context and detection instruction come before entity extraction."""
        personality = Personality()
        corrections = "## Learned corrections\nApply these lessons from past feedback:\n- [tone] Be more casual"

        prompt = build_system_prompt(personality, corrections_context=corrections)

        corrections_pos = prompt.index("Learned corrections")
        detection_pos = prompt.index("<!--correction")
        entity_pos = prompt.index("<!--entities")

        assert corrections_pos < detection_pos
        assert detection_pos < entity_pos


class TestSkillCreationInstruction:
    def test_skill_creation_instruction_present(self):
        personality = Personality()
        prompt = build_system_prompt(personality)
        assert "create_skill" in prompt

    def test_skill_creation_after_catalog(self):
        personality = Personality()
        prompt = build_system_prompt(
            personality,
            skill_catalog="## Available skills\n- **research**: Deep research",
        )
        catalog_pos = prompt.find("Available skills")
        creation_pos = prompt.find("create_skill")
        assert catalog_pos < creation_pos
