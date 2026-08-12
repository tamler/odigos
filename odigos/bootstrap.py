"""Phased bootstrapper for Odigos agent initialization.

Each phase returns its product and can be tested independently.
Phases 1-4 are critical (fail fast). Phases 5-7 are non-critical
(catch exceptions, log warnings, continue).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from odigos import aio
from odigos.config import Settings
from odigos.container import Container

logger = logging.getLogger(__name__)


def _enforce_hosted_security(settings, bwrap_present: bool | None = None) -> None:
    """In hosted mode, refuse insecure dev overrides and require working bubblewrap."""
    if settings.deployment.mode != "hosted":
        return
    if os.environ.get("ODIGOS_SANDBOX_ALLOW_INSECURE"):
        raise RuntimeError(
            "ODIGOS_SANDBOX_ALLOW_INSECURE is set but deployment.mode=hosted; "
            "refusing to start."
        )
    if bwrap_present is None:
        # Gate on the tier the sandbox actually resolved to, not on `which bwrap`.
        # The binary being on PATH says nothing about whether it can construct a
        # namespace here: seccomp, AppArmor userns limits, or a systemd unit that
        # drops AF_NETLINK all make bwrap present but non-functional, and the
        # provider then falls back to ulimit-only with no filesystem isolation.
        from odigos.providers.sandbox import SandboxProvider

        SandboxProvider()  # runs (and caches) tier detection
        present = SandboxProvider._isolation == "bwrap"
    else:
        present = bwrap_present
    if not present:
        raise RuntimeError(
            "deployment.mode=hosted requires working bubblewrap (bwrap) isolation, but "
            "the sandbox probe did not resolve to the bwrap tier; refusing to start. "
            "Run the probe by hand to see the failure."
        )


def startup_security_report(settings) -> None:
    """Log the resolved security posture at boot."""
    from odigos.providers.sandbox import SandboxProvider
    SandboxProvider()  # ensure isolation tier detected
    logger.info(
        "security posture: mode=%s isolation=%s require_isolation=%s sso_auto_provision=%s",
        settings.deployment.mode,
        SandboxProvider._isolation,
        settings.sandbox.require_isolation,
        settings.sso_auto_provision,
    )


def _skill_validation_today():
    return datetime.now(timezone.utc).date()


class Bootstrapper:
    def __init__(self, settings: Settings, config_path: str = "config.yaml"):
        self.settings = settings
        self.config_path = config_path
        self.container = Container(settings=settings, config_path=config_path)

    # ------------------------------------------------------------------
    # Phase 1: Database + early config
    # ------------------------------------------------------------------
    async def init_database(self) -> None:
        """Phase 1: Database connection, migrations, and early config setup."""
        from odigos.db import Database
        from odigos.storage import FILES_DIR, ensure_dirs

        ensure_dirs()

        # Create brain and source directories for memory redesign
        Path("data/sources").mkdir(parents=True, exist_ok=True)
        Path("data/brain/entities").mkdir(parents=True, exist_ok=True)
        Path("data/brain/topics").mkdir(parents=True, exist_ok=True)
        Path("data/brain/conversations").mkdir(parents=True, exist_ok=True)
        Path("data/brain/synthesis").mkdir(parents=True, exist_ok=True)
        Path("data/agent").mkdir(parents=True, exist_ok=True)

        self.container.env_path = ".env"
        self.container.upload_dir = str(FILES_DIR)

        # Shared HTTP client for API tools
        import httpx
        self.container.http_client = httpx.AsyncClient(
            timeout=30,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

        # Auto-generate API key if not configured
        if not self.settings.api_key:
            import secrets
            self.settings.api_key = secrets.token_urlsafe(32)
            await _persist_generated_api_key(
                self.config_path, self.settings.api_key, env_path=self.container.env_path
            )
            logger.warning(
                "No api_key configured -- generated and saved a random key to %s. "
                "View it with: grep ODIGOS_API_KEY %s",
                self.container.env_path, self.container.env_path,
            )

        # Migrate old sections directory
        _agent_dir = Path("data/agent")
        _old_sections = Path("data/prompt_sections")
        if _old_sections.exists() and not _agent_dir.exists():
            shutil.copytree(str(_old_sections), str(_agent_dir))
            logger.info("Migrated data/prompt_sections/ to data/agent/")
        if Path("data/personality.yaml").exists():
            logger.warning(
                "data/personality.yaml is deprecated and ignored "
                "-- identity is now in data/agent/identity.md"
            )

        # Initialize database
        db = Database(self.settings.database.path)
        await db.initialize()
        self.container.db = db
        logger.info("Database initialized at %s", self.settings.database.path)

        # Auto-generate SESSION_SECRET if not set
        if not self.settings.session_secret:
            import secrets as _secrets
            self.settings.session_secret = _secrets.token_urlsafe(48)
            env_path = Path(".env")
            try:
                await aio.append_text(env_path, f"\nSESSION_SECRET={self.settings.session_secret}\n")
                logger.info("Generated SESSION_SECRET and saved to .env")
            except PermissionError:
                logger.warning(
                    "Generated SESSION_SECRET (could not persist to .env -- read-only)"
                )

        # Seed user from data/seed_user.json (for provisioned deploys)
        await _seed_user(db)

        # VAPID keys for web push
        from odigos.core.webpush import get_or_create_vapid_keys
        self.container.vapid_keys = get_or_create_vapid_keys()
        if self.container.vapid_keys:
            logger.info("VAPID keys loaded for web push notifications")

        # Budget tracker — instantiated early so STT/image/music tools can be wired with it.
        # The actual budget settings are read from self.settings.budget here; the same field
        # name is read again at line ~172 below where the redundant init is now removed.
        from odigos.core.budget import BudgetTracker

        self.container.budget_tracker = BudgetTracker(
            db=self.container.db,
            daily_limit=self.settings.budget.daily_limit_usd,
            monthly_limit=self.settings.budget.monthly_limit_usd,
            warn_threshold=self.settings.budget.warn_threshold,
        )
        logger.info("Budget tracker initialized")

        # STT / TTS providers
        from odigos.providers.stt import create_stt_provider
        from odigos.providers.tts import create_tts_provider

        self.container.stt_provider = create_stt_provider(
            voice_config=self.settings.voice,
            groq_api_key=self.settings.service_key("groq"),
            stt_config=self.settings.stt,
            budget_tracker=self.container.budget_tracker,
        )
        logger.info("STT provider: %s", self.container.stt_provider.name)

        self.container.tts_provider = create_tts_provider(
            voice_config=self.settings.voice,
            tts_config=self.settings.tts,
        )
        logger.info("TTS provider: %s", self.container.tts_provider.name)

    # ------------------------------------------------------------------
    # Phase 2: LLM provider
    # ------------------------------------------------------------------
    async def init_llm(self) -> None:
        """Phase 2: LLM provider setup — multi-provider with tiered routing."""
        from odigos.providers.llm import LLMClient

        s = self.settings

        if not s.providers:
            raise RuntimeError(
                "No LLM providers configured. Add a `providers:` block to config.yaml "
                "with at least one OpenAI-compatible endpoint."
            )
        if not s.models:
            raise RuntimeError(
                "No models configured. Add a `models:` block to config.yaml."
            )

        # Routing table: resolve empty tiers to the `fast` default.
        routing = {
            "fast": s.llm.fast,
            "smart": s.llm.smart or s.llm.fast,
            "background": s.llm.background or s.llm.fast,
            "fallback": s.llm.fallback or s.llm.fast,
        }

        self.container.llm_provider = LLMClient(
            providers=s.providers,
            models=s.models,
            routing=routing,
            max_tokens=s.llm.max_tokens,
            temperature=s.llm.temperature,
            request_timeout=s.llm.request_timeout_seconds,
            connect_timeout=s.llm.connect_timeout_seconds,
        )
        logger.info(
            "LLM provider initialized: fast=%s smart=%s background=%s fallback=%s",
            routing["fast"], routing["smart"], routing["background"], routing["fallback"],
        )
        logger.info("Starting Odigos agent: %s", s.agent.name)

        # Budget tracker is already instantiated above; intentionally not redundant.

    # ------------------------------------------------------------------
    # Phase 3: Embeddings
    # ------------------------------------------------------------------
    async def init_embeddings(self) -> None:
        """Phase 3: Embeddings (local or remote)."""
        from odigos.providers.embeddings import EmbeddingProvider

        s = self.settings
        embed_mode = s.embeddings.mode
        if embed_mode == "auto":
            try:
                import httpx
                resp = await asyncio.to_thread(
                    httpx.get,
                    f"{s.embeddings.remote_url}/health",
                    timeout=2.0,
                )
                if resp.status_code == 200:
                    embed_mode = "remote"
                    logger.info(
                        "Detected shared embedding toolkit at %s",
                        s.embeddings.remote_url,
                    )
                else:
                    embed_mode = "local"
            except Exception:
                embed_mode = "local"

        if embed_mode == "remote":
            from odigos.providers.embeddings_remote import RemoteEmbeddingProvider
            self.container.embeddings = RemoteEmbeddingProvider(
                remote_url=s.embeddings.remote_url,
            )
            logger.info("Using remote embedding service at %s", s.embeddings.remote_url)
        else:
            self.container.embeddings = await asyncio.to_thread(EmbeddingProvider)
            logger.info("Using local embedding model")


    # ------------------------------------------------------------------
    # Phase 4: Memory subsystem
    # ------------------------------------------------------------------
    async def init_memory(self) -> None:
        """Phase 4: Memory subsystem (vectors, graph, summarizer)."""
        from odigos.memory.chunking import ChunkingService
        from odigos.memory.corrections import CorrectionsManager
        from odigos.memory.graph import EntityGraph
        from odigos.memory.manager import MemoryManager
        from odigos.memory.resolver import EntityResolver
        from odigos.memory.summarizer import ConversationSummarizer
        from odigos.memory.store import MemoryStore
        from odigos.memory.recall import MemoryRecall
        from odigos.memory.classifier import MemoryClassifier
        from odigos.memory.evolution import MemoryEvolution
        from odigos.core.goal_store import GoalStore
        from odigos.core.trace import Tracer

        db = self.container.db
        embedder = self.container.embeddings
        provider = self.container.llm_provider

        memory_store = MemoryStore(
            db=db,
            llm_client=provider,
            embedder=embedder,
            prompts_dir="data/prompts",
        )
        memory_recall = MemoryRecall(db=db, embedder=embedder)
        memory_classifier = MemoryClassifier(
            llm_client=provider,
            prompts_dir="data/prompts",
        )
        memory_evolution = MemoryEvolution(
            db=db,
            llm_client=provider,
            prompts_dir="data/prompts",
            embedder=embedder,
        )
        self.container.memory_store = memory_store
        self.container.memory_recall = memory_recall
        self.container.memory_classifier = memory_classifier
        self.container.memory_evolution = memory_evolution

        chunking_service = ChunkingService()

        graph = EntityGraph(db=db)
        resolver = EntityResolver(graph=graph, memory_store=memory_store)
        summarizer = ConversationSummarizer(
            db=db, memory_store=memory_store, llm_provider=provider,
        )
        self.container.memory_manager = MemoryManager(
            memory_store=memory_store,
            memory_recall=memory_recall,
            graph=graph,
            resolver=resolver,
            summarizer=summarizer,
            chunking_service=chunking_service,
            cite_sources=self.settings.agent.cite_sources,
            db=db,
        )
        logger.info("Memory system initialized")

        # Corrections manager (stored on container for agent init)
        self._corrections_manager = CorrectionsManager(db=db, memory_store=memory_store)
        logger.info("Corrections manager initialized")

        # Goal store
        self.container.goal_store = GoalStore(db=db)
        logger.info("Goal store initialized")

        # Tracer
        self.container.tracer = Tracer(db=db)
        logger.info("Tracer initialized")

        # Skill registry
        self.container.skill_registry = SkillRegistry()
        self.container.skill_registry.load_all(self.settings.skills.path)
        logger.info("Loaded %d skills", len(self.container.skill_registry.list()))

        # Agent client (mesh networking)
        from odigos.core.agent_client import AgentClient
        mesh_enabled = self.settings.mesh.enabled
        self.container.agent_client = AgentClient(
            peers=self.settings.peers if mesh_enabled else [],
            agent_name=self.settings.agent.name,
            db=db,
        )
        if not mesh_enabled:
            logger.info("Mesh networking disabled (hermit mode)")

        # Card manager
        from odigos.core.cards import CardManager
        self.container.card_manager = CardManager(
            db=db,
            agent_name=self.settings.agent.name,
            host=self.settings.server.host,
            ws_port=self.settings.server.ws_port,
            feed_base_url=f"http://{self.settings.server.host}:{self.settings.server.port}",
        )
        logger.info("Card manager initialized")

        # Store intermediate refs for later phases
        self._chunking_service = chunking_service
        self._summarizer = summarizer

    # ------------------------------------------------------------------
    # Phase 5: Tools (non-critical)
    # ------------------------------------------------------------------
    async def init_tools(self) -> None:
        """Phase 5: Register all tools based on settings/services."""
        try:
            await self._do_init_tools()
        except Exception:
            logger.exception("Tool registration failed (non-critical, continuing)")

    async def _do_init_tools(self) -> None:
        from odigos.tools.registry import ToolRegistry

        db = self.container.db
        settings = self.settings
        provider = self.container.llm_provider
        memory_store = self.container.memory_store
        memory_manager = self.container.memory_manager
        goal_store = self.container.goal_store
        skill_registry = self.container.skill_registry
        card_manager = self.container.card_manager
        agent_client = self.container.agent_client
        mesh_enabled = settings.mesh.enabled

        registry = ToolRegistry()

        # -- Core tools --
        self._register_core_tools(registry, db, settings, memory_store)
        self._register_workspace_tools(registry, db, skill_registry)
        self._register_media_tools(registry, db, settings)
        self._register_comms_tools(registry, settings)
        self._register_productivity_tools(registry, db, goal_store, settings, provider)

        # Subagent manager — unified lifecycle (dispatch, execute, deliver, chain)
        from odigos.core.subagent import SubagentManager
        subagent_manager = SubagentManager(
            db=db,
            llm_provider=provider,
            tool_registry=registry,
            memory_recall=getattr(memory_manager, "memory_recall", None) if memory_manager else None,
            skill_registry=skill_registry,
            tracer=None,
        )
        logger.info("Subagent manager initialized")

        # Subagent orchestration tools
        from odigos.tools.subagent_tools import (
            RunSubagentTool, RunParallelSubagentsTool,
            SubagentStatusTool, CancelSubagentTool,
        )
        registry.register(RunSubagentTool(db=db))
        registry.register(RunParallelSubagentsTool(db=db))
        registry.register(SubagentStatusTool(db=db))
        registry.register(CancelSubagentTool(db=db))
        logger.info("Subagent orchestration tools registered")

        # Peer messaging (skip in hermit mode)
        if mesh_enabled:
            from odigos.tools.peer import MessagePeerTool
            registry.register(MessagePeerTool(peer_client=agent_client))
            if agent_client.list_peer_names():
                logger.info(
                    "Peer messaging tool registered with pre-configured peers: %s",
                    ", ".join(agent_client.list_peer_names()),
                )
            else:
                logger.info("Peer messaging tool registered (discovery via announce)")

        # Card tools
        from odigos.tools.card_tools import GenerateCardTool, ImportCardTool
        registry.register(GenerateCardTool(card_manager=card_manager))
        registry.register(ImportCardTool(card_manager=card_manager))
        logger.info("Card tools registered")

        # Settings management tool
        from odigos.tools.settings_tool import ManageSettingsTool
        registry.register(ManageSettingsTool(settings=settings, config_path=self.config_path))
        logger.info("Settings tool registered")

        # Remember fact tool
        from odigos.tools.remember_fact import RememberFactTool
        _embedder = memory_store._embedder if memory_store else None
        registry.register(RememberFactTool(
            db=db, provider=provider, embedder=_embedder,
        ))
        logger.info("Remember fact tool registered")

        # MCP server bridges
        await self._register_mcp_tools(registry, settings)

        self.container.tool_registry = registry
        self._subagent_manager = subagent_manager

    def _register_core_tools(self, registry, db, settings, memory_store):
        """Search, scrape, code, file, document tools."""
        from odigos.providers.scraper import ScraperProvider
        from odigos.tools.scrape import ScrapeTool

        scraper = ScraperProvider()
        self.container._scraper = scraper
        registry.register(ScrapeTool(scraper=scraper))
        logger.info("Scrape tool initialized")

        from odigos.tools.feed import FeedTool
        registry.register(FeedTool())
        logger.info("Feed tool initialized (feedparser)")

        # Document processing
        from odigos.providers.markitdown import MarkItDownProvider
        from odigos.tools.document import DocTool
        from odigos.memory.ingester import DocumentIngester

        markitdown_provider = MarkItDownProvider()
        self.container.markitdown_provider = markitdown_provider

        doc_ingester = DocumentIngester(
            db=db,
            memory_store=memory_store,
            memory_classifier=self.container.memory_classifier,
            chunking_service=self._chunking_service,
        )
        self.container.doc_ingester = doc_ingester

        self._doc_tool = DocTool(
            markitdown_provider=markitdown_provider,
            ingester=doc_ingester,
            docling_provider=None,
        )
        registry.register(self._doc_tool)
        logger.info("Document tool initialized (MarkItDown default)")

        # Code execution sandbox
        from odigos.providers.sandbox import SandboxProvider
        from odigos.tools.code import CodeTool

        sandbox = SandboxProvider(
            timeout=settings.sandbox.timeout_seconds,
            max_memory_mb=settings.sandbox.max_memory_mb,
            allow_network=settings.sandbox.allow_network,
            require_isolation=(
                settings.sandbox.require_isolation
                or settings.deployment.mode == "hosted"
            ),
        )
        registry.register(CodeTool(sandbox=sandbox, db=db))
        logger.info("Code tool initialized (sandbox)")

        # File tool
        from odigos.tools.file import FileTool
        registry.register(FileTool(allowed_paths=settings.file_access.allowed_paths))
        logger.info("File tool initialized (allowed: %s)", settings.file_access.allowed_paths)

        # Knowledge lookup
        from odigos.tools.knowledge import LookupTool
        registry.register(LookupTool())
        logger.info("Knowledge lookup tool registered")

        # Image processing
        from odigos.tools.image import ImageTool
        registry.register(ImageTool())
        logger.info("Image processing tool registered")

        # Translation
        from odigos.tools.translate import TranslateTool
        registry.register(TranslateTool())
        logger.info("Translation tool registered")

        # Marp slide rendering
        from odigos.tools.marp_tool import MarpTool
        registry.register(MarpTool())
        logger.info("Marp tool registered")

        # Text analysis
        from odigos.tools.text_analysis import TextAnalysisTool
        registry.register(TextAnalysisTool())
        logger.info("Text analysis tool registered")

        # Tool discovery
        from odigos.tools.find_tools import FindToolsTool
        registry.register(FindToolsTool(registry=registry, skill_registry=self.container.skill_registry))
        logger.info("Tool discovery registered (find_tools)")

        # Web platform tool (opencli-rs)
        from odigos.tools.opencli import OPENCLI_BIN
        if OPENCLI_BIN:
            from odigos.tools.opencli import WebPlatformTool
            registry.register(WebPlatformTool())
            logger.info("Web platform tool registered (opencli-rs found at %s)", OPENCLI_BIN)

    def _register_workspace_tools(self, registry, db, skill_registry):
        """Notebooks, kanban, workspace search, skills, artifacts."""
        from odigos.tools.kanban import (
            KanbanListBoardsTool, KanbanGetBoardTool,
            KanbanCreateBoardTool, KanbanCreateCardTool,
            KanbanMoveCardTool, KanbanUpdateCardTool, KanbanDeleteCardTool,
        )
        registry.register(KanbanListBoardsTool(db=db))
        registry.register(KanbanGetBoardTool(db=db))
        registry.register(KanbanCreateBoardTool(db=db))
        registry.register(KanbanCreateCardTool(db=db))
        registry.register(KanbanMoveCardTool(db=db))
        registry.register(KanbanUpdateCardTool(db=db))
        registry.register(KanbanDeleteCardTool(db=db))
        logger.info("Kanban tools initialized")

        from odigos.tools.artifact import CreateArtifactTool, DeleteArtifactTool
        registry.register(CreateArtifactTool(db=db))
        registry.register(DeleteArtifactTool(db=db))
        logger.info("Artifact tool initialized")

        from odigos.tools.workspace_search import WorkspaceSearchTool
        registry.register(WorkspaceSearchTool(db=db))
        logger.info("Workspace search tool registered")

        from odigos.tools.notebook import ManageNotebookTool
        registry.register(ManageNotebookTool(db=db))
        logger.info("Notebook tool registered")

        # Skill tools
        try:
            Path("skills/code").mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("Could not create skills/code/ (read-only filesystem)")

        code_skill_count = skill_registry.register_code_skills(registry)
        if code_skill_count:
            logger.info("Registered %d code skill tools", code_skill_count)

        from odigos.tools.skill_tool import ActivateSkillTool
        from odigos.tools.skill_manage import CreateSkillTool, UpdateSkillTool

        # Build skill verifier for use in skill tools (lazy — llm_provider available at this point)
        try:
            from odigos.skills.verifier import SkillVerifier as _SkillVerifier
            _skill_verifier = _SkillVerifier(
                llm_client=self.container.llm_provider,
                prompts_dir="data/prompts",
                skill_registry=skill_registry,
                db=db,
            )
        except Exception:
            logger.warning("SkillVerifier unavailable for skill tools", exc_info=True)
            _skill_verifier = None

        registry.register(ActivateSkillTool(skill_registry=skill_registry))
        registry.register(CreateSkillTool(
            skill_registry=skill_registry, tool_registry=registry,
            verifier=_skill_verifier,
        ))
        registry.register(UpdateSkillTool(
            skill_registry=skill_registry, tool_registry=registry,
            verifier=_skill_verifier,
        ))
        logger.info("Skill tools registered (activate, create, update)")

        # Spreadsheet
        from odigos.tools.spreadsheet import DataTableTool
        registry.register(DataTableTool(db=db))
        logger.info("Data table tool registered")

    def _register_media_tools(self, registry, db, settings):
        """Image gen, music gen, audio, QR, calendar events."""
        # Audio processing (FFmpeg)
        if shutil.which("ffmpeg"):
            from odigos.tools.audio_process import ProcessAudioTool
            registry.register(ProcessAudioTool(db=db))
            logger.info("Audio processing tool registered (FFmpeg found)")
        else:
            logger.info("Audio processing tool skipped (FFmpeg not found)")

        # QR code
        from odigos.tools.qr import QRCodeTool
        registry.register(QRCodeTool(db=db))
        logger.info("QR code tool registered")

        # Calendar event (.ics)
        from odigos.tools.ics import CalendarEventTool
        registry.register(CalendarEventTool(db=db))
        logger.info("Calendar event tool registered")

        # Kie.ai-powered tools (image gen, music gen)
        kie_api_key = settings.service_key("kie_ai")
        if kie_api_key:
            from odigos.tools.image_gen import GenerateImageTool
            registry.register(GenerateImageTool(
                http=self.container.http_client,
                api_key=kie_api_key,
                default_ratio=settings.image_generation.default_aspect_ratio,
                nsfw_filter=settings.image_generation.nsfw_filter,
                max_poll_seconds=settings.image_generation.max_poll_seconds,
                db=db,
                budget_tracker=self.container.budget_tracker,
                callback_secret=settings.session_secret,
            ))
            logger.info("Image generation tool registered (Z-Image)")

            from odigos.tools.music_gen import GenerateMusicTool
            registry.register(GenerateMusicTool(
                http=self.container.http_client,
                api_key=kie_api_key,
                model=settings.music_generation.model,
                max_poll_seconds=settings.music_generation.max_poll_seconds,
                db=db,
                budget_tracker=self.container.budget_tracker,
                callback_secret=settings.session_secret,
            ))
            logger.info(
                "Music generation tool registered (Suno %s)",
                settings.music_generation.model,
            )

        # Feed publish
        if settings.feed.enabled:
            from odigos.tools.feed_publish import PublishToFeedTool
            registry.register(PublishToFeedTool(
                db=db,
                feed_base_url=f"http://{settings.server.host}:{settings.server.port}",
            ))
            logger.info("Feed publish tool registered")

    def _register_comms_tools(self, registry, settings):
        """Email, calendar, notifications, feed monitoring."""
        # Calendar tools (auto-enabled when CalDAV URL is configured)
        if settings.calendar.url:
            from odigos.tools.calendar import (
                CheckCalendarTool, CreateCalendarEventTool, FindFreeTimeTool,
            )
            registry.register(CheckCalendarTool(calendar_config=settings.calendar))
            registry.register(CreateCalendarEventTool(calendar_config=settings.calendar))
            registry.register(FindFreeTimeTool(calendar_config=settings.calendar))
            logger.info("Calendar tools initialized (%s)", settings.calendar.url)

        # Feed monitoring
        from odigos.tools.feed_monitor import WatchFeedTool, ListFeedsTool, CheckFeedsTool
        registry.register(WatchFeedTool(db=self.container.db))
        registry.register(ListFeedsTool(db=self.container.db))
        registry.register(CheckFeedsTool(db=self.container.db))
        logger.info("Feed monitoring tools initialized")

        # Email tools (auto-enabled when IMAP host is configured)
        if settings.email.imap_host:
            from odigos.tools.email import (
                CheckEmailTool, SearchEmailTool, ReadEmailTool, SendEmailTool,
            )
            registry.register(CheckEmailTool(email_config=settings.email))
            registry.register(SearchEmailTool(email_config=settings.email))
            registry.register(ReadEmailTool(email_config=settings.email))
            registry.register(SendEmailTool(email_config=settings.email))
            logger.info("Email tools initialized (%s)", settings.email.address)

    def _register_productivity_tools(self, registry, db, goal_store, settings, provider):
        """Goals, todos, plans, suggest, quiz."""
        from odigos.tools.goals import CreateReminderTool, CreateTodoTool, CreateGoalTool
        registry.register(CreateReminderTool(goal_store=goal_store))
        registry.register(CreateTodoTool(goal_store=goal_store))
        registry.register(CreateGoalTool(goal_store=goal_store))
        logger.info("Goal tools initialized")

        from odigos.tools.suggest import SuggestActionsTool
        registry.register(SuggestActionsTool(goal_store=goal_store))
        logger.info("Suggest actions tool initialized")

        from odigos.tools.quiz import CreateQuizTool, GradeResponseTool
        registry.register(CreateQuizTool(db=db))
        registry.register(GradeResponseTool(db=db))
        logger.info("Quiz tools initialized")

        from odigos.tools.decompose import DecomposeQueryTool
        registry.register(DecomposeQueryTool(provider=provider))
        from odigos.tools.plan import CheckPlanTool, UpdatePlanTool
        registry.register(CheckPlanTool(db=db))
        registry.register(UpdatePlanTool(db=db))
        logger.info("Decompose, check_plan, update_plan tools registered")

    async def _register_mcp_tools(self, registry, settings):
        """MCP server bridges."""
        if not settings.mcp.servers:
            return

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
                        server=server, server_name=server_name, mcp_tool=mcp_tool,
                    )
                    if registry.get(bridge.name):
                        logger.warning(
                            "MCP tool name collision: '%s' overwrites existing tool",
                            bridge.name,
                        )
                    registry.register(bridge)
                    logger.info("Registered MCP tool: %s", bridge.name)
                self.container._mcp_servers.append(server)
                logger.info(
                    "MCP server '%s' connected (%d tools)",
                    server_name, len(mcp_tools),
                )
            except Exception:
                logger.exception("Failed to connect MCP server: %s", server_name)

    # ------------------------------------------------------------------
    # Phase 6: Plugins (non-critical)
    # ------------------------------------------------------------------
    async def init_plugins(self) -> None:
        """Phase 6: Load plugins. Non-critical -- catches exceptions, logs warnings."""
        try:
            await self._do_init_plugins()
        except Exception:
            logger.exception("Plugin initialization failed (non-critical, continuing)")

    def validate_skill_tools(self) -> None:
        """Validate every skill's declared tools against the tool catalog
        (spec 2026-05-29). A tool is OK if it's live OR in the catalog
        (exists but inactive this run). A tool in neither is a hard problem:
        WARN before the cutover, RAISE on/after it. Env ODIGOS_TOOL_VALIDATION
        overrides: 'warn' = never raise, 'off' = skip entirely."""
        import os
        from datetime import date

        mode = os.environ.get("ODIGOS_TOOL_VALIDATION", "auto").lower()
        if mode == "off":
            return

        skill_registry = getattr(self.container, "skill_registry", None)
        registry = getattr(self.container, "tool_registry", None)
        if skill_registry is None or registry is None:
            return

        try:
            from odigos.tools.catalog import build_catalog
            catalog = build_catalog()
        except Exception:
            logger.warning("Skill validation skipped: tool catalog unavailable", exc_info=True)
            return
        if not catalog:
            logger.warning("Skill validation skipped: tool catalog empty")
            return

        live = {t.name for t in registry.list()}
        _CUTOVER = date(2026, 8, 1)
        hard: list[str] = []
        inactive: list[str] = []
        for skill in skill_registry.list():
            for tool_name in skill.tools:
                if tool_name in live:
                    continue
                if tool_name in catalog:
                    gate = catalog[tool_name]
                    # For a gated tool, the gate explains why it's inactive. For an
                    # ALWAYS-gated tool that still isn't live, the gate is NOT the
                    # reason (it registered conditionally elsewhere or failed to
                    # register this run) — don't print the contradictory
                    # "inactive: always available".
                    reason = gate.describe() if gate.kind != "always" else "not active this run"
                    inactive.append(
                        f"skill '{skill.name}' uses '{tool_name}' ({reason})"
                    )
                else:
                    hard.append(
                        f"skill '{skill.name}' references unknown tool '{tool_name}'"
                    )

        if inactive:
            logger.info("Skill tool validation (inactive): %s", "; ".join(inactive))
        if hard:
            msg = "Skill tool validation failed: " + "; ".join(hard)
            if mode != "warn" and _skill_validation_today() >= _CUTOVER:
                raise RuntimeError(msg)
            logger.warning("%s (hard failure on/after %s unless ODIGOS_TOOL_VALIDATION=warn)",
                           msg, _CUTOVER.isoformat())

    async def _do_init_plugins(self) -> None:
        from odigos.channels.base import ChannelRegistry
        from odigos.core.plugin_context import PluginContext
        from odigos.core.plugins import PluginManager

        channel_registry = ChannelRegistry()
        self.container.channel_registry = channel_registry

        plugin_context = PluginContext(
            tool_registry=self.container.tool_registry,
            channel_registry=channel_registry,
            tracer=self.container.tracer,
            config={"settings": self.settings},
        )

        plugin_manager = PluginManager(plugin_context=plugin_context)
        plugin_manager.load_all("plugins")
        plugin_manager.load_all("data/plugins")
        logger.info("Loaded %d plugins", len(plugin_manager.loaded_plugins))

        # Check if docling plugin registered a provider
        docling_from_plugin = plugin_context.get_provider("docling")
        if docling_from_plugin and hasattr(self, "_doc_tool"):
            self._doc_tool.docling = docling_from_plugin
            logger.info("Docling provider loaded from plugin")

        self.container.plugin_manager = plugin_manager
        self.container.plugin_context = plugin_context

    # ------------------------------------------------------------------
    # Phase 6b: Agent + services (depends on tools + plugins)
    # ------------------------------------------------------------------
    async def init_agent(self) -> None:
        """Initialize Agent, AgentService, evolution engine, and related services."""
        from odigos.core.agent import Agent
        from odigos.core.agent_service import AgentService
        from odigos.core.approval import ApprovalGate
        from odigos.core.classifier import QueryClassifier

        s = self.settings
        db = self.container.db
        provider = self.container.llm_provider

        # Approval gate
        approval_gate = None
        if s.approval.enabled and s.approval.tools:
            approval_gate = ApprovalGate(
                db=db,
                tools_requiring_approval=s.approval.tools,
                channel_registry=self.container.channel_registry,
                timeout=s.approval.timeout,
            )
            logger.info(
                "Approval gate enabled for %d tools: %s",
                len(s.approval.tools), ", ".join(s.approval.tools),
            )

        # Query classifier
        classifier = QueryClassifier(
            provider=provider, db=db,
            tool_registry=self.container.tool_registry,
            skill_registry=self.container.skill_registry,
        )
        logger.info("Query classifier initialized")

        # Agent
        agent = Agent(
            db=db,
            provider=provider,
            agent_name=s.agent.name,
            memory_manager=self.container.memory_manager,
            tool_registry=self.container.tool_registry,
            skill_registry=self.container.skill_registry,
            cost_fetcher=None,
            budget_tracker=self.container.budget_tracker,
            max_tool_turns=s.agent.max_tool_turns,
            run_timeout=s.agent.run_timeout_seconds,
            summarizer=self._summarizer,
            corrections_manager=self._corrections_manager,
            tracer=self.container.tracer,
            approval_gate=approval_gate,
            classifier=classifier,
            auto_route=s.llm.auto_route,
            settings=s,
        )
        self.container.agent = agent

        # AgentService facade
        agent_service = AgentService(
            agent=agent,
            goal_store=self.container.goal_store,
            budget_tracker=self.container.budget_tracker,
            approval_gate=approval_gate,
        )
        agent_service.doc_ingester = self.container.doc_ingester
        agent_service.markitdown_provider = self.container.markitdown_provider
        agent_service.upload_dir = self.container.upload_dir
        self.container.plugin_context.set_service(agent_service)
        self.container.agent_service = agent_service

        # Wire audio providers from plugins
        stt_from_plugin = self.container.plugin_context.get_provider("stt")
        tts_from_plugin = self.container.plugin_context.get_provider("tts")
        if stt_from_plugin:
            agent_service.stt_provider = stt_from_plugin
        if tts_from_plugin:
            agent_service.tts_provider = tts_from_plugin

        # Phase 2 channel plugins (need AgentService)
        self.container.plugin_manager.load_channels("plugins")
        logger.info("Channel plugins loaded")

        # WebChannel for dashboard WebSocket
        from odigos.channels.web import WebChannel
        web_channel = WebChannel()
        self.container.channel_registry.register("web", web_channel)
        web_channel.setup_tracer_forwarding(self.container.tracer)
        self.container.web_channel = web_channel

        # MessageBus — single interface for all message publishing
        from odigos.core.message_bus import MessageBus
        self.container.message_bus = MessageBus(
            db=db,
            channel_registry=self.container.channel_registry,
        )
        logger.info("MessageBus initialized")
        self.container.agent.message_bus = self.container.message_bus
        self.container.agent.reflector.message_bus = self.container.message_bus
        self.container.agent.reflector._extraction_provider = self.container.llm_provider
        # Reflector extracts entities using the background tier — cheapest model.
        self.container.agent.reflector._extraction_intelligence = "background"

        # Wire subagent manager tracer
        if hasattr(self, "_subagent_manager"):
            self._subagent_manager.tracer = self.container.tracer

        # Evolution engine
        from odigos.core.checkpoint import CheckpointManager
        from odigos.core.evaluator import Evaluator
        from odigos.core.evolution import EvolutionEngine

        checkpoint_manager = CheckpointManager(
            db=db, sections_dir="data/agent",
            skills_dir=s.skills.path,
        )
        evaluator = Evaluator(
            db=db, provider=provider,
            qualified_evaluator_min_score=s.evolution.qualified_evaluator_min_score,
            skill_registry=self.container.skill_registry,
        )
        evolution_engine = EvolutionEngine(
            db=db, checkpoint_manager=checkpoint_manager,
            evaluator=evaluator, provider=provider,
            evolution_config=s.evolution,
        )
        agent.context_assembler.checkpoint_manager = checkpoint_manager
        agent.executor.evaluator = evaluator
        self.container.checkpoint_manager = checkpoint_manager
        self.container.evolution_engine = evolution_engine
        logger.info("Evolution engine initialized")

        # Strategist
        from odigos.core.strategist import Strategist
        tool_names = [
            t.name for t in self.container.tool_registry.list()
        ] if hasattr(self.container.tool_registry, "list") else []

        self._strategist = Strategist(
            db=db, provider=provider,
            evolution_engine=evolution_engine,
            agent_description=s.agent.description,
            agent_tools=tool_names,
            evolution_config=s.evolution,
            skill_registry=self.container.skill_registry,
        )
        logger.info("Strategist initialized")

        # Template index
        from odigos.core.template_index import AgentTemplateIndex
        self.container.template_index = AgentTemplateIndex(
            db=db, repo_url=s.templates.repo_url,
            cache_ttl_days=s.templates.cache_ttl_days,
        )
        logger.info("Agent template index initialized")

        # Spawner
        from odigos.core.spawner import Spawner
        self.container.spawner = Spawner(
            db=db, provider=provider,
            parent_name=s.agent.name,
            llm_config=s.llm,
            server_config=s.server,
            template_index=self.container.template_index,
        )
        logger.info("Spawner initialized")

        # Cron manager
        from odigos.core.cron import CronManager
        self.container.cron_manager = CronManager(db=db)
        logger.info("Cron manager initialized")

        # Scheduler
        from odigos.core.scheduler import Scheduler
        self.container.scheduler = Scheduler(db=db)
        logger.info("Unified scheduler initialized")

        # Wire scheduler into CreateReminderTool
        reminder_tool = self.container.tool_registry.get("create_reminder")
        if reminder_tool:
            reminder_tool.scheduler = self.container.scheduler

        # Notifier
        from odigos.core.notifier import Notifier
        self.container.notifier = Notifier(
            channel_registry=self.container.channel_registry,
            db=db, vapid_keys=self.container.vapid_keys,
        )
        logger.info("Notifier initialized")

        # Register notification tool
        from odigos.tools.notify import NotifyTool
        self.container.tool_registry.register(
            NotifyTool(notifier=self.container.notifier),
        )
        logger.info("Notification tool registered")

    # ------------------------------------------------------------------
    # Phase 7: Background loops (non-critical)
    # ------------------------------------------------------------------
    async def init_background(self) -> None:
        """Phase 7: Heartbeat, cron, background loops. Non-critical."""
        try:
            await self._do_init_background()
        except Exception:
            logger.exception("Background initialization failed (non-critical, continuing)")

    async def _do_init_background(self) -> None:
        from odigos.core.heartbeat import Heartbeat

        s = self.settings
        db = self.container.db
        mesh_enabled = s.mesh.enabled

        heartbeat = Heartbeat(
            db=db,
            agent=self.container.agent,
            channel_registry=self.container.channel_registry,
            goal_store=self.container.goal_store,
            provider=self.container.llm_provider,
            interval=s.heartbeat.interval_seconds,
            max_todos_per_tick=s.heartbeat.max_todos_per_tick,
            idle_think_interval=s.heartbeat.idle_think_interval,
            tracer=self.container.tracer,
            subagent_manager=self._subagent_manager,
            evolution_engine=self.container.evolution_engine,
            strategist=self._strategist,
            agent_client=self.container.agent_client if mesh_enabled else None,
            agent_role=s.agent.role,
            agent_description=s.agent.description,
            announce_interval=s.heartbeat.announce_interval_seconds,
            cron_manager=self.container.cron_manager,
            notifier=self.container.notifier,
            scheduler=self.container.scheduler,
            ws_port=s.server.ws_port,
            settings=s,
            budget_tracker=self.container.budget_tracker,
            tool_registry=self.container.tool_registry,
            message_bus=self.container.message_bus,
        )
        heartbeat._proactive_config = self.settings.proactive
        self.container.agent.heartbeat = heartbeat
        self.container.heartbeat = heartbeat

        # Wire consolidator and skill verifier into heartbeat
        try:
            from odigos.core.consolidation import PromptConsolidator
            from odigos.skills.verifier import SkillVerifier

            consolidator = PromptConsolidator(
                db=db,
                llm_client=self.container.llm_provider,
                prompts_dir="data/prompts",
                sections_dir="data/agent",
            )
            heartbeat.consolidator = consolidator
            logger.info("PromptConsolidator attached to heartbeat")

            skill_verifier = SkillVerifier(
                llm_client=self.container.llm_provider,
                prompts_dir="data/prompts",
                skill_registry=self.container.skill_registry,
                db=db,
            )
            heartbeat.skill_verifier = skill_verifier
            heartbeat.skill_registry = self.container.skill_registry
            logger.info("SkillVerifier attached to heartbeat")
        except Exception:
            logger.warning("Could not attach consolidator/skill_verifier to heartbeat", exc_info=True)

        # Wire memory evolution into heartbeat
        heartbeat.memory_evolution = self.container.memory_evolution
        logger.info("MemoryEvolution attached to heartbeat")

        # Wire notebook review phase
        heartbeat.notes_review_enabled = True

        # Wire email config
        if s.email.imap_host:
            heartbeat._email_config = s.email
            logger.info(
                "Email heartbeat enabled (check every %d ticks)",
                s.email.check_interval_ticks,
            )

        # Start channels
        for ch in self.container.channel_registry.all():
            await ch.start()
            logger.info("Channel '%s' started", ch.channel_name)

        # Start heartbeat
        await heartbeat.start()
        logger.info("Heartbeat started (interval=%ds)", s.heartbeat.interval_seconds)

        # WebSocket connector for mesh peers
        if mesh_enabled and s.peers:
            from odigos.core.ws_connector import WSConnector
            ws_connector = WSConnector(
                agent_client=self.container.agent_client,
                agent_name=s.agent.name,
                peers=s.peers,
            )
            await ws_connector.start()
            self.container._ws_connector = ws_connector
            logger.info("WebSocket connector started for %d peer(s)", len(s.peers))

        # Warn if binding to all interfaces without TLS
        if s.server.host == "0.0.0.0":
            logger.warning(
                "Server bound to 0.0.0.0 (all interfaces) without TLS. "
                "Use a reverse proxy with TLS in production, or bind to "
                "127.0.0.1 for local-only access."
            )

        # Validate routing rules
        from odigos.core.routing import load_routing_rules
        _routing_warnings = self.container.tool_registry.validate_routing_rules(
            load_routing_rules(),
        )
        if _routing_warnings:
            logger.warning(
                "Routing rule warnings: %d issues found", len(_routing_warnings),
            )

        # Heavy file processing pool
        self.container.heavy_pool = ThreadPoolExecutor(max_workers=4)
        logger.info("Heavy file processing pool started (4 workers)")

    # ------------------------------------------------------------------
    # Main bootstrap
    # ------------------------------------------------------------------
    async def bootstrap(self) -> Container:
        """Run all phases in order. Returns populated Container."""
        # Critical phases (1-4): fail fast
        await self.init_database()
        await self.init_llm()
        await self.init_embeddings()
        await self.init_memory()

        # Non-critical phases (5-7): catch + log + continue
        await self.init_tools()
        await self.init_plugins()
        # Validate skills AFTER plugins so plugin-registered tools are present.
        try:
            self.validate_skill_tools()
        except RuntimeError:
            raise
        except Exception:
            logger.exception("Skill tool validation crashed (non-critical, continuing)")
        _enforce_hosted_security(self.settings)
        startup_security_report(self.settings)
        await self.init_agent()
        await self.init_background()

        logger.info("Odigos is ready.")
        return self.container


# ---- Helpers ----

async def _persist_generated_api_key(
    config_path: str, api_key: str, env_path: str = ".env"
) -> None:
    """Persist the generated api_key to .env (gitignored) so it survives
    restarts without landing in the operator-edited config.yaml.

    The env var name matches the alias the Settings layer reads
    (ODIGOS_API_KEY); see Settings.api_key in odigos/config.py.
    """
    try:
        await aio.append_text(Path(env_path), f"\nODIGOS_API_KEY={api_key}\n")
    except Exception:
        logger.warning("Could not persist api_key to %s", env_path)


async def _seed_user(db) -> None:
    """Seed user from data/seed_user.json (for provisioned deploys).

    Expected JSON shape:
        {
          "username": "jacob",
          "email": "jacob@example.com",
          "password": "TempPass123",
          "display_name": "Jacob",          # optional
          "must_change_password": true       # optional, default true
        }
    """
    import json as _json

    _seed_path = Path("data/seed_user.json")
    if not _seed_path.exists():
        return

    try:
        _seed = _json.loads(await aio.read_text(_seed_path))
        _row = await db.fetch_one("SELECT COUNT(*) as count FROM users")
        if _row and _row["count"] == 0:
            import uuid as _uuid
            from odigos.api.auth import _hash_password

            _user_id = _uuid.uuid4().hex
            _now = datetime.now(timezone.utc).isoformat()
            _must_change = 1 if _seed.get("must_change_password", True) else 0
            _email = (_seed.get("email") or "").strip()
            await db.execute(
                "INSERT INTO users (id, username, email, password_hash, display_name, "
                "must_change_password, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    _user_id,
                    _seed["username"],
                    _email,
                    _hash_password(_seed["password"]),
                    _seed.get("display_name", ""),
                    _must_change,
                    _now,
                ),
            )
            logger.info(
                "Seed user '%s' (%s) created from data/seed_user.json",
                _seed["username"], _email or "no email",
            )
            _seed_path.unlink()
            logger.info("Consumed and deleted data/seed_user.json")
        else:
            _seed_path.unlink()
            logger.info("Seed user skipped (users exist), deleted seed_user.json")
    except Exception:
        logger.warning("Failed to process seed_user.json (will retry on next startup)")


# Late import to avoid circular reference at module level
from odigos.skills.registry import SkillRegistry  # noqa: E402
