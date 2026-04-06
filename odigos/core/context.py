from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import tiktoken

from odigos.core.content_filter import ContentFilter
from odigos.core.profiler import UserProfile, format_profile_for_context
from odigos.core.prompt_loader import load_prompt
from odigos.core.queries import get_recent_tool_errors, get_user_facts, get_user_profile
from odigos.core.relevance import prune_sections
from odigos.core.routing import load_routing_rules
from odigos.db import Database
from odigos.personality.section_registry import SectionRegistry
from odigos.personality.prompt_builder import build_system_prompt

_context_filter = ContentFilter()

# Core tools included for EVERY classification — the agent should always
# be able to search, create, and discover more tools.
_CORE_TOOLS = ["search_web", "search_documents", "generate_image", "generate_music", "run_code"]

# Additional tools per classification — merged with core set
_EXTRA_TOOLS = {
    "simple": [],
    "standard": [],
    "document_query": ["read_file"],
    "complex": ["create_file", "decompose_query"],
    "planning": ["decompose_query"],
    "code": ["create_file"],
    "creative": [],
    "email": ["check_email", "send_email", "search_email"],
}

# Combined fallback: core + extras (used when query_log has no history)
_FALLBACK_TOOLS = {
    k: _CORE_TOOLS + v for k, v in _EXTRA_TOOLS.items()
}

_CLASS_CATEGORIES = {
    "standard": ["search"],
    "document_query": ["search", "analysis"],
    "complex": ["search", "code"],
    "creative": ["create", "media"],
    "email": ["communication"],
    "code": ["code"],
}


async def _get_likely_tools(db, classification: str) -> list[str]:
    """Get tools historically used for this classification type from query_log."""
    rows = await db.fetch_all(
        "SELECT tools_used, COUNT(*) as cnt FROM query_log "
        "WHERE classification = ? AND tools_used IS NOT NULL AND tools_used != '' "
        "GROUP BY tools_used ORDER BY cnt DESC LIMIT 5",
        (classification,),
    )
    tools: set[str] = set()
    for row in rows:
        raw = row["tools_used"]
        if raw.startswith("["):
            tools.update(json.loads(raw))
        else:
            tools.update(t.strip() for t in raw.split(",") if t.strip())
    return list(tools)

if TYPE_CHECKING:
    from odigos.core.checkpoint import CheckpointManager
    from odigos.core.classifier import QueryAnalysis
    from odigos.memory.corrections import CorrectionsManager
    from odigos.memory.manager import MemoryManager
    from odigos.memory.summarizer import ConversationSummarizer
    from odigos.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

_tokenizer = tiktoken.get_encoding("cl100k_base")

# 60-second TTL cache for memory_index counts (avoid hitting DB every request)
_memory_index_cache: tuple[float, str] | None = None
_MEMORY_INDEX_TTL = 60.0


def estimate_tokens(text: str) -> int:
    """Count tokens using tiktoken (cl100k_base, used by Claude/GPT-4)."""
    return len(_tokenizer.encode(text, disallowed_special=()))


