"""Dependency container holding all initialized services."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from odigos.channels.base import ChannelRegistry
    from odigos.config import Settings
    from odigos.core.agent import Agent
    from odigos.core.agent_client import AgentClient
    from odigos.core.agent_service import AgentService
    from odigos.core.budget import BudgetTracker
    from odigos.core.checkpoint import CheckpointManager
    from odigos.core.cron import CronManager
    from odigos.core.evolution import EvolutionEngine
    from odigos.core.goal_store import GoalStore
    from odigos.core.heartbeat import Heartbeat
    from odigos.core.notifier import Notifier
    from odigos.core.plugin_context import PluginContext
    from odigos.core.plugins import PluginManager
    from odigos.core.scheduler import Scheduler
    from odigos.core.spawner import Spawner
    from odigos.core.template_index import AgentTemplateIndex
    from odigos.core.trace import Tracer
    from odigos.channels.web import WebChannel
    from odigos.db import Database
    from odigos.memory.ingester import DocumentIngester
    from odigos.memory.manager import MemoryManager
    from odigos.memory.vectors import VectorMemory
    from odigos.providers.embeddings import EmbeddingProvider
    from odigos.providers.llm import LLMClient
    from odigos.providers.markitdown import MarkItDownProvider
    from odigos.skills.registry import SkillRegistry
    from odigos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class Container:
    # Phase 1: Config & Database
    settings: Settings | None = None
    config_path: str = "config.yaml"
    env_path: str = ".env"
    upload_dir: str = ""
    db: Database | None = None

    # Phase 2: LLM
    llm_provider: LLMClient | None = None

    # Phase 3: Embeddings
    embeddings: EmbeddingProvider | None = None

    # Phase 4: Memory
    vector_memory: VectorMemory | None = None
    memory_manager: MemoryManager | None = None

    # Phase 5: Tools
    tool_registry: ToolRegistry | None = None

    # Phase 6: Plugins & Channels
    plugin_manager: PluginManager | None = None
    plugin_context: PluginContext | None = None
    channel_registry: ChannelRegistry | None = None
    web_channel: WebChannel | None = None

    # Core services
    agent: Agent | None = None
    agent_service: AgentService | None = None
    agent_client: AgentClient | None = None
    budget_tracker: BudgetTracker | None = None
    goal_store: GoalStore | None = None
    skill_registry: SkillRegistry | None = None
    checkpoint_manager: CheckpointManager | None = None
    evolution_engine: EvolutionEngine | None = None
    template_index: AgentTemplateIndex | None = None
    spawner: Spawner | None = None
    cron_manager: CronManager | None = None
    scheduler: Scheduler | None = None
    notifier: Notifier | None = None
    card_manager: Any = None
    tracer: Tracer | None = None
    doc_ingester: DocumentIngester | None = None
    markitdown_provider: MarkItDownProvider | None = None

    # Audio
    stt_provider: Any = None
    tts_provider: Any = None

    # Security
    vapid_keys: dict | None = None

    # Phase 7: Background
    heartbeat: Heartbeat | None = None
    heavy_pool: ThreadPoolExecutor | None = None

    # Internal refs for cleanup
    _scraper: Any = field(default=None, repr=False)
    _mcp_servers: list = field(default_factory=list, repr=False)
    _ws_connector: Any = field(default=None, repr=False)

    async def shutdown(self) -> None:
        """Clean shutdown of all components in reverse order."""
        if self.heavy_pool:
            self.heavy_pool.shutdown(wait=False)
        if self._ws_connector:
            await self._ws_connector.stop()
        if self.heartbeat:
            await self.heartbeat.stop()
        if self.channel_registry:
            for ch in self.channel_registry.all():
                try:
                    await ch.stop()
                except Exception:
                    logger.exception("Error stopping channel: %s", ch.channel_name)
        for server in self._mcp_servers:
            try:
                await server.disconnect()
            except Exception:
                logger.exception("Error disconnecting MCP server: %s", server.name)
        self._mcp_servers.clear()
        if self.template_index:
            await self.template_index.close()
        if self._scraper:
            await self._scraper.close()
        if self.embeddings:
            await self.embeddings.close()
        if self.llm_provider:
            await self.llm_provider.close()
        if self.db:
            await self.db.close()
        logger.info("Container shutdown complete.")
