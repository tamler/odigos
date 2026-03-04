import yaml
from pathlib import Path


from odigos.personality.loader import Personality, VoiceConfig, IdentityConfig, load_personality
from odigos.personality.prompt_builder import build_system_prompt


class TestLoadPersonality:
    def test_loads_from_yaml(self, tmp_path: Path):
        """Load personality from a YAML file."""
        personality_file = tmp_path / "personality.yaml"
        personality_file.write_text(
            yaml.dump(
                {
                    "name": "Jarvis",
                    "voice": {
                        "tone": "formal and precise",
                        "verbosity": "verbose",
                        "humor": "none",
                        "formality": "always formal",
                    },
                    "identity": {
                        "role": "butler",
                        "relationship": "servant",
                        "first_person": False,
                        "expresses_uncertainty": False,
                        "expresses_opinions": False,
                    },
                }
            )
        )

        personality = load_personality(str(personality_file))

        assert personality.name == "Jarvis"
        assert personality.voice.tone == "formal and precise"
        assert personality.voice.verbosity == "verbose"
        assert personality.identity.role == "butler"
        assert personality.identity.first_person is False

    def test_returns_defaults_when_file_missing(self):
        """Missing file returns default personality."""
        personality = load_personality("/nonexistent/path.yaml")

        assert personality.name == "Odigos"
        assert personality.voice.tone == "direct, warm, slightly informal"
        assert personality.identity.first_person is True

    def test_partial_yaml_fills_defaults(self, tmp_path: Path):
        """YAML with only some fields fills the rest with defaults."""
        personality_file = tmp_path / "personality.yaml"
        personality_file.write_text(yaml.dump({"name": "Nova"}))

        personality = load_personality(str(personality_file))

        assert personality.name == "Nova"
        # Defaults for everything else
        assert personality.voice.tone == "direct, warm, slightly informal"
        assert personality.identity.role == "personal assistant and research partner"


class TestPromptBuilder:
    def test_builds_prompt_with_personality(self):
        """Prompt includes personality identity and voice sections."""
        personality = Personality(
            name="TestBot",
            voice=VoiceConfig(tone="cheerful", verbosity="brief"),
            identity=IdentityConfig(role="helper", relationship="friendly"),
        )

        prompt = build_system_prompt(personality)

        assert "TestBot" in prompt
        assert "cheerful" in prompt
        assert "brief" in prompt
        assert "helper" in prompt
        assert "<!--entities" in prompt  # entity extraction always included

    def test_builds_prompt_with_memory_context(self):
        """Prompt includes memory section when provided."""
        personality = Personality()

        prompt = build_system_prompt(
            personality,
            memory_context="## Relevant memories\n- Alice prefers mornings.",
        )

        assert "Relevant memories" in prompt
        assert "Alice prefers mornings" in prompt

    def test_builds_prompt_without_memory(self):
        """Prompt works fine without memory context."""
        personality = Personality()

        prompt = build_system_prompt(personality)

        assert "Odigos" in prompt
        assert "<!--entities" in prompt
        assert "Relevant memories" not in prompt

    def test_uncertainty_and_opinions_in_prompt(self):
        """Identity flags are reflected in the prompt."""
        personality = Personality(
            identity=IdentityConfig(
                expresses_uncertainty=True,
                expresses_opinions=True,
            )
        )

        prompt = build_system_prompt(personality)

        # Should contain uncertainty language
        assert "not sure" in prompt.lower() or "uncertain" in prompt.lower()

    def test_no_uncertainty_when_disabled(self):
        """When expresses_uncertainty is False, prompt doesn't mention it."""
        personality = Personality(identity=IdentityConfig(expresses_uncertainty=False))

        prompt = build_system_prompt(personality)

        assert "not sure" not in prompt.lower()