class ContextAssembler:
    """Builds the messages list for an LLM call from conversation history."""

    def __init__(
        self,
        db: Database,
        agent_name: str,
        history_limit: int = 20,
        memory_manager: MemoryManager | None = None,
        sections_dir: str = "data/agent",
        summarizer: ConversationSummarizer | None = None,
        skill_registry: SkillRegistry | None = None,
        corrections_manager: CorrectionsManager | None = None,
        checkpoint_manager: CheckpointManager | None = None,
        settings=None,
    ) -> None:
        self.db = db
        self.agent_name = agent_name
        self.history_limit = history_limit
        self.memory_manager = memory_manager
        self.summarizer = summarizer
        self.skill_registry = skill_registry
        self.corrections_manager = corrections_manager
        self.checkpoint_manager = checkpoint_manager
        self.settings = settings
        self.fallback_registry = SectionRegistry(sections_dir)

    async def build(
        self,
        conversation_id: str,
        message_content: str,
        max_tokens: int = 0,
        *,
        query_analysis: QueryAnalysis | None = None,
        context_metadata: dict | None = None,
    ) -> list[dict]:
        """Assemble the full messages list: system + history + current."""
        messages: list[dict] = []

        # Load routing rules from editable config
        routing = load_routing_rules()
        route = routing.get(query_analysis.classification, {}) if query_analysis else {}

        # -- Parallel context assembly --
        # All these queries are independent. Run them concurrently.

        skip_rag = route.get("skip_rag", False)
        skip_profile = route.get("skip_profile", False)
        skip_experiences = route.get("skip_experiences", False)
        skip_documents = route.get("skip_documents", False)

        async def _recovery_briefing():
            if not self.db or skip_rag:
                return ""
            try:
                plan_row = await self.db.fetch_one(
                    "SELECT steps, updated_at FROM task_plans WHERE conversation_id = ? "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (conversation_id,),
                )
                if plan_row:
                    steps = json.loads(plan_row["steps"])
                    pending = [s for s in steps if s.get("status") != "done"]
                    done = [s for s in steps if s.get("status") == "done"]
                    if pending and done:
                        lines = ["## Recovery: you have an unfinished plan"]
                        lines.append(f"Completed: {len(done)} steps. Remaining: {len(pending)} steps.")
                        for s in pending:
                            lines.append(f"- Pending: Step {s['step']}: {s['task']}")
                        return "\n".join(lines)
            except Exception:
                logger.debug("Could not load recovery briefing", exc_info=True)
            return ""

        async def _memory_context():
            if not self.memory_manager or skip_rag:
                return ""
            try:
                if query_analysis and query_analysis.search_queries:
                    recall_query = " ".join(query_analysis.search_queries)
                    return await self.memory_manager.recall(recall_query)
                return await self.memory_manager.recall(message_content)
            except Exception:
                logger.debug("Memory recall failed", exc_info=True)
                return ""

        async def _memory_index():
            global _memory_index_cache
            if not self.db or skip_rag:
                return ""
            # Return cached result if within TTL
            import time as _time
            now = _time.monotonic()
            if _memory_index_cache is not None:
                cached_at, cached_val = _memory_index_cache
                if now - cached_at < _MEMORY_INDEX_TTL:
                    return cached_val
            try:
                row = await self.db.fetch_one("""
                    SELECT
                        (SELECT COUNT(*) FROM memory_entries WHERE source_type = 'document_chunk') as doc_chunks,
                        (SELECT COUNT(*) FROM memory_entries WHERE source_type = 'user_message') as conversations,
                        (SELECT COUNT(*) FROM entities WHERE status = 'active') as entities,
                        (SELECT COUNT(*) FROM documents) as documents
                """)
                counts = {
                    "doc_chunks": row["doc_chunks"] if row else 0,
                    "conversations": row["conversations"] if row else 0,
                    "entities": row["entities"] if row else 0,
                    "documents": row["documents"] if row else 0,
                }
                result = ""
                if any(counts.values()):
                    result = (
                        f"## Memory index: {counts['documents']} documents ({counts['doc_chunks']} chunks), "
                        f"{counts['conversations']} conversation memories, {counts['entities']} entities"
                    )
                _memory_index_cache = (now, result)
                return result
            except Exception:
                logger.debug("Could not build memory index", exc_info=True)
            return ""

        async def _doc_listing():
            if not self.db or skip_documents:
                return ""
            try:
                doc_rows = await self.db.fetch_all(
                    "SELECT id, filename, chunk_count FROM documents WHERE status IN ('complete', 'ingested') ORDER BY filename"
                )
                if doc_rows:
                    lines = [
                        "## Available documents",
                        "Write Python code with list_documents(), read_document(name), search_documents(query) to analyze these:",
                        "",
                    ]
                    for row in doc_rows:
                        lines.append(f"- [{row['id'][:8]}] {row['filename']} ({row['chunk_count']} chunks)")
                    return "\n".join(lines)
            except Exception:
                logger.debug("Failed to list documents", exc_info=True)
            return ""

        async def _skill_hints():
            if not query_analysis or not self.db:
                return ""
            try:
                classification = query_analysis.classification
                rows = await self.db.fetch_all(
                    "SELECT su.skill_name, su.skill_type, AVG(su.evaluation_score) as avg_score, COUNT(*) as uses "
                    "FROM skill_usage su "
                    "JOIN query_log ql ON su.conversation_id = ql.conversation_id "
                    "WHERE ql.classification = ? AND su.evaluation_score > 0.7 "
                    "GROUP BY su.skill_name "
                    "ORDER BY avg_score DESC LIMIT 5",
                    (classification,),
                )
                if rows:
                    lines = ["## Relevant skills for this type of query"]
                    for row in rows:
                        lines.append(f"- {row['skill_name']} ({row['skill_type']}, used {row['uses']}x, avg score {(row['avg_score'] or 0):.1f})")
                    return "\n".join(lines)
            except Exception:
                logger.debug("Failed to query skill usage hints", exc_info=True)
            return ""

        async def _corrections():
            if not self.corrections_manager:
                return ""
            try:
                return await self.corrections_manager.relevant(message_content)
            except Exception:
                logger.debug("Corrections lookup failed", exc_info=True)
                return ""

        async def _error_hints():
            if not self.db:
                return ""
            try:
                error_rows = await get_recent_tool_errors(self.db, days=1)
                if error_rows:
                    lines = ["## Recent tool issues (avoid repeating)"]
                    for row in error_rows[:5]:
                        lines.append(
                            f"- {row['tool_name']}: {row['error_type']} ({row['count']}x in last 24h)"
                        )
                    return "\n".join(lines)
            except Exception:
                logger.debug("Could not load error hints", exc_info=True)
            return ""

        async def _experiences():
            if not self.db or skip_experiences:
                return ""
            try:
                classification_type = (
                    query_analysis.classification if query_analysis else "standard"
                )

                # Tier 1: Dynamic lookup from query_log history
                tool_names = await _get_likely_tools(self.db, classification_type)

                # Tier 2: Static fallback map
                if not tool_names:
                    tool_names = _FALLBACK_TOOLS.get(classification_type, [])

                # Tier 3: Category-based fallback from tool registry
                if not tool_names:
                    cats = _CLASS_CATEGORIES.get(classification_type, [])
                    if cats and hasattr(self, 'tool_registry') and self.tool_registry:
                        tool_names = [
                            t.name for t in self.tool_registry.list()
                            if t.category in cats
                        ]

                if tool_names:
                    placeholders = ",".join("?" * len(tool_names))
                    exp_rows = await self.db.fetch_all(
                        f"SELECT tool_name, lesson, success, confidence "
                        f"FROM agent_experiences "
                        f"WHERE tool_name IN ({placeholders}) "
                        f"ORDER BY confidence DESC, updated_at DESC LIMIT 5",
                        tool_names,
                    )
                else:
                    exp_rows = await self.db.fetch_all(
                        "SELECT tool_name, lesson, success, confidence "
                        "FROM agent_experiences "
                        "WHERE confidence >= 0.7 OR success = 0 "
                        "ORDER BY confidence DESC, updated_at DESC LIMIT 5"
                    )

                if not exp_rows:
                    return ""

                lines = ["## Tactical experience (learned from past interactions)"]
                for row in exp_rows:
                    prefix = "Warning" if not row["success"] else "Tip"
                    lines.append(f"- [{prefix}] {row['tool_name']}: {row['lesson']}")
                return "\n".join(lines)
            except Exception:
                logger.debug("Could not load experiences", exc_info=True)
            return ""

        async def _user_profile():
            if not self.db or skip_profile:
                return ""
            parts = []
            # Free-form profile (legacy)
            try:
                profile_row = await get_user_profile(self.db)
                if profile_row and profile_row.get("summary"):
                    lines = ["## About your user"]
                    if profile_row["summary"]:
                        lines.append(profile_row["summary"])
                    if profile_row.get("communication_style"):
                        lines.append(
                            f"Communication style: "
                            f"{profile_row['communication_style']}"
                        )
                    if profile_row.get("preferences"):
                        lines.append(
                            f"Preferences: {profile_row['preferences']}"
                        )
                    if profile_row.get("expertise_areas"):
                        lines.append(
                            f"Expertise: {profile_row['expertise_areas']}"
                        )
                    parts.append("\n".join(lines))
            except Exception:
                logger.debug(
                    "Could not load user profile", exc_info=True,
                )
            # Structured profile (v2)
            try:
                v2_row = await self.db.fetch_one(
                    "SELECT profile_json FROM user_profile_v2 "
                    "WHERE id = 'owner'"
                )
                if v2_row and v2_row["profile_json"]:
                    profile = UserProfile.from_json(
                        v2_row["profile_json"]
                    )
                    structured = format_profile_for_context(profile)
                    parts.append(structured)
            except Exception:
                logger.debug(
                    "Could not load structured profile",
                    exc_info=True,
                )
            return "\n\n".join(parts)

        async def _user_facts():
            if not self.db or skip_profile:
                return ""
            try:
                fact_rows = await get_user_facts(self.db, limit=20)
                if fact_rows:
                    lines = ["## Known facts about your user"]
                    for row in fact_rows:
                        lines.append(f"- [{row['category']}] {row['fact']}")
                    return "\n".join(lines)
            except Exception:
                logger.debug("Could not load user facts", exc_info=True)
            return ""

        async def _sections():
            if self.checkpoint_manager:
                return await self.checkpoint_manager.get_working_sections()
            return self.fallback_registry.load_all()

        async def _last_interaction():
            """Get a brief summary of the most recent conversation on any channel."""
            if not self.db:
                return ""
            try:
                row = await self.db.fetch_one(
                    "SELECT c.id, c.channel, c.title, c.last_message_at, "
                    "  (SELECT content FROM messages WHERE conversation_id = c.id AND role = 'user' "
                    "   ORDER BY timestamp DESC LIMIT 1) as last_user_msg, "
                    "  (SELECT content FROM messages WHERE conversation_id = c.id AND role = 'assistant' "
                    "   ORDER BY timestamp DESC LIMIT 1) as last_assistant_msg "
                    "FROM conversations c "
                    "WHERE c.id != ? AND c.last_message_at IS NOT NULL "
                    "ORDER BY c.last_message_at DESC LIMIT 1",
                    (conversation_id,),
                )
                if not row or not row["last_user_msg"]:
                    return ""
                channel = row["channel"] or "unknown"
                title = row["title"] or "a conversation"
                when = row["last_message_at"] or ""
                user_preview = row["last_user_msg"][:150]
                asst_preview = (row["last_assistant_msg"] or "")[:150]
                return (
                    f"## Last interaction (via {channel}, {when})\n"
                    f"Topic: {title}\n"
                    f"User said: {user_preview}\n"
                    f"You replied: {asst_preview}"
                )
            except Exception:
                logger.debug("Could not load last interaction", exc_info=True)
                return ""

        async def _heartbeat_context() -> str:
            """Load recent autonomous work summaries from heartbeat sessions."""
            try:
                rows = await self.db.fetch_all(
                    "SELECT summary, created_at FROM heartbeat_sessions "
                    "ORDER BY created_at DESC LIMIT 5",
                )
                if not rows:
                    return ""
                lines = ["## Recent autonomous work"]
                for r in rows:
                    lines.append(f"- [{r['created_at'][:16]}] {r['summary'][:300]}")
                return "\n".join(lines)
            except Exception:
                return ""

        # Run all context queries in parallel
        (
            recovery_briefing, memory_context, memory_index, doc_listing,
            skill_hints, corrections_context, error_hints, experiences_section,
            user_profile, user_facts, sections, last_interaction, heartbeat_ctx,
        ) = await asyncio.gather(
            _recovery_briefing(), _memory_context(), _memory_index(), _doc_listing(),
            _skill_hints(), _corrections(), _error_hints(), _experiences(),
            _user_profile(), _user_facts(), _sections(), _last_interaction(),
            _heartbeat_context(),
        )

        # Build skill catalog sorted by maturity (sync, no DB call)
        skill_catalog = ""
        if self.skill_registry:
            _mat_order = {
                "mature": 0, "committed": 1, "progenitor": 2,
            }
            # Skills are discovered via find_tools, not listed in system prompt.
            # The old approach dumped all skill names here (~5K chars) which caused
            # context rot and prevented the model from calling find_tools.
            skill_catalog = ""

        # Add decomposition hints for complex queries
        if query_analysis and query_analysis.sub_questions:
            sub_q_text = "\n".join(f"- {q}" for q in query_analysis.sub_questions)
            memory_context += f"\n\n## Analysis hints\nConsider addressing these aspects:\n{sub_q_text}"

        # Active task plan -- NOT auto-injected. Agent uses check_plan tool when needed.
        active_plan = ""

        # Notebook context (when user is on a notebook page)
        notebook_context = ""
        if context_metadata and context_metadata.get("notebook_id") and self.db:
            try:
                nb_id = context_metadata["notebook_id"]
                nb_row = await self.db.fetch_one(
                    "SELECT title, mode, collaboration FROM notebooks WHERE id = ?",
                    (nb_id,),
                )
                if nb_row:
                    lines = [
                        f"## Active notebook: \"{nb_row['title']}\" (mode: {nb_row['mode']}, collaboration: {nb_row['collaboration']})",
                        "Recent entries:",
                    ]
                    entry_rows = await self.db.fetch_all(
                        "SELECT content, entry_type, mood, created_at FROM notebook_entries "
                        "WHERE notebook_id = ? AND status = 'active' "
                        "ORDER BY created_at DESC LIMIT 10",
                        (nb_id,),
                    )
                    for row in reversed(entry_rows):  # chronological order
                        prefix = f"[{row['entry_type']}]"
                        if row.get("mood"):
                            prefix += f" ({row['mood']})"
                        lines.append(f"- {prefix} {row['content'][:200]}")
                    notebook_context = "\n".join(lines)
            except Exception:
                logger.debug("Could not load notebook context", exc_info=True)

        # Board context (when user is on a kanban board page)
        if context_metadata and context_metadata.get("board_id") and self.db:
            try:
                board_id = context_metadata["board_id"]
                board_row = await self.db.fetch_one(
                    "SELECT title, description FROM kanban_boards WHERE id = ?",
                    (board_id,),
                )
                if board_row:
                    lines = [
                        f"## Active kanban board: \"{board_row['title']}\"",
                    ]
                    if board_row.get("description"):
                        lines.append(f"Description: {board_row['description']}")
                    col_rows = await self.db.fetch_all(
                        "SELECT id, title FROM kanban_columns WHERE board_id = ? ORDER BY position ASC",
                        (board_id,),
                    )
                    card_rows = await self.db.fetch_all(
                        "SELECT title, column_id, priority FROM kanban_cards "
                        "WHERE board_id = ? ORDER BY position ASC",
                        (board_id,),
                    )
                    cards_by_col = {}
                    for card in card_rows:
                        cards_by_col.setdefault(card["column_id"], []).append(card)
                    for col in col_rows:
                        col_cards = cards_by_col.get(col["id"], [])
                        lines.append(f"\n**{col['title']}** ({len(col_cards)} cards)")
                        for card in col_cards[:10]:
                            lines.append(f"- {card['title']}")
                    notebook_context = "\n".join(lines)
            except Exception:
                logger.debug("Could not load board context", exc_info=True)

        # Enrich page context from bubble/UI metadata
        if context_metadata:
            page = context_metadata.get("page")
            if page and page not in ("chat",):
                page_lines = []
                page_title = context_metadata.get("page_title", "")
                visible_data = context_metadata.get("visible_data", "")
                if page_title:
                    scan = _context_filter.scan(page_title)
                    safe_title = scan.sanitized_text
                    page_lines.append(f"## User is currently viewing: {safe_title} ({page} page)")
                elif page:
                    page_lines.append(f"## User is currently on the {page} page")
                if visible_data:
                    scan = _context_filter.scan(visible_data)
                    page_lines.append(scan.sanitized_text)
                if page_lines and not notebook_context:
                    notebook_context = "\n".join(page_lines)
                elif page_lines:
                    notebook_context = notebook_context + "\n\n" + "\n".join(page_lines)

        # Image prompt guide removed from system prompt — it's injected
        # only when generate_image is actually called, via the tool's own context.

        concise_mode = self.settings.agent.concise_mode if self.settings else False

        # Prune low-relevance context sections
        classification = (
            query_analysis.classification if query_analysis else ""
        )
        prunable = {
            "memory_context": memory_context,
            "memory_index": memory_index,
            "skill_catalog": skill_catalog,
            "corrections": corrections_context,
            "doc_listing": doc_listing,
            "skill_hints": skill_hints,
            "active_plan": active_plan,
            "error_hints": error_hints,
            "experiences": experiences_section,
            "user_profile": user_profile,
            "user_facts": user_facts,
            "recovery_briefing": recovery_briefing,
            "page_context": notebook_context,
            "last_interaction": last_interaction,
        }
        pruned = prune_sections(
            query=message_content,
            sections=prunable,
            classification=classification,
        )
        memory_context = pruned.get("memory_context", "")
        memory_index = pruned.get("memory_index", "")
        skill_catalog = pruned.get("skill_catalog", "")
        corrections_context = pruned.get("corrections", "")
        doc_listing = pruned.get("doc_listing", "")
        skill_hints = pruned.get("skill_hints", "")
        active_plan = pruned.get("active_plan", "")
        error_hints = pruned.get("error_hints", "")
        experiences_section = pruned.get("experiences", "")
        user_profile = pruned.get("user_profile", "")
        user_facts = pruned.get("user_facts", "")
        recovery_briefing = pruned.get("recovery_briefing", "")
        if heartbeat_ctx:
            recovery_briefing = (recovery_briefing + "\n\n" + heartbeat_ctx).strip()
        notebook_context = pruned.get("page_context", "")
        last_interaction = pruned.get("last_interaction", "")

        system_prompt = build_system_prompt(
            sections=sections,
            memory_context=memory_context,
            memory_index=memory_index,
            skill_catalog=skill_catalog,
            corrections_context=corrections_context,
            doc_listing=doc_listing,
            agent_name=self.agent_name,
            skill_hints=skill_hints,
            active_plan=active_plan,
            error_hints=error_hints,
            experiences=experiences_section,
            user_profile=user_profile,
            user_facts=user_facts,
            recovery_briefing=recovery_briefing,
            page_context=notebook_context,
            last_interaction=last_interaction,
            concise_mode=concise_mode,
        )

        messages.append({"role": "system", "content": system_prompt})

        # Trigger summarization if needed
        if self.summarizer:
            try:
                await self.summarizer.summarize_if_needed(conversation_id)
            except Exception:
                logger.debug("Summarization failed for %s", conversation_id, exc_info=True)

        # Inject conversation summaries
        summaries = await self.db.fetch_all(
            "SELECT summary FROM conversation_summaries "
            "WHERE conversation_id = ? ORDER BY start_message_idx ASC",
            (conversation_id,),
        )
        if summaries:
            combined = "\n\n".join(row["summary"] for row in summaries)
            scan = _context_filter.scan(combined)
            messages.append({
                "role": "system",
                "content": f"[Previous conversation summary]:\n\n{scan.sanitized_text}",
            })

        # Conversation history
        history = await self.db.fetch_all(
            "SELECT role, content FROM messages "
            "WHERE conversation_id = ? "
            "ORDER BY timestamp ASC "
            "LIMIT ?",
            (conversation_id, self.history_limit),
        )
        for row in history:
            messages.append({"role": row["role"], "content": row["content"]})

        # Current message
        messages.append({"role": "user", "content": message_content})

        if max_tokens > 0:
            messages = self._trim_to_budget(messages, max_tokens)

        return messages

    async def build_headless(
        self,
        step_description: str,
        plan_context: str = "",
    ) -> list[dict]:
        """Build a lightweight context for headless/background execution.

        Skips conversation history, page context, recovery briefing, skill catalog,
        and memory index. Includes RAG recall, experiences, and user profile.
        """
        async def _memory_context():
            if not self.memory_manager:
                return ""
            try:
                return await self.memory_manager.recall(step_description)
            except Exception:
                logger.debug("Headless memory recall failed", exc_info=True)
                return ""

        async def _experiences():
            if not self.db:
                return ""
            try:
                exp_rows = await self.db.fetch_all(
                    "SELECT tool_name, lesson, success, confidence "
                    "FROM agent_experiences "
                    "WHERE confidence >= 0.7 OR success = 0 "
                    "ORDER BY confidence DESC, updated_at DESC LIMIT 5"
                )
                if not exp_rows:
                    return ""
                lines = ["## Tactical experience (learned from past interactions)"]
                for row in exp_rows:
                    prefix = "Warning" if not row["success"] else "Tip"
                    lines.append(f"- [{prefix}] {row['tool_name']}: {row['lesson']}")
                return "\n".join(lines)
            except Exception:
                logger.debug("Headless experiences failed", exc_info=True)
                return ""

        async def _user_profile():
            if not self.db:
                return ""
            parts = []
            try:
                profile_row = await get_user_profile(self.db)
                if profile_row and profile_row.get("summary"):
                    lines = ["## About your user"]
                    if profile_row["summary"]:
                        lines.append(profile_row["summary"])
                    parts.append("\n".join(lines))
            except Exception:
                logger.debug("Headless profile failed", exc_info=True)
            try:
                v2_row = await self.db.fetch_one(
                    "SELECT profile_json FROM user_profile_v2 WHERE id = 'owner'"
                )
                if v2_row and v2_row["profile_json"]:
                    profile = UserProfile.from_json(v2_row["profile_json"])
                    parts.append(format_profile_for_context(profile))
            except Exception:
                logger.debug("Headless structured profile failed", exc_info=True)
            return "\n\n".join(parts)

        async def _sections():
            if self.checkpoint_manager:
                return await self.checkpoint_manager.get_working_sections()
            return self.fallback_registry.load_all()

        # Run context queries in parallel
        memory_context, experiences_section, user_profile, sections = await asyncio.gather(
            _memory_context(), _experiences(), _user_profile(), _sections(),
        )

        system_prompt = build_system_prompt(
            sections=sections,
            memory_context=memory_context,
            agent_name=self.agent_name,
            experiences=experiences_section,
            user_profile=user_profile,
            active_plan=f"## Current plan context\n{plan_context}" if plan_context else "",
            concise_mode=True,
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": step_description},
        ]

    def _trim_to_budget(self, messages: list[dict], max_tokens: int) -> list[dict]:
        """Trim summary messages first, then history (oldest first) to fit within token budget."""
        total = sum(estimate_tokens(m["content"]) for m in messages)

        if total <= max_tokens:
            return messages

        # Phase 1: Remove summary messages first
        i = 1
        while total > max_tokens and i < len(messages) - 1:
            if messages[i]["content"].startswith("[Previous conversation summary]"):
                removed = messages.pop(i)
                total -= estimate_tokens(removed["content"])
                logger.debug("Trimmed summary message to fit context budget")
            else:
                i += 1

        # Phase 2: Remove oldest history messages (existing behavior)
        while total > max_tokens and len(messages) > 2:
            removed = messages.pop(1)
            total -= estimate_tokens(removed["content"])
            logger.debug("Trimmed history message to fit context budget")

        # Phase 3: If still over budget, truncate the current user message
        if total > max_tokens and len(messages) >= 2:
            last_msg = messages[-1]
            excess = total - max_tokens
            content = last_msg["content"]
            tokens = _tokenizer.encode(content, disallowed_special=())
            keep = len(tokens) - excess
            if keep > 0:
                last_msg["content"] = _tokenizer.decode(tokens[:keep]) + "\n\n[message truncated to fit context window]"
                logger.warning(
                    "Truncated user message by ~%d tokens to fit context budget",
                    excess,
                )
            else:
                logger.warning(
                    "Context still over budget after trimming all history (%d > %d tokens)",
                    total,
                    max_tokens,
                )

        return messages
