"""Meta-tool for progressive tool discovery.

Instead of loading all 45+ tools into every LLM context, the agent gets
a small always-available set plus this tool. When it needs a specialized
capability, it searches for it here and the matching tools are dynamically
added to the next turn.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.skills.registry import SkillRegistry
    from odigos.tools.registry import ToolRegistry


class FindToolsTool(BaseTool):
    """Search for available tools and skills by description or capability."""

    name = "find_tools"
    category = "memory"
    description = (
        "Search for tools and skills you don't currently see. You have 40+ tools "
        "and multiple skills but only a few are loaded. Call this when you need "
        "to do something and don't have the right tool — e.g., 'generate music', "
        "'send email', 'create image', 'manage kanban', 'write a song'. "
        "Returns tool/skill names and descriptions so you can call or activate them."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Natural language description of what you need to do. "
                    "E.g., 'send email', 'manage kanban board', 'generate image', "
                    "'create a quiz', 'translate text', 'write a song'."
                ),
            },
        },
        "required": ["query"],
    }

    def __init__(self, registry: ToolRegistry, skill_registry: SkillRegistry | None = None) -> None:
        self._registry = registry
        self._skill_registry = skill_registry

    async def execute(self, params: dict) -> ToolResult:
        query = (params.get("query") or "").lower().strip()
        if not query:
            return ToolResult(success=False, data="", error="No search query provided")

        # Broad queries: list all tools grouped by category
        _BROAD_QUERIES = {"all", "everything", "list", "capabilities", "what can you do", "help"}
        if query in _BROAD_QUERIES or any(bq in query for bq in _BROAD_QUERIES):
            return self._list_all_by_category()

        query_words = set(query.split())
        matches: list[tuple[int, object | None, object | None]] = []

        # Search skills first (higher priority)
        if self._skill_registry:
            for skill in self._skill_registry.list():
                text = f"{skill.name} {skill.description}".lower()
                text_words = set(text.split())
                overlap = len(query_words & text_words)
                if query in skill.name:
                    overlap += 5
                for qw in query_words:
                    if any(qw in tw for tw in text_words):
                        overlap += 1
                if overlap > 0:
                    # Skills get +10 boost over tools
                    matches.append((overlap + 10, None, skill))

        # Then search tools
        for tool in self._registry.list():
            if tool.name == self.name:
                continue

            # Score by word overlap with name, description, and category
            text = f"{tool.name} {tool.description} {tool.category}".lower()
            text_words = set(text.split())
            overlap = len(query_words & text_words)

            # Boost exact substring matches in name or category
            if query in tool.name or query in (tool.category or ""):
                overlap += 5
            # Boost partial word matches
            for qw in query_words:
                if any(qw in tw for tw in text_words):
                    overlap += 1

            if overlap > 0:
                matches.append((overlap, tool, None))

        matches.sort(key=lambda x: x[0], reverse=True)
        top = matches[:5]

        if not top:
            return ToolResult(
                success=True,
                data="No matching tools or skills found. Try different search terms.",
            )

        lines = [
            f"Found {len(top)} capability(ies). They are now available in your tool list — "
            "call them directly with the arguments shown below. Do NOT call find_tools again "
            "for this request."
        ]
        for _, tool, skill in top:
            if skill:
                tools_str = f" (uses: {', '.join(skill.tools)})" if skill.tools else ""
                lines.append("")
                lines.append(
                    f"[SKILL] {skill.name} — {skill.description[:160]}{tools_str}"
                )
                lines.append(f'  Next step: activate_skill(name="{skill.name}")')
            elif tool:
                lines.append("")
                cat_str = f" [{tool.category}]" if tool.category else ""
                lines.append(f"[TOOL] {tool.name}{cat_str} — {tool.description[:160]}")
                # Full schema with per-param descriptions
                props = tool.parameters_schema.get("properties", {}) or {}
                required = set(tool.parameters_schema.get("required", []))
                if props:
                    lines.append("  Parameters:")
                    for pname, pinfo in props.items():
                        ptype = pinfo.get("type", "string")
                        req_marker = " (required)" if pname in required else " (optional)"
                        pdesc = (pinfo.get("description") or "")[:140]
                        lines.append(f"    - {pname} ({ptype}){req_marker}: {pdesc}")
                # Tell the model the tool is now callable, without giving a
                # literal example that small models will emit verbatim.
                if required:
                    req_list = ", ".join(sorted(required))
                    lines.append(
                        f"  To call: invoke {tool.name} with at least: {req_list} "
                        f"(use real values from the user's request or prior tool results, "
                        f"never the parameter names as values)."
                    )
                else:
                    lines.append(f"  To call: invoke {tool.name} with the parameters above as needed.")

        return ToolResult(success=True, data="\n".join(lines))

    def _list_all_by_category(self) -> ToolResult:
        """List all tools and skills grouped by category."""
        lines: list[str] = []

        # Skills section
        if self._skill_registry:
            skills = self._skill_registry.list()
            if skills:
                skill_names = ", ".join(s.name for s in skills)
                lines.append(f"**Skills** (guided workflows): {skill_names}")
                lines.append("  Use: activate_skill(name=\"skill_name\") to start a skill.\n")

        # Tools by category
        categories: dict[str, list] = {}
        for tool in self._registry.list():
            if tool.name == self.name:
                continue
            cat = tool.category or "other"
            categories.setdefault(cat, []).append(tool)

        total = sum(len(v) for v in categories.values())
        skill_count = len(self._skill_registry.list()) if self._skill_registry else 0
        header = f"All capabilities ({total} tools"
        if skill_count:
            header += f", {skill_count} skills"
        header += "):"
        lines.insert(0, header)

        for cat in sorted(categories):
            tools = categories[cat]
            tool_names = ", ".join(t.name for t in tools)
            lines.append(f"\n**{cat}**: {tool_names}")

        return ToolResult(success=True, data="\n".join(lines))
