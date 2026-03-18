from __future__ import annotations

from odigos.personality.section_registry import PromptSection


def build_system_prompt(
    sections: list[PromptSection],
    memory_context: str = "",
    skill_catalog: str = "",
    corrections_context: str = "",
    doc_listing: str = "",
    agent_name: str = "",
    skill_hints: str = "",
    active_plan: str = "",
    error_hints: str = "",
    experiences: str = "",
    user_profile: str = "",
    user_facts: str = "",
    recovery_briefing: str = "",
) -> str:
    """Compose the system prompt from file-based sections."""
    parts = []
    for section in sorted(sections, key=lambda s: s.priority):
        content = section.content.replace("{name}", agent_name)
        parts.append(content)

    # User profile goes early -- after identity sections, before tools/skills
    if user_profile:
        parts.append(user_profile)
    if user_facts:
        parts.append(user_facts)

    if memory_context:
        parts.append(memory_context)
    if skill_catalog:
        parts.append(skill_catalog)
    if skill_hints:
        parts.append(skill_hints)
    if active_plan:
        parts.append(active_plan)
    if recovery_briefing:
        parts.append(recovery_briefing)
    if error_hints:
        parts.append(error_hints)
    if experiences:
        parts.append(experiences)
    if doc_listing:
        parts.append(doc_listing)
    if corrections_context:
        parts.append(corrections_context)

    return "\n\n".join(parts)
