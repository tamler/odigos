import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from odigos.api.rate_limit import RateLimitMiddleware

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
from odigos.api.state import router as state_router
from odigos.api.upload import router as upload_router
from odigos.channels.web import WebChannel
from odigos.core.agent_client import AgentClient
from odigos.core.cron import CronManager
from odigos.core.notifier import Notifier
from odigos.core.scheduler import Scheduler
from odigos.core.spawner import Spawner
from odigos.api.cron import router as cron_router
from odigos.api.agent_ws import router as agent_ws_router
from odigos.api.feed import router as feed_router
from odigos.api.cards import router as cards_router
from odigos.api.audio import router as audio_router
from odigos.api.auth import router as auth_router
from odigos.api.prompts import router as prompts_router
from odigos.api.documents import router as documents_router
from odigos.api.analytics import router as analytics_router
from odigos.api.notebooks import router as notebooks_router
from odigos.api.kanban import router as kanban_router
from odigos.api.artifacts import router as artifacts_router
from odigos.api.mesh import router as mesh_router
from odigos.tools.decompose import DecomposeQueryTool
from odigos.tools.notify import NotifyTool
from odigos.tools.peer import MessagePeerTool
from odigos.tools.remember_fact import RememberFactTool
from odigos.tools.settings_tool import ManageSettingsTool
from odigos.dashboard import mount_dashboard

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


