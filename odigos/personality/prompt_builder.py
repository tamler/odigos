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
    tool_context: str = "",
    skill_catalog: str = "",
    corrections_context: str = "",
) -> str:
    """Compose the system prompt from structured sections.

    Sections:
    1. Identity -- who the agent is
    2. Voice guidelines -- how to communicate
    3. Memory context -- relevant memories (if any)
    4. Tool context -- results from tool execution (if any)
    5. Skill catalog -- available skills (if any)
    6. Skill creation guidance (always)
    7. Learned corrections (optional)
    8. Correction detection (always)
    9. Entity extraction -- always appended
    """
    sections = []

    # 1. Identity
    sections.append(_build_identity_section(personality))

    # 2. Voice guidelines
    sections.append(_build_voice_section(personality))

    # 3. Memory context (optional)
    if memory_context:
        sections.append(memory_context)

    # 4. Tool context (optional)
    if tool_context:
        sections.append(tool_context)

    # 5. Skill catalog (optional)
    if skill_catalog:
        sections.append(skill_catalog)

    # 6. Skill creation guidance (always)
    sections.append(SKILL_CREATION_INSTRUCTION)

    # 7. Learned corrections (optional)
    if corrections_context:
        sections.append(corrections_context)

    # 8. Correction detection (always)
    sections.append(CORRECTION_DETECTION_INSTRUCTION)

    # 9. Entity extraction (always)
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
