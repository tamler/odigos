import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from odigos.channels.telegram import TelegramChannel
from odigos.config import load_settings
from odigos.core.agent import Agent
from odigos.core.heartbeat import Heartbeat
from odigos.core.goal_store import GoalStore
from odigos.db import Database
from odigos.memory.graph import EntityGraph
from odigos.memory.manager import MemoryManager
from odigos.memory.resolver import EntityResolver
from odigos.memory.summarizer import ConversationSummarizer
from odigos.memory.vectors import VectorMemory
from odigos.providers.embeddings import EmbeddingProvider
from odigos.providers.openrouter import OpenRouterProvider
from odigos.providers.sandbox import SandboxProvider
from odigos.core.budget import BudgetTracker
from odigos.core.router import ModelRouter
from odigos.skills.registry import SkillRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Module-level references for cleanup
_db: Database | None = None
_provider: OpenRouterProvider | None = None
_embedder: EmbeddingProvider | None = None
_telegram: TelegramChannel | None = None
_searxng = None
_scraper = None
_router: ModelRouter | None = None
_heartbeat: Heartbeat | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for FastAPI."""
    global _db, _provider, _embedder, _telegram, _searxng, _scraper, _router, _heartbeat

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    settings = load_settings(config_path)

    logger.info("Starting Odigos agent: %s", settings.agent.name)

    # Initialize database
    _db = Database(settings.database.path)
    await _db.initialize()
    logger.info("Database initialized at %s", settings.database.path)

    # Initialize LLM provider
    _provider = OpenRouterProvider(
        api_key=settings.openrouter_api_key,
        default_model=settings.openrouter.default_model,
        fallback_model=settings.openrouter.fallback_model,
        max_tokens=settings.openrouter.max_tokens,
        temperature=settings.openrouter.temperature,
    )

    # Initialize model router (wraps provider for free model pool)
    _router = ModelRouter(
        provider=_provider,
        free_pool=settings.router.free_pool,
        rate_limit_rpm=settings.router.rate_limit_rpm,
    )
    logger.info(
        "Model router initialized with %d free models",
        len(settings.router.free_pool),
    )

    # Initialize budget tracker
    budget_tracker = BudgetTracker(
        db=_db,
        daily_limit=settings.budget.daily_limit_usd,
        monthly_limit=settings.budget.monthly_limit_usd,
    )
    logger.info("Budget tracker initialized")

    # Initialize embedding provider
    _embedder = EmbeddingProvider(api_key=settings.openrouter_api_key)

    # Initialize memory stack
    vector_memory = VectorMemory(db=_db, embedder=_embedder)
    await vector_memory.initialize()

    graph = EntityGraph(db=_db)
    resolver = EntityResolver(graph=graph, vector_memory=vector_memory)
    summarizer = ConversationSummarizer(db=_db, vector_memory=vector_memory, llm_provider=_provider)
    memory_manager = MemoryManager(
        vector_memory=vector_memory,
        graph=graph,
        resolver=resolver,
        summarizer=summarizer,
    )
    logger.info("Memory system initialized")

    # Initialize tool registry and tools
    from odigos.providers.scraper import ScraperProvider
    from odigos.tools.registry import ToolRegistry
    from odigos.tools.scrape import ScrapeTool

    _scraper = ScraperProvider()
    tool_registry = ToolRegistry()

    scrape_tool = ScrapeTool(scraper=_scraper)
    tool_registry.register(scrape_tool)
    logger.info("Scrape tool initialized")

    # Add search tool if SearXNG is configured
    if settings.searxng_url:
        from odigos.providers.searxng import SearxngProvider
        from odigos.tools.search import SearchTool

        _searxng = SearxngProvider(
            url=settings.searxng_url,
            username=settings.searxng_username,
            password=settings.searxng_password,
        )
        search_tool = SearchTool(searxng=_searxng)
        tool_registry.register(search_tool)
        logger.info("Search tool initialized (SearXNG: %s)", settings.searxng_url)

    # Initialize document processing
    from odigos.providers.docling import DoclingProvider
    from odigos.tools.document import DocTool

    docling_provider = DoclingProvider()
    doc_tool = DocTool(provider=docling_provider)
    tool_registry.register(doc_tool)
    logger.info("Document tool initialized (docling)")

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

    # Initialize goal store
    goal_store = GoalStore(db=_db)
    logger.info("Goal store initialized")

    # Initialize skill registry
    skill_registry = SkillRegistry()
    skill_registry.load_all(settings.skills.path)
    logger.info("Loaded %d skills", len(skill_registry.list()))

    # Create delayed cost fetcher for async backfill
    async def _delayed_cost_fetcher(generation_id: str) -> float | None:
        await asyncio.sleep(2)
        return await _provider.fetch_generation_cost(generation_id)

    # Initialize agent
    agent = Agent(
        db=_db,
        provider=_router,
        agent_name=settings.agent.name,
        memory_manager=memory_manager,
        personality_path=settings.personality.path,
        planner_provider=_router,
        tool_registry=tool_registry,
        skill_registry=skill_registry,
        cost_fetcher=_delayed_cost_fetcher,
        goal_store=goal_store,
        budget_tracker=budget_tracker,
    )

    # Initialize Telegram channel (before heartbeat so we can pass it)
    _telegram = TelegramChannel(
        token=settings.telegram_bot_token,
        agent=agent,
        mode=settings.telegram.mode,
        webhook_url=settings.telegram.webhook_url,
        goal_store=goal_store,
        budget_tracker=budget_tracker,
    )

    # Initialize heartbeat
    _heartbeat = Heartbeat(
        db=_db,
        agent=agent,
        telegram_channel=_telegram,
        goal_store=goal_store,
        provider=_router,
        interval=settings.heartbeat.interval_seconds,
        max_todos_per_tick=settings.heartbeat.max_todos_per_tick,
        idle_think_interval=settings.heartbeat.idle_think_interval,
    )

    # Pass heartbeat to telegram for /stop and /start commands
    _telegram.heartbeat = _heartbeat

    await _telegram.start()
    logger.info("Telegram channel started in %s mode", settings.telegram.mode)

    # Start heartbeat loop
    await _heartbeat.start()
    logger.info("Heartbeat started (interval=%ds)", settings.heartbeat.interval_seconds)

    logger.info("Odigos is ready.")

    yield

    # Shutdown
    logger.info("Shutting down Odigos...")
    if _heartbeat:
        await _heartbeat.stop()
    if _telegram:
        await _telegram.stop()
    if _scraper:
        await _scraper.close()
    if _searxng:
        await _searxng.close()
    if _embedder:
        await _embedder.close()
    if _router:
        await _router.close()
    if _db:
        await _db.close()
    logger.info("Odigos stopped.")


app = FastAPI(title="Odigos", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "odigos"}


def main():
    import uvicorn

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    settings = load_settings(config_path)

    uvicorn.run(
        "odigos.main:app",
        host=settings.server.host,
        port=settings.server.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
