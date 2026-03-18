from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from odigos.channels.base import UniversalMessage
from odigos.core.context import ContextAssembler
from odigos.core.executor import Executor
from odigos.core.reflector import Reflector
from odigos.db import Database
from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from odigos.core.approval import ApprovalGate
    from odigos.core.budget import BudgetTracker
    from odigos.core.classifier import QueryClassifier
    from odigos.core.trace import Tracer
    from odigos.memory.corrections import CorrectionsManager
    from odigos.memory.manager import MemoryManager
    from odigos.memory.summarizer import ConversationSummarizer
    from odigos.skills.registry import SkillRegistry
    from odigos.tools.registry import ToolRegistry


class Agent:
    """Main agent: receives messages, runs ReAct agentic loop."""

    def __init__(
        self,
        db: Database,
        provider: LLMProvider,
        agent_name: str,
        history_limit: int = 20,
        memory_manager: MemoryManager | None = None,
        tool_registry: ToolRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        cost_fetcher: Callable | None = None,
        budget_tracker: BudgetTracker | None = None,
        max_tool_turns: int = 25,
        run_timeout: int = 300,
        summarizer: ConversationSummarizer | None = None,
        corrections_manager: CorrectionsManager | None = None,
        tracer: Tracer | None = None,
        approval_gate: ApprovalGate | None = None,
        classifier: QueryClassifier | None = None,
        reasoning_model: str = "",
    ) -> None:
        self.db = db
        self.budget_tracker = budget_tracker
        self.tracer = tracer
        self.classifier = classifier
        self.heartbeat = None  # set after construction to avoid circular init
        self._max_tool_turns = max_tool_turns
        self._run_timeout = run_timeout
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._session_lock_times: dict[str, float] = {}
        self._lock_ttl = 86400  # evict locks idle >24h
        self.context_assembler = ContextAssembler(
            db,
            agent_name,
            history_limit,
            memory_manager=memory_manager,
            summarizer=summarizer,
            skill_registry=skill_registry,
            corrections_manager=corrections_manager,
        )
        self.executor = Executor(
            provider,
            self.context_assembler,
            tool_registry=tool_registry,
            skill_registry=skill_registry,
            db=db,
            max_tool_turns=max_tool_turns,
            budget_tracker=budget_tracker,
            tracer=tracer,
            approval_gate=approval_gate,
            reasoning_model=reasoning_model,
        )
        self.reflector = Reflector(
            db,
            memory_manager=memory_manager,
            cost_fetcher=cost_fetcher,
            corrections_manager=corrections_manager,
            tracer=tracer,
        )

    async def handle_message(
        self,
        message: UniversalMessage,
        *,
        status_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Process an incoming message through the ReAct loop."""
        conversation_id = await self._get_or_create_conversation(message)

        # Extract context_metadata from message metadata (set by ws.py)
        context_metadata = message.metadata.get("context") if message.metadata else None

        # Session serialization -- one turn at a time per session
        lock = self._get_session_lock(conversation_id)
        async with lock:
            return await self._run(
                conversation_id, message,
                status_callback=status_callback,
                context_metadata=context_metadata,
            )

    async def _run(
        self,
        conversation_id: str,
        message: UniversalMessage,
        *,
        status_callback: Callable[[str], Awaitable[None]] | None = None,
        context_metadata: dict | None = None,
    ) -> str:
        """Execute the agent loop with timeout."""
        await self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (message.id, conversation_id, "user", message.content),
        )

        if self.tracer:
            await self.tracer.emit("step_start", conversation_id, {"message_preview": message.content[:200]})

        # Budget check
        if self.budget_tracker:
            status = await self.budget_tracker.check_budget()
            if not status.within_budget:
                logger.warning("Budget exceeded, returning low-cost response")
                if self.tracer:
                    await self.tracer.emit("budget_exceeded", conversation_id, {})
                return (
                    "I've hit my spending limit for this period. "
                    "I can still help with simple tasks that don't need an LLM call. "
                    "Use /status to see current budget usage."
                )

        # Classify the query
        analysis = None
        if self.classifier:
            try:
                analysis = await self.classifier.classify(message.content)
                logger.info("Query classified as '%s' (tier %d, confidence %.2f)",
                            analysis.classification, analysis.tier, analysis.confidence)
            except Exception:
                logger.warning("Query classification failed, proceeding without")

        if status_callback:
            await status_callback("Thinking...")

        try:
            async with asyncio.timeout(self._run_timeout):
                result = await self.executor.execute(
                    conversation_id, message.content, query_analysis=analysis,
                    status_callback=status_callback,
                    context_metadata=context_metadata,
                )
        except asyncio.TimeoutError:
            logger.warning("Run timed out after %ds for %s", self._run_timeout, conversation_id)
            if self.tracer:
                await self.tracer.emit("timeout", conversation_id, {"timeout_seconds": self._run_timeout})
            return "I ran out of time working on that. Try breaking it into smaller pieces."
        except Exception as e:
            logger.exception("Agent run failed for %s", conversation_id)
            if self.tracer:
                await self.tracer.emit("error", conversation_id, {"error": str(e)[:500]})
            return "Something went wrong while processing your message. Please try again."

        clean_content = await self.reflector.reflect(
            conversation_id,
            result.response,
            user_message=message.content,
        )

        if self.tracer:
            await self.tracer.emit("response", conversation_id, {
                "model": result.response.model,
                "tokens_in": result.response.tokens_in,
                "tokens_out": result.response.tokens_out,
                "cost_usd": result.response.cost_usd,
            })

        await self.db.execute(
            "UPDATE conversations SET last_message_at = datetime('now'), "
            "message_count = message_count + 2 WHERE id = ?",
            (conversation_id,),
        )

        return clean_content

    def _get_session_lock(self, conversation_id: str) -> asyncio.Lock:
        """Get or create a session lock, evicting stale entries."""
        now = time.monotonic()
        # Evict locks idle for longer than TTL (only unlocked ones)
        stale = [
            k for k, t in self._session_lock_times.items()
            if now - t > self._lock_ttl and not self._session_locks[k].locked()
        ]
        for k in stale:
            del self._session_locks[k]
            del self._session_lock_times[k]
        if conversation_id not in self._session_locks:
            self._session_locks[conversation_id] = asyncio.Lock()
        self._session_lock_times[conversation_id] = now
        return self._session_locks[conversation_id]

    async def _get_or_create_conversation(self, message: UniversalMessage) -> str:
        """Get existing conversation for this chat, or create a new one."""
        chat_id = message.metadata.get("chat_id", message.sender)
        lookup_id = f"{message.channel}:{chat_id}"

        existing = await self.db.fetch_one(
            "SELECT id FROM conversations WHERE id = ?", (lookup_id,)
        )
        if existing:
            return existing["id"]

        await self.db.execute(
            "INSERT OR IGNORE INTO conversations (id, channel) VALUES (?, ?)",
            (lookup_id, message.channel),
        )
        return lookup_id
