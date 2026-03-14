from __future__ import annotations

from odigos.personality.loader import Personality

ENTITY_EXTRACTION_INSTRUCTION = """After your response, on a new line, include extracted entities in this exact format:
<!--entities
[{{"name": "...", "type": "person|project|preference|concept", "relationship": "...", "detail": "..."}}]
-->
Only include entities if the conversation mentions specific people, projects, preferences, or important concepts.
If none are relevant, omit the block entirely."""

CORRECTION_DETECTION_INSTRUCTION = """If the user's message is correcting or disagreeing with your previous response, include a correction block after your response in this exact format:
<!--correction
{"original": "brief summary of what you said wrong", "correction": "what the user wants instead", "category": "tone|accuracy|preference|behavior|tool_choice", "context": "brief description of the situation"}
-->
Only include this block when the user is explicitly correcting you. Categories:
- tone: communication style (too formal, too casual, etc.)
- accuracy: factual errors
- preference: user preferences (scheduling, formatting, etc.)
- behavior: action/decision patterns
- tool_choice: wrong tool or approach used
If the user is not correcting you, omit the block entirely."""

SKILL_CREATION_INSTRUCTION = """You can create reusable skills for task types you encounter repeatedly using the create_skill tool. A skill is a set of instructions that guide your behavior for a specific kind of task. Create a skill when you notice you've handled the same type of request multiple times with similar steps. Use update_skill to refine a skill you created when you receive corrections or learn better approaches. When you create or update a skill, mention it briefly in your response so the user is aware."""


def build_system_prompt(
    personality: Personality,
    memory_context: str = "",
    skill_catalog: str = "",
    corrections_context: str = "",
    sections: list | None = None,
) -> str:
    """Compose the system prompt from structured sections.

    Sections:
    1. Identity -- who the agent is
    2. Voice guidelines -- how to communicate
    3. Memory context -- relevant memories (if any)
    4. Skill catalog -- available skills (if any)
    5. Skill creation guidance (always)
    6. Learned corrections (optional)
    7. Correction detection (always)
    8. Entity extraction -- always appended
    """
    parts = []

    if sections:
        # Dynamic mode: sections loaded from files + trial overrides
        for section in sorted(sections, key=lambda s: s.priority):
            if section.always_include:
                content = section.content.replace("{name}", personality.name)
                parts.append(content)
    else:
        # Legacy fallback: build from personality dataclass
        parts.append(_build_identity_section(personality))
        parts.append(_build_voice_section(personality))

    # Always-included context sections
    if memory_context:
        parts.append(memory_context)
    if skill_catalog:
        parts.append(skill_catalog)

    parts.append(SKILL_CREATION_INSTRUCTION)

    if corrections_context:
        parts.append(corrections_context)

    parts.append(CORRECTION_DETECTION_INSTRUCTION)
    parts.append(ENTITY_EXTRACTION_INSTRUCTION)

    return "\n\n".join(parts)


def _build_identity_section(personality: Personality) -> str:
    """Build the identity/intro section of the system prompt."""
    identity = personality.identity

    lines = [f"You are {personality.name}, a {identity.role}."]

    if identity.relationship:
        lines.append(f"Your relationship with the user: {identity.relationship}.")

    if identity.first_person:
        lines.append("Speak in first person.")

    if identity.expresses_uncertainty:
        lines.append("When you're not sure about something, say so honestly rather than guessing.")

    if identity.expresses_opinions:
        lines.append("When asked, share your perspective with reasoning.")

    return " ".join(lines)


def _build_voice_section(personality: Personality) -> str:
    """Build the voice/style guidelines section."""
    voice = personality.voice

    lines = ["## Communication style"]
    lines.append(f"- Tone: {voice.tone}")
    lines.append(f"- Verbosity: {voice.verbosity}")
    lines.append(f"- Humor: {voice.humor}")
    lines.append(f"- Formality: {voice.formality}")

    return "\n".join(lines)
