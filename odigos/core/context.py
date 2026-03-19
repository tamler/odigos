from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import tiktoken

from odigos.core.prompt_loader import load_prompt
from odigos.core.queries import get_recent_tool_errors, get_user_facts, get_user_profile
from odigos.core.routing import load_routing_rules
from odigos.db import Database
from odigos.personality.section_registry import SectionRegistry
from odigos.personality.prompt_builder import build_system_prompt

if TYPE_CHECKING:
    from odigos.core.checkpoint import CheckpointManager
    from odigos.core.classifier import QueryAnalysis
    from odigos.memory.corrections import CorrectionsManager
    from odigos.memory.manager import MemoryManager
    from odigos.memory.summarizer import ConversationSummarizer
    from odigos.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

_tokenizer = tiktoken.get_encoding("cl100k_base")


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
    ) -> None:
        self.db = db
        self.agent_name = agent_name
        self.history_limit = history_limit
        self.memory_manager = memory_manager
        self.summarizer = summarizer
        self.skill_registry = skill_registry
        self.corrections_manager = corrections_manager
        self.checkpoint_manager = checkpoint_manager
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
            if not self.db or skip_rag:
                return ""
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
                if any(counts.values()):
                    return (
                        f"## Memory index: {counts['documents']} documents ({counts['doc_chunks']} chunks), "
                        f"{counts['conversations']} conversation memories, {counts['entities']} entities"
                    )
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
                exp_rows = await self.db.fetch_all(
                    "SELECT tool_name, lesson FROM agent_experiences "
                    "WHERE times_applied > 0 OR success = 0 "
                    "ORDER BY updated_at DESC LIMIT 10"
                )
                if exp_rows:
                    lines = ["## Tactical experience (learned from past interactions)"]
                    for row in exp_rows:
                        lines.append(f"- {row['tool_name']}: {row['lesson']}")
                    return "\n".join(lines)
            except Exception:
                logger.debug("Could not load experiences", exc_info=True)
            return ""

        async def _user_profile():
            if not self.db or skip_profile:
                return ""
            try:
                profile_row = await get_user_profile(self.db)
                if profile_row and profile_row.get("summary"):
                    lines = ["## About your user"]
                    if profile_row["summary"]:
                        lines.append(profile_row["summary"])
                    if profile_row.get("communication_style"):
                        lines.append(f"Communication style: {profile_row['communication_style']}")
                    if profile_row.get("preferences"):
                        lines.append(f"Preferences: {profile_row['preferences']}")
                    if profile_row.get("expertise_areas"):
                        lines.append(f"Expertise: {profile_row['expertise_areas']}")
                    return "\n".join(lines)
            except Exception:
                logger.debug("Could not load user profile", exc_info=True)
            return ""

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

        # Run all context queries in parallel
        (
            recovery_briefing, memory_context, memory_index, doc_listing,
            skill_hints, corrections_context, error_hints, experiences_section,
            user_profile, user_facts, sections,
        ) = await asyncio.gather(
            _recovery_briefing(), _memory_context(), _memory_index(), _doc_listing(),
            _skill_hints(), _corrections(), _error_hints(), _experiences(),
            _user_profile(), _user_facts(), _sections(),
        )

        # Build skill catalog (sync, no DB call)
        skill_catalog = ""
        if self.skill_registry:
            skills = self.skill_registry.list()
            if skills:
                lines = [
                    "## Available skills",
                    "Use activate_skill to load a skill's full instructions before starting the task.",
                ]
                for s in skills:
                    lines.append(f"- **{s.name}**: {s.description}")
                skill_catalog = "\n".join(lines)

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
            messages.append({
                "role": "system",
                "content": f"[Previous conversation summary]:\n\n{combined}",
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
