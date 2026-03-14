import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from odigos.channels.base import ChannelRegistry
from odigos.config import load_settings
from odigos.core.agent import Agent
from odigos.core.heartbeat import Heartbeat
from odigos.core.goal_store import GoalStore
from odigos.db import Database
from odigos.memory.graph import EntityGraph
from odigos.memory.manager import MemoryManager
from odigos.memory.resolver import EntityResolver
from odigos.memory.summarizer import ConversationSummarizer
from odigos.memory.corrections import CorrectionsManager
from odigos.memory.vectors import VectorMemory
from odigos.providers.embeddings import EmbeddingProvider
from odigos.providers.llm import LLMClient
from odigos.providers.sandbox import SandboxProvider
from odigos.core.budget import BudgetTracker
from odigos.core.plugin_context import PluginContext
from odigos.core.plugins import PluginManager
from odigos.core.subagent import SubagentManager
from odigos.core.trace import Tracer
from odigos.skills.registry import SkillRegistry

from odigos.api.agent_message import router as agent_message_router
from odigos.api.conversations import router as conversations_router
from odigos.api.goals import router as goals_router
from odigos.api.memory import router as memory_router
from odigos.api.budget import router as budget_router
from odigos.api.metrics import router as metrics_router
from odigos.api.plugins import router as plugins_router
from odigos.api.settings import router as settings_router
from odigos.api.skills import router as skills_router
from odigos.api.message import router as message_router
from odigos.api.ws import router as ws_router
from odigos.api.setup import router as setup_router
from odigos.api.evolution import router as evolution_router
from odigos.api.agents import router as agents_router
from odigos.api.upload import router as upload_router
from odigos.channels.web import WebChannel
from odigos.core.agent_client import AgentClient
from odigos.core.spawner import Spawner
from odigos.api.agent_ws import router as agent_ws_router
from odigos.tools.peer import MessagePeerTool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Module-level references for cleanup
_db: Database | None = None
_provider: LLMClient | None = None
_embedder: EmbeddingProvider | None = None
_channel_registry: ChannelRegistry | None = None
_scraper = None
_heartbeat: Heartbeat | None = None
_mcp_servers: list = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for FastAPI."""
    global _db, _provider, _embedder, _channel_registry, _scraper, _heartbeat, _mcp_servers

    config_path = os.environ.get("ODIGOS_CONFIG", "config.yaml")
    settings = load_settings(config_path)

    # Auto-generate API key if not configured
    if not settings.api_key:
        import secrets

        settings.api_key = secrets.token_urlsafe(32)
        logger.warning(
            "No api_key configured — generated a random key for this session: %s",
            settings.api_key,
        )
        logger.warning(
            "Set 'api_key' in your config.yaml to use a persistent key."
        )

    app.state.settings = settings
    app.state.config_path = config_path
    app.state.env_path = ".env"
    app.state.upload_dir = "data/uploads"

    logger.info("Starting Odigos agent: %s", settings.agent.name)

    # Initialize database
    _db = Database(settings.database.path)
    await _db.initialize()
    logger.info("Database initialized at %s", settings.database.path)

    # Initialize agent client (WebSocket-primary, HTTP-fallback)
    agent_client = AgentClient(
        peers=settings.peers,
        agent_name=settings.agent.name,
        db=_db,
    )

    # Initialize tracer
    tracer = Tracer(db=_db)
    logger.info("Tracer initialized")

    # Initialize LLM provider (OpenAI-compatible)
    _provider = LLMClient(
        base_url=settings.llm.base_url,
        api_key=settings.llm_api_key,
        default_model=settings.llm.default_model,
        fallback_model=settings.llm.fallback_model,
        max_tokens=settings.llm.max_tokens,
        temperature=settings.llm.temperature,
        request_timeout=settings.llm.request_timeout_seconds,
        connect_timeout=settings.llm.connect_timeout_seconds,
    )

    # Initialize budget tracker
    budget_tracker = BudgetTracker(
        db=_db,
        daily_limit=settings.budget.daily_limit_usd,
        monthly_limit=settings.budget.monthly_limit_usd,
        warn_threshold=settings.budget.warn_threshold,
    )
    app.state.budget_tracker = budget_tracker
    logger.info("Budget tracker initialized")

    # Initialize local embedding provider
    _embedder = EmbeddingProvider()

    # Initialize memory stack
    vector_memory = VectorMemory(embedder=_embedder, db=_db)

    from odigos.memory.chunking import ChunkingService

    chunking_service = ChunkingService()

    graph = EntityGraph(db=_db)
    resolver = EntityResolver(graph=graph, vector_memory=vector_memory)
    summarizer = ConversationSummarizer(db=_db, vector_memory=vector_memory, llm_provider=_provider)
    memory_manager = MemoryManager(
        vector_memory=vector_memory,
        graph=graph,
        resolver=resolver,
        summarizer=summarizer,
        chunking_service=chunking_service,
    )
    logger.info("Memory system initialized")

    # Initialize corrections manager
    corrections_manager = CorrectionsManager(db=_db, vector_memory=vector_memory)
    logger.info("Corrections manager initialized")

    # Initialize tool registry and tools
    from odigos.providers.scraper import ScraperProvider
    from odigos.tools.registry import ToolRegistry
    from odigos.tools.scrape import ScrapeTool

    _scraper = ScraperProvider()
    tool_registry = ToolRegistry()

    scrape_tool = ScrapeTool(scraper=_scraper)
    tool_registry.register(scrape_tool)
    logger.info("Scrape tool initialized")

    # Initialize RSS feed tool
    from odigos.tools.feed import FeedTool

    feed_tool = FeedTool()
    tool_registry.register(feed_tool)
    logger.info("Feed tool initialized (feedparser)")

    # Initialize document processing
    from odigos.providers.markitdown import MarkItDownProvider
    from odigos.tools.document import DocTool

    markitdown_provider = MarkItDownProvider()

    docling_provider = None  # Loaded via plugin if available

    from odigos.memory.ingester import DocumentIngester

    doc_ingester = DocumentIngester(db=_db, vector_memory=vector_memory, chunking_service=chunking_service)
    doc_tool = DocTool(
        markitdown_provider=markitdown_provider,
        ingester=doc_ingester,
        docling_provider=docling_provider,
    )
    tool_registry.register(doc_tool)
    logger.info("Document tool initialized (MarkItDown default, Docling %s)", "available" if docling_provider else "not installed")

    # Initialize code execution sandbox
    from odigos.tools.code import CodeTool

    sandbox = SandboxProvider(
        timeout=settings.sandbox.timeout_seconds,
        max_memory_mb=settings.sandbox.max_memory_mb,
        allow_network=settings.sandbox.allow_network,
    )
    code_tool = CodeTool(sandbox=sandbox)
    tool_registry.register(code_tool)
    logger.info("Code tool initialized (sandbox)")

    # Initialize file tool with configured allowed paths
    from odigos.tools.file import FileTool

    file_tool = FileTool(allowed_paths=settings.file_access.allowed_paths)
    tool_registry.register(file_tool)
    logger.info("File tool initialized (allowed: %s)", settings.file_access.allowed_paths)

    # Initialize goal store
    goal_store = GoalStore(db=_db)
    app.state.goal_store = goal_store
    logger.info("Goal store initialized")

    # Register goal tools
    from odigos.tools.goals import CreateReminderTool, CreateTodoTool, CreateGoalTool

    tool_registry.register(CreateReminderTool(goal_store=goal_store))
    tool_registry.register(CreateTodoTool(goal_store=goal_store))
    tool_registry.register(CreateGoalTool(goal_store=goal_store))
    logger.info("Goal tools initialized")

    # Initialize skill registry
    skill_registry = SkillRegistry()
    skill_registry.load_all(settings.skills.path)
    logger.info("Loaded %d skills", len(skill_registry.list()))
    app.state.skill_registry = skill_registry

    # Register skill tools (activation, creation, update)
    from odigos.tools.skill_tool import ActivateSkillTool
    from odigos.tools.skill_manage import CreateSkillTool, UpdateSkillTool

    activate_skill_tool = ActivateSkillTool(skill_registry=skill_registry)
    tool_registry.register(activate_skill_tool)

    create_skill_tool = CreateSkillTool(skill_registry=skill_registry)
    tool_registry.register(create_skill_tool)

    update_skill_tool = UpdateSkillTool(skill_registry=skill_registry)
    tool_registry.register(update_skill_tool)

    logger.info("Skill tools registered (activate, create, update)")

    # Initialize subagent manager
    subagent_manager = SubagentManager(
        db=_db,
        provider=_provider,
        tool_registry=tool_registry,
        tracer=tracer,
        memory_manager=memory_manager,
    )
    logger.info("Subagent manager initialized")

    # Register subagent tool
    from odigos.tools.subagent_tool import SpawnSubagentTool

    spawn_tool = SpawnSubagentTool(subagent_manager=subagent_manager)
    tool_registry.register(spawn_tool)
    logger.info("Subagent tool registered")

    # Register peer messaging tool if peers are configured
    if agent_client.list_peer_names():
        tool_registry.register(MessagePeerTool(peer_client=agent_client))
        logger.info("Peer messaging tool registered for peers: %s", ", ".join(agent_client.list_peer_names()))

    # Connect MCP servers and register bridged tools
    if settings.mcp.servers:
        from odigos.tools.mcp_bridge import MCPServer, MCPToolBridge, StdioTransport

        for server_name, server_cfg in settings.mcp.servers.items():
            transport = StdioTransport(
                command=server_cfg.command,
                args=server_cfg.args,
                env=server_cfg.env,
            )
            server = MCPServer(name=server_name, transport=transport)
            try:
                await server.connect()
                mcp_tools = await server.list_tools()
                for mcp_tool in mcp_tools:
                    bridge = MCPToolBridge(
                        server=server, server_name=server_name, mcp_tool=mcp_tool
                    )
                    if tool_registry.get(bridge.name):
                        logger.warning(
                            "MCP tool name collision: '%s' overwrites existing tool",
                            bridge.name,
                        )
                    tool_registry.register(bridge)
                    logger.info("Registered MCP tool: %s", bridge.name)
                _mcp_servers.append(server)
                logger.info(
                    "MCP server '%s' connected (%d tools)",
                    server_name,
                    len(mcp_tools),
                )
            except Exception:
                logger.exception("Failed to connect MCP server: %s", server_name)

    # Initialize channel registry
    channel_registry = ChannelRegistry()
    app.state.channel_registry = channel_registry

    # Create plugin context with all registries
    plugin_context = PluginContext(
        tool_registry=tool_registry,
        channel_registry=channel_registry,
        tracer=tracer,
        config={"settings": settings}
    )

    # Load plugins — new register(ctx) pattern + legacy hooks
    plugin_manager = PluginManager(plugin_context=plugin_context)
    plugin_manager.load_all("plugins")

    # Also load legacy event-hook plugins from data/plugins
    plugin_manager.load_all("data/plugins")
    logger.info("Loaded %d plugins", len(plugin_manager.loaded_plugins))
    app.state.plugin_manager = plugin_manager

    # Check if docling plugin registered a provider
    docling_from_plugin = plugin_context.get_provider("docling")
    if docling_from_plugin:
        # Update the doc tool with the plugin-provided docling
        doc_tool.docling = docling_from_plugin
        logger.info("Docling provider loaded from plugin")

    # Initialize approval gate if enabled
    approval_gate = None
    if settings.approval.enabled and settings.approval.tools:
        from odigos.core.approval import ApprovalGate

        approval_gate = ApprovalGate(
            db=_db,
            tools_requiring_approval=settings.approval.tools,
            channel_registry=channel_registry,
            timeout=settings.approval.timeout,
        )
        logger.info(
            "Approval gate enabled for %d tools: %s",
            len(settings.approval.tools),
            ", ".join(settings.approval.tools),
        )

    # Initialize agent
    agent = Agent(
        db=_db,
        provider=_provider,
        agent_name=settings.agent.name,
        memory_manager=memory_manager,
        personality_path=settings.personality.path,
        tool_registry=tool_registry,
        skill_registry=skill_registry,
        cost_fetcher=None,
        budget_tracker=budget_tracker,
        max_tool_turns=settings.agent.max_tool_turns,
        run_timeout=settings.agent.run_timeout_seconds,
        summarizer=summarizer,
        corrections_manager=corrections_manager,
        tracer=tracer,
        approval_gate=approval_gate,
    )
    app.state.agent = agent

    # Create AgentService facade for interaction interfaces
    from odigos.core.agent_service import AgentService

    agent_service = AgentService(
        agent=agent,
        goal_store=goal_store,
        budget_tracker=budget_tracker,
        approval_gate=approval_gate,
    )
    plugin_context.set_service(agent_service)
    app.state.agent_service = agent_service

    # Phase 2: Load channel plugins (need AgentService)
    plugin_manager.load_channels("plugins")
    logger.info("Channel plugins loaded")

    # Initialize WebChannel for WebSocket-based web dashboard
    web_channel = WebChannel()
    channel_registry.register("web", web_channel)
    web_channel.setup_tracer_forwarding(tracer)
    app.state.db = _db
    app.state.vector_memory = vector_memory
    app.state.web_channel = web_channel
    app.state.agent_client = agent_client

    _channel_registry = channel_registry

    # Initialize evolution engine
    from odigos.core.checkpoint import CheckpointManager
    from odigos.core.evaluator import Evaluator
    from odigos.core.evolution import EvolutionEngine

    checkpoint_manager = CheckpointManager(
        db=_db,
        sections_dir="data/prompt_sections",
        personality_path=settings.personality.path,
        skills_dir=settings.skills.path,
    )
    evaluator = Evaluator(
        db=_db,
        provider=_provider,
        qualified_evaluator_min_score=settings.evolution.qualified_evaluator_min_score,
    )
    evolution_engine = EvolutionEngine(
        db=_db,
        checkpoint_manager=checkpoint_manager,
        evaluator=evaluator,
        provider=_provider,
        evolution_config=settings.evolution,
    )
    agent.context_assembler.checkpoint_manager = checkpoint_manager
    app.state.checkpoint_manager = checkpoint_manager
    app.state.evolution_engine = evolution_engine
    logger.info("Evolution engine initialized")

    # Initialize strategist
    from odigos.core.strategist import Strategist

    # Gather tool names for strategist context
    tool_names = [t.name for t in tool_registry.list()] if hasattr(tool_registry, 'list') else []

    strategist = Strategist(
        db=_db,
        provider=_provider,
        evolution_engine=evolution_engine,
        agent_description=settings.agent.description,
        agent_tools=tool_names,
        evolution_config=settings.evolution,
    )
    logger.info("Strategist initialized")

    # Initialize spawner
    spawner = Spawner(
        db=_db,
        provider=_provider,
        parent_name=settings.agent.name,
        llm_config=settings.llm,
        server_config=settings.server,
    )
    app.state.spawner = spawner
    logger.info("Spawner initialized")

    # Initialize heartbeat
    _heartbeat = Heartbeat(
        db=_db,
        agent=agent,
        channel_registry=channel_registry,
        goal_store=goal_store,
        provider=_provider,
        interval=settings.heartbeat.interval_seconds,
        max_todos_per_tick=settings.heartbeat.max_todos_per_tick,
        idle_think_interval=settings.heartbeat.idle_think_interval,
        tracer=tracer,
        subagent_manager=subagent_manager,
        evolution_engine=evolution_engine,
        strategist=strategist,
        agent_client=agent_client,
        agent_role=settings.agent.role,
        agent_description=settings.agent.description,
        announce_interval=settings.heartbeat.announce_interval_seconds,
        background_model=settings.llm.background_model,
    )

    # Set heartbeat on agent so any channel can access it
    agent.heartbeat = _heartbeat

    # Start all registered channels
    for ch in channel_registry.all():
        await ch.start()
        logger.info("Channel '%s' started", ch.channel_name)

    # Start heartbeat loop
    await _heartbeat.start()
    logger.info("Heartbeat started (interval=%ds)", settings.heartbeat.interval_seconds)

    # Warn if binding to all interfaces without TLS
    if settings.server.host == "0.0.0.0":
        logger.warning(
            "Server bound to 0.0.0.0 (all interfaces) without TLS. "
            "Use a reverse proxy with TLS in production, or bind to 127.0.0.1 for local-only access."
        )

    logger.info("Odigos is ready.")

    yield

    # Shutdown
    logger.info("Shutting down Odigos...")
    if _heartbeat:
        await _heartbeat.stop()
    for ch in channel_registry.all():
        try:
            await ch.stop()
        except Exception:
            logger.exception("Error stopping channel: %s", ch.channel_name)
    for server in _mcp_servers:
        try:
            await server.disconnect()
        except Exception:
            logger.exception("Error disconnecting MCP server: %s", server.name)
    _mcp_servers.clear()
    if _scraper:
        await _scraper.close()
    if _embedder:
        await _embedder.close()
    if _provider:
        await _provider.close()
    if _db:
        await _db.close()
    logger.info("Odigos stopped.")


app = FastAPI(title="Odigos", lifespan=lifespan)

app.include_router(setup_router)
app.include_router(agent_message_router)
app.include_router(conversations_router)
app.include_router(goals_router)
app.include_router(memory_router)
app.include_router(budget_router)
app.include_router(metrics_router)
app.include_router(plugins_router)
app.include_router(settings_router)
app.include_router(skills_router)
app.include_router(message_router)
app.include_router(upload_router)
app.include_router(evolution_router)
app.include_router(agents_router)
app.include_router(agent_ws_router)
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "odigos"}

from odigos.dashboard import mount_dashboard
mount_dashboard(app)


def main():
    import uvicorn

    config_path = os.environ.get("ODIGOS_CONFIG", "config.yaml")
    settings = load_settings(config_path)

    uvicorn.run(
        "odigos.main:app",
        host=settings.server.host,
        port=settings.server.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
