"""Spawner: generates config and seed identity for specialist agents.

Handles the planning phase of specialist creation. Actual deployment
is handled separately by the deploy tool.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.config import LLMConfig, ServerConfig
    from odigos.db import Database
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class Spawner:
    """Generates specialist agent configurations and seed content."""

    def __init__(
        self,
        db: Database,
        provider: LLMProvider,
        parent_name: str,
        llm_config: LLMConfig | None = None,
        server_config: ServerConfig | None = None,
    ) -> None:
        self.db = db
        self.provider = provider
        self.parent_name = parent_name
        self.llm_config = llm_config
        self.server_config = server_config

    async def generate_config(
        self,
        agent_name: str,
        role: str,
        description: str,
        specialty: str | None = None,
        deploy_target: str = "",
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
            "_deploy_target": deploy_target,
            "_specialty": specialty,
        }

    async def generate_seed_identity(
        self,
        role: str,
        description: str,
        specialty: str | None = None,
    ) -> str:
        """Generate a seed identity.md prompt section for the specialist."""
        prompt = (
            f"Write a brief identity statement (2-3 sentences) for an AI agent with:\n"
            f"- Role: {role}\n"
            f"- Description: {description}\n"
            f"- Specialty: {specialty or 'general'}\n\n"
            f"The identity should define the agent's core purpose and approach. "
            f"Write in second person ('You are...'). Be specific, not generic."
        )
        response = await self.provider.complete(
            [{"role": "user", "content": prompt}],
            model=getattr(self.provider, "fallback_model", None),
            max_tokens=150,
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
        deploy_target: str,
        config_snapshot: dict,
        proposal_id: str | None = None,
    ) -> str:
        """Record a spawn attempt in the database."""
        spawn_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO spawned_agents "
            "(id, agent_name, role, description, deploy_target, proposal_id, config_snapshot, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'deploying')",
            (spawn_id, agent_name, role, description, deploy_target, proposal_id, json.dumps(config_snapshot)),
        )
        return spawn_id

    async def spawn(
        self,
        agent_name: str,
        role: str,
        description: str,
        specialty: str | None = None,
        deploy_target: str = "",
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
            deploy_target=deploy_target,
        )

        identity = await self.generate_seed_identity(
            role=role, description=description, specialty=specialty,
        )

        knowledge = await self.gather_seed_knowledge(specialty or role)

        spawn_id = await self.record_spawn(
            agent_name=agent_name,
            role=role,
            description=description,
            deploy_target=deploy_target,
            config_snapshot=config,
            proposal_id=proposal_id,
        )

        return {
            "spawn_id": spawn_id,
            "config": config,
            "identity": identity,
            "seed_knowledge": knowledge,
        }
