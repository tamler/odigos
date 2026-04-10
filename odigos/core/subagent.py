from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from odigos.core.executor import Executor
from odigos.core.prompt_loader import load_prompt
from odigos.db import Database
from odigos.providers.base import LLMProvider
from odigos.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from odigos.core.trace import Tracer
    from odigos.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


@dataclass
class SubagentPersona:
    """A sub-agent persona definition loaded from data/subagents/."""
    name: str
    description: str
    model: str = "default"
    tools: list[str] = field(default_factory=list)
    max_runtime_seconds: int = 600
    skill: str | None = None
    tools_override: bool = False
    workspace_roots: list[str] = field(default_factory=list)
    system_prompt: str = ""


# Module-level cache: name → (persona, mtime)
_persona_cache: dict[str, tuple[SubagentPersona, float]] = {}


def load_persona(name: str, personas_dir: str = "data/subagents") -> SubagentPersona | None:
    """Load a sub-agent persona from disk.

    Returns None if the persona file doesn't exist.
    Uses an mtime-keyed in-memory cache.
    """
    path = Path(personas_dir) / f"{name}.md"
    if not path.exists():
        return None

    mtime = path.stat().st_mtime
    cached = _persona_cache.get(name)
    if cached and cached[1] == mtime:
        return cached[0]

    text = path.read_text()
    frontmatter_dict: dict[str, Any] = {}
    body = text

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter_dict = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                logger.warning("Invalid YAML frontmatter in persona %s", name)
            body = parts[2].lstrip("\n")

    persona = SubagentPersona(
        name=frontmatter_dict.get("name", name),
        description=frontmatter_dict.get("description", ""),
        model=frontmatter_dict.get("model", "default"),
        tools=list(frontmatter_dict.get("tools") or []),
        max_runtime_seconds=int(frontmatter_dict.get("max_runtime_seconds", 600)),
        skill=frontmatter_dict.get("skill"),
        tools_override=bool(frontmatter_dict.get("tools_override", False)),
        workspace_roots=list(frontmatter_dict.get("workspace_roots") or []),
        system_prompt=body.strip(),
    )

    _persona_cache[name] = (persona, mtime)
    return persona


def validate_persona(persona: SubagentPersona, known_tool_names: set[str]) -> list[str]:
    """Check that tool names referenced in the system prompt are in the whitelist.

    Returns a list of warning messages.
    """
    warnings: list[str] = []
    whitelist = set(persona.tools)

    for tool_name in known_tool_names:
        if re.search(rf"\b{re.escape(tool_name)}\b", persona.system_prompt):
            if tool_name not in whitelist:
                warnings.append(
                    f"Persona '{persona.name}' references tool '{tool_name}' "
                    f"in its prompt but it's not in the whitelist"
                )

    return warnings


def resolve_tools(
    persona_tools: list[str],
    skill_tools: list[str],
    explicit_tools: list[str] | None,
    tools_override: bool,
) -> list[str]:
    """Resolve the sub-agent's tool whitelist.

    Precedence:
    1. If explicit_tools given, use them.
    2. If tools_override=True, use persona_tools only.
    3. Otherwise, union of skill_tools and persona_tools.
    """
    if explicit_tools is not None:
        return list(explicit_tools)
    if tools_override:
        return list(persona_tools)
    # Union, preserving order
    seen: set[str] = set()
    result: list[str] = []
    for t in list(persona_tools) + list(skill_tools):
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result

_SUBAGENT_SYSTEM_FALLBACK = (
    "You are a focused subagent. Complete the given task concisely. "
    "Do not ask follow-up questions."
)

MAX_CONCURRENT_PER_CONVERSATION = 3
DEFAULT_TIMEOUT = 600


class _SubagentContext:
    """Minimal context assembler for subagents.

    Returns pre-built messages instead of assembling from conversation history.
    """

    def __init__(self, messages: list[dict]) -> None:
        self._messages = messages

    async def build(
        self,
        conversation_id: str,
        message_content: str,
        max_tokens: int = 0,
        *,
        query_analysis=None,
        context_metadata: dict | None = None,
    ) -> list[dict]:
        return list(self._messages)


