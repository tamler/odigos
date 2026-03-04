from odigos.personality.loader import Personality

ENTITY_EXTRACTION_INSTRUCTION = """After your response, on a new line, include extracted entities in this exact format:
<!--entities
[{{"name": "...", "type": "person|project|preference|concept", "relationship": "...", "detail": "..."}}]
-->
Only include entities if the conversation mentions specific people, projects, preferences, or important concepts.
If none are relevant, omit the block entirely."""


def build_system_prompt(
    personality: Personality,
    memory_context: str = "",
) -> str:
    """Compose the system prompt from structured sections.

    Sections:
    1. Identity -- who the agent is
    2. Voice guidelines -- how to communicate
    3. Memory context -- relevant memories (if any)
    4. Entity extraction -- always appended
    """
    sections = []

    # 1. Identity
    sections.append(_build_identity_section(personality))

    # 2. Voice guidelines
    sections.append(_build_voice_section(personality))

    # 3. Memory context (optional)
    if memory_context:
        sections.append(memory_context)

    # 4. Entity extraction (always)
    sections.append(ENTITY_EXTRACTION_INSTRUCTION)

    return "\n\n".join(sections)


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
