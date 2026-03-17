from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import tiktoken

from odigos.core.prompt_loader import load_prompt
from odigos.core.queries import get_recent_tool_errors, get_user_facts, get_user_profile
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


def _load_routing_rules() -> dict:
    """Load routing rules from data/agent/routing_rules.md."""
    text = load_prompt("routing_rules.md", fallback="", base_dir="data/agent")
    rules: dict[str, dict[str, bool]] = {}
    current_section: str | None = None
    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1]
            rules[current_section] = {}
        elif ":" in line and current_section:
            key, val = line.split(":", 1)
            rules[current_section][key.strip()] = val.strip().lower() == "true"
    return rules


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
        self._fallback_registry = SectionRegistry(sections_dir)

    async def build(
        self,
        conversation_id: str,
        current_message: str,
        max_tokens: int = 0,
        *,
        query_analysis: QueryAnalysis | None = None,
    ) -> list[dict]:
        """Assemble the full messages list: system + history + current."""
        messages: list[dict] = []

        # Load routing rules from editable config
        routing = _load_routing_rules()
        route = routing.get(query_analysis.classification, {}) if query_analysis else {}

        # Get memory context if available
        memory_context = ""
        if self.memory_manager:
            if route.get("skip_rag", False):
                pass  # Skip RAG per routing rules
            elif query_analysis and query_analysis.search_queries:
                # Use optimized search queries from classifier
                recall_query = " ".join(query_analysis.search_queries)
                memory_context = await self.memory_manager.recall(recall_query)
            else:
                memory_context = await self.memory_manager.recall(current_message)

        # Build skill catalog if available
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

        # Document listing for code-based analysis
        doc_listing = ""
        if self.db and not route.get("skip_documents", False):
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
                    doc_listing = "\n".join(lines)
            except Exception:
                logger.debug("Failed to list documents (table may not exist)", exc_info=True)

        # Skill recommendations based on past usage
        skill_hints = ""
        if query_analysis and self.db:
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
                    skill_hints = "\n".join(lines)
            except Exception:
                logger.debug("Failed to query skill usage hints", exc_info=True)

        # Get corrections context if available
        corrections_context = ""
        if self.corrections_manager:
            corrections_context = await self.corrections_manager.relevant(current_message)

        # Load dynamic prompt sections
        if self.checkpoint_manager:
            sections = await self.checkpoint_manager.get_working_sections()
        else:
            sections = self._fallback_registry.load_all()

        # Add decomposition hints for complex queries
        if query_analysis and query_analysis.sub_questions:
            sub_q_text = "\n".join(f"- {q}" for q in query_analysis.sub_questions)
            memory_context += f"\n\n## Analysis hints\nConsider addressing these aspects:\n{sub_q_text}"

        # Active task plan -- NOT auto-injected. Agent uses check_plan tool when needed.
        active_plan = ""

        # Recent tool errors (helps agent avoid repeating mistakes)
        error_hints = ""
        if self.db:
            try:
                error_rows = await get_recent_tool_errors(self.db, days=1)
                if error_rows:
                    lines = ["## Recent tool issues (avoid repeating)"]
                    for row in error_rows[:5]:
                        lines.append(
                            f"- {row['tool_name']}: {row['error_type']} ({row['count']}x in last 24h)"
                        )
                    error_hints = "\n".join(lines)
            except Exception:
                logger.debug("Could not load error hints", exc_info=True)

        # Tactical experiences (learned from past interactions)
        experiences_section = ""
        if self.db and not route.get("skip_experiences", False):
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
                    experiences_section = "\n".join(lines)
            except Exception:
                logger.debug("Could not load experiences", exc_info=True)

        # User profile (built from conversation patterns)
        user_profile = ""
        if self.db and not route.get("skip_profile", False):
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
                    user_profile = "\n".join(lines)
            except Exception:
                logger.debug("Could not load user profile", exc_info=True)

        # User facts (discrete remembered/extracted facts)
        user_facts = ""
        if self.db and not route.get("skip_profile", False):
            try:
                fact_rows = await get_user_facts(self.db, limit=20)
                if fact_rows:
                    lines = ["## Known facts about your user"]
                    for row in fact_rows:
                        lines.append(f"- [{row['category']}] {row['fact']}")
                    user_facts = "\n".join(lines)
            except Exception:
                logger.debug("Could not load user facts", exc_info=True)

        system_prompt = build_system_prompt(
            sections=sections,
            memory_context=memory_context,
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
        messages.append({"role": "user", "content": current_message})

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
