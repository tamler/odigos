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
) -> str:
    """Compose the system prompt from file-based sections."""
    parts = []
    for section in sorted(sections, key=lambda s: s.priority):
        content = section.content.replace("{name}", agent_name)
        parts.append(content)

    if memory_context:
        parts.append(memory_context)
    if skill_catalog:
        parts.append(skill_catalog)
    if skill_hints:
        parts.append(skill_hints)
    if doc_listing:
        parts.append(doc_listing)
    if corrections_context:
        parts.append(corrections_context)

    return "\n\n".join(parts)