async def _register_tools(
    settings, db, provider, vector_memory, chunking_service, memory_manager,
    goal_store, skill_registry, card_manager, agent_client, mesh_enabled,
    config_path, mcp_servers,
):
    """Create the tool registry and register all core tools.

    Returns (tool_registry, scraper, doc_tool, doc_ingester, markitdown_provider,
             subagent_manager, notifier).
    """
    from odigos.providers.scraper import ScraperProvider
    from odigos.tools.registry import ToolRegistry
    from odigos.tools.scrape import ScrapeTool

    scraper = ScraperProvider()
    tool_registry = ToolRegistry()

    scrape_tool = ScrapeTool(scraper=scraper)
    tool_registry.register(scrape_tool)
    logger.info("Scrape tool initialized")

    # RSS feed tool
    from odigos.tools.feed import FeedTool

    feed_tool = FeedTool()
    tool_registry.register(feed_tool)
    logger.info("Feed tool initialized (feedparser)")

    # Document processing
    from odigos.providers.markitdown import MarkItDownProvider
    from odigos.tools.document import DocTool

    markitdown_provider = MarkItDownProvider()
    docling_provider = None  # Loaded via plugin if available

    from odigos.memory.ingester import DocumentIngester

    doc_ingester = DocumentIngester(db=db, vector_memory=vector_memory, chunking_service=chunking_service)
    doc_tool = DocTool(
        markitdown_provider=markitdown_provider,
        ingester=doc_ingester,
        docling_provider=docling_provider,
    )
    tool_registry.register(doc_tool)
    logger.info("Document tool initialized (MarkItDown default, Docling %s)", "available" if docling_provider else "not installed")

    # Code execution sandbox
    from odigos.tools.code import CodeTool

    sandbox = SandboxProvider(
        timeout=settings.sandbox.timeout_seconds,
        max_memory_mb=settings.sandbox.max_memory_mb,
        allow_network=settings.sandbox.allow_network,
    )
    code_tool = CodeTool(sandbox=sandbox, db=db)
    tool_registry.register(code_tool)
    logger.info("Code tool initialized (sandbox)")

    # File tool
    from odigos.tools.file import FileTool

    file_tool = FileTool(allowed_paths=settings.file_access.allowed_paths)
    tool_registry.register(file_tool)
    logger.info("File tool initialized (allowed: %s)", settings.file_access.allowed_paths)

    # Goal tools
    from odigos.tools.goals import CreateReminderTool, CreateTodoTool, CreateGoalTool

    # scheduler may not exist yet during _register_tools; injected post-init
    tool_registry.register(CreateReminderTool(goal_store=goal_store))
    tool_registry.register(CreateTodoTool(goal_store=goal_store))
    tool_registry.register(CreateGoalTool(goal_store=goal_store))
    logger.info("Goal tools initialized")

    # Kanban tools
    from odigos.tools.kanban import (
        KanbanListBoardsTool, KanbanGetBoardTool, KanbanCreateCardTool,
        KanbanMoveCardTool, KanbanUpdateCardTool, KanbanDeleteCardTool,
    )
    tool_registry.register(KanbanListBoardsTool(db=db))
    tool_registry.register(KanbanGetBoardTool(db=db))
    tool_registry.register(KanbanCreateCardTool(db=db))
    tool_registry.register(KanbanMoveCardTool(db=db))
    tool_registry.register(KanbanUpdateCardTool(db=db))
    tool_registry.register(KanbanDeleteCardTool(db=db))
    logger.info("Kanban tools initialized")

    # Artifact tool
    from odigos.tools.artifact import CreateArtifactTool
    tool_registry.register(CreateArtifactTool(db=db))
    logger.info("Artifact tool initialized")

    # Skill tools
    from pathlib import Path as _SkillPath
    try:
        _SkillPath("skills/code").mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("Could not create skills/code/ (read-only filesystem)")

    code_skill_count = skill_registry.register_code_skills(tool_registry)
    if code_skill_count:
        logger.info("Registered %d code skill tools", code_skill_count)

    from odigos.tools.skill_tool import ActivateSkillTool
    from odigos.tools.skill_manage import CreateSkillTool, UpdateSkillTool

    tool_registry.register(ActivateSkillTool(skill_registry=skill_registry))
    tool_registry.register(CreateSkillTool(skill_registry=skill_registry, tool_registry=tool_registry))
    tool_registry.register(UpdateSkillTool(skill_registry=skill_registry, tool_registry=tool_registry))
    logger.info("Skill tools registered (activate, create, update)")

    # Subagent manager (internal use only -- no user-facing spawn tool)
    tracer_ref = None  # Will be set by caller after return
    subagent_manager = SubagentManager(
        db=db,
        provider=provider,
        tool_registry=tool_registry,
        tracer=None,
        memory_manager=memory_manager,
    )
    logger.info("Subagent manager initialized")

    # Peer messaging tool (skip in hermit mode)
    if mesh_enabled:
        tool_registry.register(MessagePeerTool(peer_client=agent_client))
        if agent_client.list_peer_names():
            logger.info("Peer messaging tool registered with pre-configured peers: %s", ", ".join(agent_client.list_peer_names()))
        else:
            logger.info("Peer messaging tool registered (discovery via announce)")

    # Card tools
    from odigos.tools.card_tools import GenerateCardTool, ImportCardTool
    tool_registry.register(GenerateCardTool(card_manager=card_manager))
    tool_registry.register(ImportCardTool(card_manager=card_manager))
    logger.info("Card tools registered")

    # Settings management tool
    tool_registry.register(ManageSettingsTool(settings=settings, config_path=config_path))
    logger.info("Settings tool registered")

    # Remember fact tool
    tool_registry.register(RememberFactTool(db=db))
    logger.info("Remember fact tool registered")

    # Feed publish tool
    if settings.feed.enabled:
        from odigos.tools.feed_publish import PublishToFeedTool
        feed_publish = PublishToFeedTool(
            db=db,
            feed_base_url=f"http://{settings.server.host}:{settings.server.port}",
        )
        tool_registry.register(feed_publish)
        logger.info("Feed publish tool registered")

    # MCP server bridges
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
                mcp_servers.append(server)
                logger.info(
                    "MCP server '%s' connected (%d tools)",
                    server_name,
                    len(mcp_tools),
                )
            except Exception:
                logger.exception("Failed to connect MCP server: %s", server_name)

    return tool_registry, scraper, doc_tool, doc_ingester, markitdown_provider, subagent_manager


