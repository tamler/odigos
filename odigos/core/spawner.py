"""Spawner: generates config and seed identity for specialist agents.

Handles the planning phase of specialist creation. Actual deployment
is handled separately by the deploy tool.

When a template match is found in the agency-agents index, the spawner
uses it as a rich baseline and asks the LLM to tailor it. Otherwise
falls back to generating a short identity from scratch.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING

from odigos.core.prompt_loader import load_prompt

if TYPE_CHECKING:
    from odigos.config import LLMConfig, ServerConfig
    from odigos.core.template_index import AgentTemplateIndex
    from odigos.db import Database
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

_ADAPT_TEMPLATE_FALLBACK = (
    "Below is a specialist agent template. Adapt it into a focused identity "
    "and instruction set for an AI agent with:\n"
    "- Role: {role}\n"
    "- Description: {description}\n"
    "- Specialty: {specialty}\n\n"
    "Keep the template's personality, workflows, deliverables, and success metrics "
    "where relevant. Remove anything that doesn't apply. Write in second person "
    "('You are...'). Output only the adapted identity -- no commentary.\n\n"
    "--- TEMPLATE ---\n{template_content}"
)


class Spawner:
    """Generates specialist agent configurations and seed content."""

    def __init__(
        self,
        db: Database,
        provider: LLMProvider,
        parent_name: str,
        llm_config: LLMConfig | None = None,
        server_config: ServerConfig | None = None,
        template_index: AgentTemplateIndex | None = None,
    ) -> None:
        self.db = db
        self.provider = provider
        self.parent_name = parent_name
        self.llm_config = llm_config
        self.server_config = server_config
        self.template_index = template_index

    async def generate_config(
        self,
        agent_name: str,
        role: str,
        description: str,
        specialty: str | None = None,
    ) -> dict:
        """Generate a config.yaml structure for a new specialist agent."""
        llm = self.llm_config
        ws_port = self.server_config.ws_port if self.server_config else 8001
        return {
            "agent": {
                "name": agent_name,
                "role": role,
                "description": description,
                "parent": self.parent_name,
                "allow_external_evaluation": False,
            },
            "llm": {
                "base_url": llm.base_url if llm else "https://openrouter.ai/api/v1",
                "default_model": llm.default_model if llm else "anthropic/claude-sonnet-4",
                "fallback_model": llm.fallback_model if llm else "google/gemini-2.0-flash-001",
            },
            "peers": [
                {
                    "name": self.parent_name,
                    "netbird_ip": "",  # Filled at deploy time
                    "ws_port": ws_port,
                }
            ],
            "_specialty": specialty,
        }

    async def generate_seed_identity(
        self,
        role: str,
        description: str,
        specialty: str | None = None,
    ) -> dict:
        """Generate a seed identity for the specialist.

        Returns a dict with:
          - source: "template" or "none"
          - identity: the tailored identity text (if template found)
          - template_name: name of the matched template (if found)
          - suggestion: guidance for the caller when no match is found

        When no template matches, does NOT waste an LLM call generating
        a generic blurb. Instead returns a signal so the caller can
        research and build a proper identity using available tools.
        """
        template_content = await self._find_template(role, specialty)

        if template_content:
            identity = await self._identity_from_template(
                template_content, role, description, specialty,
            )
            match = await self.template_index.match_template(role, specialty) if self.template_index else None
            return {
                "source": "template",
                "identity": identity,
                "template_name": match["name"] if match else "unknown",
            }

        return {
            "source": "none",
            "identity": "",
            "suggestion": (
                f"No template found for role='{role}' specialty='{specialty or 'general'}'. "
                f"Use browse_agent_templates to search the catalog, or use research skills "
                f"to build a custom identity for this specialization. You can create a "
                f"custom template with create_custom_template for future spawns."
            ),
        }

    async def _find_template(self, role: str, specialty: str | None) -> str | None:
        """Try to find and fetch a matching template."""
        if not self.template_index:
            return None

        match = await self.template_index.match_template(role, specialty)
        if not match:
            logger.debug("No template match for role=%s specialty=%s", role, specialty)
            return None

        logger.info(
            "Template match: %s/%s for role=%s specialty=%s",
            match["division"], match["name"], role, specialty,
        )
        content = await self.template_index.fetch_template(match["github_path"])
        if not content:
            logger.warning("Failed to fetch template content for %s", match["github_path"])
        return content

    async def _identity_from_template(
        self,
        template_content: str,
        role: str,
        description: str,
        specialty: str | None,
    ) -> str:
        """Tailor a template to the specific agent context."""
        adapt_template = load_prompt("spawner_adapt.md", _ADAPT_TEMPLATE_FALLBACK)
        prompt = adapt_template.format(
            role=role,
            description=description,
            specialty=specialty or 'general',
            template_content=template_content,
        )
        response = await self.provider.complete(
            [{"role": "user", "content": prompt}],
            model=getattr(self.provider, "fallback_model", None),
            max_tokens=1500,
            temperature=0.4,
        )
        return response.content.strip()


    async def gather_seed_knowledge(
        self,
        specialty: str,
        limit: int = 20,
    ) -> list[dict]:
        """Gather relevant improvement signals from evaluations matching the specialty."""
        rows = await self.db.fetch_all(
            "SELECT task_type, overall_score, improvement_signal, created_at "
            "FROM evaluations "
            "WHERE task_type = ? AND improvement_signal IS NOT NULL "
            "ORDER BY created_at DESC LIMIT ?",
            (specialty, limit),
        )
        return [dict(r) for r in rows]

    async def record_spawn(
        self,
        agent_name: str,
        role: str,
        description: str,
        config_snapshot: dict,
        proposal_id: str | None = None,
    ) -> str:
        """Record a spawn attempt in the database."""
        spawn_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO spawned_agents "
            "(id, agent_name, role, description, proposal_id, config_snapshot, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'deploying')",
            (spawn_id, agent_name, role, description, proposal_id, json.dumps(config_snapshot)),
        )
        return spawn_id

    async def spawn(
        self,
        agent_name: str,
        role: str,
        description: str,
        specialty: str | None = None,
        proposal_id: str | None = None,
    ) -> dict:
        """Full spawn pipeline: config + identity + knowledge + record.

        Returns the spawn record with all generated artifacts.
        Does NOT deploy -- that's handled by the deploy tool.
        """
        config = await self.generate_config(
            agent_name=agent_name,
            role=role,
            description=description,
            specialty=specialty,
        )

        identity = await self.generate_seed_identity(
            role=role, description=description, specialty=specialty,
        )

        knowledge = await self.gather_seed_knowledge(specialty or role)

        spawn_id = await self.record_spawn(
            agent_name=agent_name,
            role=role,
            description=description,
            config_snapshot=config,
            proposal_id=proposal_id,
        )

        return {
            "spawn_id": spawn_id,
            "config": config,
            "identity": identity,
            "seed_knowledge": knowledge,
        }
