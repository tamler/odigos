"""Tools for browsing and adopting agent templates from the agency-agents catalog."""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.core.template_index import AgentTemplateIndex
    from odigos.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class BrowseTemplates(BaseTool):
    """Browse available agent personality templates from the catalog."""

    name = "browse_agent_templates"
    description = (
        "Browse the catalog of agent personality templates. "
        "Search by role or division (e.g. 'engineering', 'marketing', 'design'), "
        "or list all available templates. Use this to find specialized roles "
        "you can adopt as skills."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "division": {
                "type": "string",
                "description": (
                    "Filter by division: engineering, design, marketing, sales, "
                    "support, testing, product, project-management, game-development, "
                    "spatial-computing, specialized, strategy, paid-media, custom. "
                    "Omit to list all."
                ),
            },
            "search": {
                "type": "string",
                "description": "Search query to filter templates by name (e.g. 'backend', 'seo', 'ux').",
            },
            "preview": {
                "type": "string",
                "description": "Template name to preview -- fetches and shows the full template content.",
            },
        },
        "required": [],
    }

    def __init__(self, template_index: AgentTemplateIndex) -> None:
        self._index = template_index

    async def execute(self, params: dict) -> ToolResult:
        preview = params.get("preview")
        if preview:
            return await self._preview(preview)

        division = params.get("division")
        search = params.get("search")

        templates = await self._index.list_templates(division=division)

        if search:
            tokens = set(re.findall(r"[a-z]+", search.lower()))
            templates = [
                t for t in templates
                if tokens & set(re.findall(r"[a-z]+", f"{t['name']} {t['division']}".lower()))
            ]

        if not templates:
            return ToolResult(
                success=True,
                data="No templates found. Try refreshing the index or a different search.",
            )

        lines = [f"Found {len(templates)} templates:\n"]
        for t in templates:
            source = "custom" if t["github_path"].startswith("custom:") else "github"
            lines.append(f"- [{t['division']}] {t['name']} ({source})")

        lines.append(
            "\nUse preview parameter with a template name to see full details, "
            "or use adopt_agent_template to add one as a skill."
        )
        return ToolResult(success=True, data="\n".join(lines))

    async def _preview(self, name: str) -> ToolResult:
        """Fetch and display a template's full content."""
        templates = await self._index.list_templates()
        match = None
        for t in templates:
            if name.lower() in t["name"].lower():
                match = t
                break

        if not match:
            return ToolResult(
                success=False, data="",
                error=f"No template matching '{name}' found.",
            )

        content = await self._index.fetch_template(match["github_path"])
        if not content:
            return ToolResult(
                success=False, data="",
                error=f"Failed to fetch template content for '{match['name']}'.",
            )

        header = f"# {match['name']} ({match['division']})\n\n"
        return ToolResult(success=True, data=header + content)


class AdoptTemplate(BaseTool):
    """Download an agent template and install it as a skill."""

    name = "adopt_agent_template"
    description = (
        "Adopt an agent personality template from the catalog as a local skill. "
        "This downloads the template and registers it so you can activate it "
        "for relevant conversations. Use browse_agent_templates first to find "
        "the right template."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "template_name": {
                "type": "string",
                "description": "Name of the template to adopt (use browse_agent_templates to find names).",
            },
            "skill_name": {
                "type": "string",
                "description": (
                    "Name for the new skill (lowercase, hyphens/underscores). "
                    "Defaults to a sanitized version of the template name."
                ),
            },
        },
        "required": ["template_name"],
    }

    def __init__(
        self,
        template_index: AgentTemplateIndex,
        skill_registry: SkillRegistry,
    ) -> None:
        self._index = template_index
        self._skills = skill_registry

    async def execute(self, params: dict) -> ToolResult:
        template_name = params.get("template_name", "")
        if not template_name:
            return ToolResult(success=False, data="", error="template_name is required.")

        # Find matching template
        templates = await self._index.list_templates()
        match = None
        for t in templates:
            if template_name.lower() in t["name"].lower():
                match = t
                break

        if not match:
            return ToolResult(
                success=False, data="",
                error=f"No template matching '{template_name}'. Use browse_agent_templates to search.",
            )

        # Fetch content
        content = await self._index.fetch_template(match["github_path"])
        if not content:
            return ToolResult(
                success=False, data="",
                error=f"Failed to fetch template '{match['name']}'. GitHub may be unreachable.",
            )

        # Determine skill name
        skill_name = params.get("skill_name") or self._sanitize_name(match["name"])

        # Check for existing skill
        existing = self._skills.get(skill_name)
        if existing and existing.builtin:
            return ToolResult(
                success=False, data="",
                error=f"Cannot overwrite built-in skill '{skill_name}'. Choose a different skill_name.",
            )

        # Create the skill
        description = f"Adopted from agency-agents: {match['division']}/{match['name']}"
        try:
            self._skills.create(
                name=skill_name,
                description=description,
                system_prompt=content,
                complexity="standard",
            )
        except ValueError as e:
            return ToolResult(success=False, data="", error=str(e))

        return ToolResult(
            success=True,
            data=(
                f"Template '{match['name']}' adopted as skill '{skill_name}'.\n"
                f"Division: {match['division']}\n"
                f"You can now activate this skill with activate_skill."
            ),
        )

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Convert a template name to a valid skill name."""
        sanitized = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        return sanitized or "adopted-template"