async def _init_plugins(settings, tool_registry, channel_registry, tracer, doc_tool):
    """Load plugins and wire post-plugin providers.

    Returns (plugin_context, plugin_manager).
    """
    plugin_context = PluginContext(
        tool_registry=tool_registry,
        channel_registry=channel_registry,
        tracer=tracer,
        config={"settings": settings}
    )

    plugin_manager = PluginManager(plugin_context=plugin_context)
    plugin_manager.load_all("plugins")

    # Also load legacy event-hook plugins from data/plugins
    plugin_manager.load_all("data/plugins")
    logger.info("Loaded %d plugins", len(plugin_manager.loaded_plugins))

    # Check if docling plugin registered a provider
    docling_from_plugin = plugin_context.get_provider("docling")
    if docling_from_plugin:
        doc_tool.docling = docling_from_plugin
        logger.info("Docling provider loaded from plugin")

    return plugin_context, plugin_manager


def _persist_generated_api_key(config_path: str, api_key: str) -> None:
    """Append generated api_key to config.yaml so it survives restarts."""
    try:
        import yaml
        from pathlib import Path
        cp = Path(config_path)
        data = {}
        if cp.exists():
            with open(cp) as f:
                data = yaml.safe_load(f) or {}
        data["api_key"] = api_key
        with open(cp, "w") as f:
            yaml.dump(data, f, default_flow_style=False)
    except Exception:
        logger.warning("Could not persist api_key to %s", config_path)


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
        # Write to config so it persists across restarts
        _persist_generated_api_key(config_path, settings.api_key)
        logger.warning(
            "No api_key configured — generated and saved a random key to %s. "
            "View it with: grep api_key %s",
            config_path, config_path,
        )

    # Migrate old sections directory to new location
    from pathlib import Path as _Path
    _agent_dir = _Path("data/agent")
    _old_sections = _Path("data/prompt_sections")
    if _old_sections.exists() and not _agent_dir.exists():
        import shutil
        shutil.copytree(str(_old_sections), str(_agent_dir))
        logger.info("Migrated data/prompt_sections/ to data/agent/")
    if _Path("data/personality.yaml").exists():
        logger.warning("data/personality.yaml is deprecated and ignored — identity is now in data/agent/identity.md")

    app.state.settings = settings
    app.state.config_path = config_path
    app.state.env_path = ".env"
    app.state.upload_dir = "data/uploads"

    logger.info("Starting Odigos agent: %s", settings.agent.name)

    # Initialize database
    _db = Database(settings.database.path)
    await _db.initialize()
    logger.info("Database initialized at %s", settings.database.path)

    # Auto-generate SESSION_SECRET if not set
    if not settings.session_secret:
        import secrets as _secrets

        settings.session_secret = _secrets.token_urlsafe(48)
        env_path = _Path(".env")
        try:
            with open(env_path, "a") as _ef:
                _ef.write(f"\nSESSION_SECRET={settings.session_secret}\n")
            logger.info("Generated SESSION_SECRET and saved to .env")
        except PermissionError:
            logger.warning("Generated SESSION_SECRET (could not persist to .env -- read-only)")

    # Seed user from data/seed_user.json (for provisioned deploys)
    import json as _json

    _seed_path = _Path("data/seed_user.json")
    if _seed_path.exists():
        try:
            _seed = _json.loads(_seed_path.read_text())
            _row = await _db.fetch_one("SELECT COUNT(*) as count FROM users")
            if _row and _row["count"] == 0:
                import uuid as _uuid
                from odigos.api.auth import _hash_password

                _user_id = _uuid.uuid4().hex
                _now = datetime.now(timezone.utc).isoformat()
                _must_change = 1 if _seed.get("must_change_password", True) else 0
                await _db.execute(
                    "INSERT INTO users (id, username, password_hash, display_name, must_change_password, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        _user_id,
                        _seed["username"],
                        _hash_password(_seed["password"]),
                        _seed.get("display_name", ""),
                        _must_change,
                        _now,
                    ),
                )
                logger.info("Seed user '%s' created from data/seed_user.json", _seed["username"])
                _seed_path.unlink()
                logger.info("Consumed and deleted data/seed_user.json")
            else:
                _seed_path.unlink()
                logger.info("Seed user skipped (users exist), deleted seed_user.json")
        except Exception:
            logger.warning("Failed to process seed_user.json (will retry on next startup)")

    # Initialize agent client (mesh networking)
    mesh_enabled = settings.mesh.enabled
    agent_client = AgentClient(
        peers=settings.peers if mesh_enabled else [],
        agent_name=settings.agent.name,
        db=_db,
    )
    if not mesh_enabled:
        logger.info("Mesh networking disabled (hermit mode)")

    # Initialize card manager
    from odigos.core.cards import CardManager

    card_manager = CardManager(
        db=_db,
        agent_name=settings.agent.name,
        host=settings.server.host,
        ws_port=settings.server.ws_port,
        feed_base_url=f"http://{settings.server.host}:{settings.server.port}",
    )
    app.state.card_manager = card_manager
    logger.info("Card manager initialized")

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
        cite_sources=settings.agent.cite_sources,
    )
    logger.info("Memory system initialized")

    # Pre-download cross-encoder reranker model for document recall
    try:
        from sentence_transformers import CrossEncoder
        CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        logger.info("Cross-encoder reranker model ready")
    except Exception:
        logger.warning("Could not load cross-encoder reranker model")

    # Initialize corrections manager
    corrections_manager = CorrectionsManager(db=_db, vector_memory=vector_memory)
    logger.info("Corrections manager initialized")

    # Initialize goal store
    goal_store = GoalStore(db=_db)
    app.state.goal_store = goal_store
    logger.info("Goal store initialized")

    # Initialize skill registry
    skill_registry = SkillRegistry()
    skill_registry.load_all(settings.skills.path)
    logger.info("Loaded %d skills", len(skill_registry.list()))
    app.state.skill_registry = skill_registry

    # Register all core tools
    (
        tool_registry, _scraper, doc_tool, doc_ingester, markitdown_provider,
        subagent_manager,
    ) = await _register_tools(
        settings=settings,
        db=_db,
        provider=_provider,
        vector_memory=vector_memory,
        chunking_service=chunking_service,
        memory_manager=memory_manager,
        goal_store=goal_store,
        skill_registry=skill_registry,
        card_manager=card_manager,
        agent_client=agent_client,
        mesh_enabled=mesh_enabled,
        config_path=config_path,
        mcp_servers=_mcp_servers,
    )
    # Wire tracer into subagent manager (available now)
    subagent_manager.tracer = tracer
    app.state.doc_ingester = doc_ingester
    app.state.markitdown_provider = markitdown_provider

    # Initialize channel registry and load plugins
    channel_registry = ChannelRegistry()
    app.state.channel_registry = channel_registry

    plugin_context, plugin_manager = await _init_plugins(
        settings=settings,
        tool_registry=tool_registry,
        channel_registry=channel_registry,
        tracer=tracer,
        doc_tool=doc_tool,
    )
    app.state.plugin_manager = plugin_manager
    app.state.plugin_context = plugin_context

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

    # Initialize query classifier
    from odigos.core.classifier import QueryClassifier

    classifier = QueryClassifier(provider=_provider, db=_db, vector_memory=vector_memory)
    logger.info("Query classifier initialized")

    # Initialize agent
    agent = Agent(
        db=_db,
        provider=_provider,
        agent_name=settings.agent.name,
        memory_manager=memory_manager,
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
        classifier=classifier,
        reasoning_model=settings.llm.reasoning_model,
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
    agent_service.doc_ingester = doc_ingester
    agent_service.markitdown_provider = markitdown_provider
    agent_service.upload_dir = "data/uploads"
    plugin_context.set_service(agent_service)
    app.state.agent_service = agent_service

    # Wire audio providers to service for channel access
    stt_from_plugin = plugin_context.get_provider("stt")
    tts_from_plugin = plugin_context.get_provider("tts")
    if stt_from_plugin:
        agent_service.stt_provider = stt_from_plugin
    if tts_from_plugin:
        agent_service.tts_provider = tts_from_plugin

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
        sections_dir="data/agent",
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
        skill_registry=skill_registry,
    )
    logger.info("Strategist initialized")

    # Initialize agent template index and tools
    from odigos.core.template_index import AgentTemplateIndex
    template_index = AgentTemplateIndex(
        db=_db,
        repo_url=settings.templates.repo_url,
        cache_ttl_days=settings.templates.cache_ttl_days,
    )
    app.state.template_index = template_index

    logger.info("Agent template index initialized")

    # Initialize spawner
    spawner = Spawner(
        db=_db,
        provider=_provider,
        parent_name=settings.agent.name,
        llm_config=settings.llm,
        server_config=settings.server,
        template_index=template_index,
    )
    app.state.spawner = spawner
    logger.info("Spawner initialized")

    # Initialize cron manager (legacy, kept for backward compat)
    cron_manager = CronManager(db=_db)
    app.state.cron_manager = cron_manager
    logger.info("Cron manager initialized")

    # Initialize unified scheduler
    scheduler = Scheduler(db=_db)
    app.state.scheduler = scheduler
    logger.info("Unified scheduler initialized")

    # Wire scheduler into CreateReminderTool (registered during _register_tools)
    reminder_tool = tool_registry.get("create_reminder")
    if reminder_tool:
        reminder_tool.scheduler = scheduler

    # Initialize notifier
    notifier = Notifier(channel_registry=channel_registry)
    app.state.notifier = notifier
    logger.info("Notifier initialized")

    # Register notification tool
    tool_registry.register(NotifyTool(notifier=notifier))
    logger.info("Notification tool registered")

    # Register decompose query tool and plan management tools
    tool_registry.register(DecomposeQueryTool(provider=_provider))
    from odigos.tools.plan import CheckPlanTool, UpdatePlanTool
    tool_registry.register(CheckPlanTool(db=_db))
    tool_registry.register(UpdatePlanTool(db=_db))
    logger.info("Decompose, check_plan, update_plan tools registered")

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
        agent_client=agent_client if mesh_enabled else None,
        agent_role=settings.agent.role,
        agent_description=settings.agent.description,
        announce_interval=settings.heartbeat.announce_interval_seconds,
        background_model=settings.llm.background_model,
        cron_manager=cron_manager,
        notifier=notifier,
        scheduler=scheduler,
        ws_port=settings.server.ws_port,
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

    # Start WebSocket connector for mesh peers
    _ws_connector = None
    if mesh_enabled and settings.peers:
        from odigos.core.ws_connector import WSConnector
        _ws_connector = WSConnector(
            agent_client=agent_client,
            agent_name=settings.agent.name,
            peers=settings.peers,
        )
        await _ws_connector.start()
        app.state.ws_connector = _ws_connector
        logger.info("WebSocket connector started for %d peer(s)", len(settings.peers))

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
    if _ws_connector:
        await _ws_connector.stop()
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
    if hasattr(app.state, "template_index") and app.state.template_index:
        await app.state.template_index.close()
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

# Rate limiting: 10 req/s per IP with burst of 30
app.add_middleware(RateLimitMiddleware, rate=10.0, burst=30)

# CORS: only allow same-origin requests (dashboard is served from same host)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],  # No cross-origin allowed; dashboard is same-origin
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,
)

app.include_router(auth_router)
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
app.include_router(cron_router)
app.include_router(state_router)
app.include_router(agent_ws_router)
app.include_router(ws_router)
app.include_router(feed_router)
app.include_router(cards_router)
app.include_router(audio_router)
app.include_router(prompts_router)
app.include_router(documents_router)
app.include_router(analytics_router)
app.include_router(notebooks_router)
app.include_router(kanban_router)
app.include_router(artifacts_router)
app.include_router(mesh_router)


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "odigos"}

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