class SubagentManager:
    """Manages subagent lifecycle: spawn, execute, store results."""

    def __init__(
        self,
        db: Database,
        provider: LLMProvider,
        tool_registry: ToolRegistry,
        tracer: Tracer | None = None,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self.db = db
        self.provider = provider
        self.tool_registry = tool_registry
        self.tracer = tracer
        self.memory_manager = memory_manager
        self._tasks: dict[str, asyncio.Task] = {}

    async def spawn(
        self,
        instruction: str,
        parent_conversation_id: str,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> str:
        """Spawn a new subagent task. Returns the subagent ID."""
        subagent_id = str(uuid.uuid4())

        # Atomic insert: only succeeds if fewer than MAX_CONCURRENT running
        await self.db.execute(
            "INSERT INTO subagent_tasks (id, parent_conversation_id, instruction, status) "
            "SELECT ?, ?, ?, 'running' "
            "WHERE (SELECT COUNT(*) FROM subagent_tasks "
            "       WHERE parent_conversation_id = ? AND status = 'running') < ?",
            (subagent_id, parent_conversation_id, instruction,
             parent_conversation_id, MAX_CONCURRENT_PER_CONVERSATION),
        )

        # Verify the row was actually inserted
        row = await self.db.fetch_one(
            "SELECT id FROM subagent_tasks WHERE id = ?", (subagent_id,)
        )
        if row is None:
            raise ValueError(
                f"Max concurrent subagents ({MAX_CONCURRENT_PER_CONVERSATION}) "
                f"reached for conversation {parent_conversation_id}"
            )

        task = asyncio.create_task(
            self._run_subagent(subagent_id, instruction, parent_conversation_id, timeout)
        )
        self._tasks[subagent_id] = task
        return subagent_id

    async def _run_subagent(
        self,
        subagent_id: str,
        instruction: str,
        parent_conversation_id: str,
        timeout: int,
    ) -> None:
        """Execute a subagent task in the background."""
        try:
            messages: list[dict] = [
                {
                    "role": "system",
                    "content": load_prompt("subagent.md", _SUBAGENT_SYSTEM_FALLBACK),
                },
            ]

            if self.memory_manager:
                try:
                    memory_context = await self.memory_manager.recall(instruction)
                    if memory_context:
                        messages.append(
                            {"role": "system", "content": f"Relevant context:\n{memory_context}"}
                        )
                except Exception:
                    logger.debug("Memory recall failed for subagent %s", subagent_id, exc_info=True)

            messages.append({"role": "user", "content": instruction})

            restricted_registry = self._build_restricted_registry()
            context = _SubagentContext(messages)
            executor = Executor(
                provider=self.provider,
                context_assembler=context,
                tool_registry=restricted_registry,
                db=self.db,
                tracer=self.tracer,
            )

            result = await asyncio.wait_for(
                executor.execute(f"subagent:{subagent_id}", instruction),
                timeout=timeout,
            )

            result_content = result.response.content or "Subagent completed with no output."
            now = datetime.now(timezone.utc).isoformat()
            await self.db.execute(
                "UPDATE subagent_tasks SET status = 'completed', result = ?, completed_at = ? "
                "WHERE id = ?",
                (result_content, now, subagent_id),
            )
        except (TimeoutError, asyncio.TimeoutError):
            now = datetime.now(timezone.utc).isoformat()
            await self.db.execute(
                "UPDATE subagent_tasks SET status = 'failed', result = ?, completed_at = ? "
                "WHERE id = ?",
                ("Subagent timed out", now, subagent_id),
            )
        except Exception as e:
            now = datetime.now(timezone.utc).isoformat()
            await self.db.execute(
                "UPDATE subagent_tasks SET status = 'failed', result = ?, completed_at = ? "
                "WHERE id = ?",
                (f"Error: {str(e)[:500]}", now, subagent_id),
            )
        finally:
            if self.tracer:
                try:
                    await self.tracer.emit(
                        "subagent_completed",
                        parent_conversation_id,
                        {"subagent_id": subagent_id, "instruction": instruction},
                    )
                except Exception:
                    logger.debug("Failed to emit subagent trace", exc_info=True)
            self._tasks.pop(subagent_id, None)

    def _build_restricted_registry(self) -> ToolRegistry:
        """Clone all tools except spawn_subagent to prevent recursive spawning."""
        restricted = ToolRegistry()
        for tool in self.tool_registry.list():
            if tool.name != "spawn_subagent":
                restricted.register(tool)
        return restricted

    async def get_completed_all(self) -> list[dict]:
        """Return all completed/failed tasks that have not been delivered yet."""
        return await self.db.fetch_all(
            "SELECT * FROM subagent_tasks "
            "WHERE status IN ('completed', 'failed') AND delivered_at IS NULL"
        )

    async def mark_delivered(self, subagent_id: str) -> None:
        """Mark a subagent task as delivered to the parent conversation."""
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            "UPDATE subagent_tasks SET delivered_at = ? WHERE id = ?",
            (now, subagent_id),
        )
