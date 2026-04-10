"""SubagentManager: orchestrates specialist sub-agent LLM execution.

Sub-agents are stateless, task-focused LLM calls with their own persona,
tool whitelist, model, and isolated context. The orchestrator dispatches
them for specialized work and delivers results with its own voice.

This module unifies the legacy per-conversation spawn model with the new
persona-based async dispatch. All sub-agent work now flows through
`SubagentManager.dispatch()` which writes to the `tasks` table with
type='subagent'. The heartbeat worker polls pending tasks and calls
`SubagentManager.execute_task()` to run them.

The legacy `spawn()` / `get_completed_all()` / `mark_delivered()` methods
are preserved as thin wrappers for the peer messaging subsystem.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from odigos.db import Database
from odigos.providers.base import LLMProvider
from odigos.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from odigos.core.trace import Tracer
    from odigos.memory.recall import MemoryRecall
    from odigos.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 600
MIN_ARTIFACT_SIZE_CHARS = 500


@dataclass
class SubagentPersona:
    """A sub-agent persona definition loaded from data/subagents/."""
    name: str
    description: str
    model: str = "default"
    tools: list[str] = field(default_factory=list)
    max_runtime_seconds: int = DEFAULT_TIMEOUT_SECONDS
    skill: str | None = None
    tools_override: bool = False
    workspace_roots: list[str] = field(default_factory=list)
    system_prompt: str = ""


@dataclass
class SubagentDispatchResult:
    """Result of SubagentManager.dispatch()."""
    task_id: str
    status: str  # 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
    result: str | None = None
    artifact_path: str | None = None
    error: str | None = None
    duration_ms: int | None = None
    cost_usd: float | None = None


# Module-level persona cache: name → (persona, mtime)
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
        max_runtime_seconds=int(
            frontmatter_dict.get("max_runtime_seconds", DEFAULT_TIMEOUT_SECONDS)
        ),
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
    seen: set[str] = set()
    result: list[str] = []
    for t in list(persona_tools) + list(skill_tools):
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


def build_scoped_system_prompt(
    *,
    persona: SubagentPersona | None,
    skill: Any | None,
    explicit_system_prompt: str | None,
    context_facts: list[str],
    input_artifact: str | None,
    workspace_root: str | None,
) -> str:
    """Construct the sub-agent's system prompt by layering:
    skill → persona → explicit prompt → context facts → input artifact → workspace → output framing.
    """
    parts: list[str] = []

    if skill is not None and getattr(skill, "system_prompt", None):
        parts.append(str(skill.system_prompt))

    if persona is not None and persona.system_prompt:
        parts.append(persona.system_prompt)

    if explicit_system_prompt:
        parts.append(explicit_system_prompt)

    if not parts:
        parts.append("You are a specialist sub-agent. Produce the task output directly.")

    if context_facts:
        facts_block = "\n".join(f"- {f}" for f in context_facts)
        parts.append(f"\n## User context\n{facts_block}")

    if input_artifact:
        parts.append(f"\n## Current state (input artifact)\n{input_artifact}")

    if workspace_root:
        parts.append(
            f"\n## Workspace\nYou may only read and write files under: {workspace_root}\n"
            f"Do not attempt to access any path outside this directory."
        )

    parts.append(
        "\n## Output\nProduce the direct task output. Do not add conversational "
        "framing — the orchestrator will deliver your output to the user with "
        "its own voice."
    )

    return "\n\n".join(parts)


# Sub-agent orchestration tool names that must NOT be in a sub-agent's
# whitelist. These would allow recursive spawning.
_RECURSION_BLOCKED_TOOLS: set[str] = {
    "run_subagent",
    "run_parallel_subagents",
    "subagent_status",
    "cancel_subagent",
    "spawn_subagent",  # legacy name
}


class SubagentManager:
    """Unified sub-agent lifecycle manager.

    Responsibilities:
    - Dispatch: create pending sub-agent tasks (`dispatch()`, `spawn()`)
    - Execute: run a single task with scoped executor (`execute_task()`)
    - Deliver: surface completed results for consumption (`get_completed_all()`, `mark_delivered()`)
    - Chain: handle `on_complete` and `on_failure` follow-ups
    - Persona/tool resolution: load and validate personas, compose scoped system prompts
    """

    def __init__(
        self,
        db: Database,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
        personas_dir: str = "data/subagents",
        memory_recall: "MemoryRecall | None" = None,
        skill_registry: "SkillRegistry | None" = None,
        tracer: "Tracer | None" = None,
    ) -> None:
        self.db = db
        self.llm_provider = llm_provider
        self.tool_registry = tool_registry
        self.personas_dir = personas_dir
        self.memory_recall = memory_recall
        self.skill_registry = skill_registry
        self.tracer = tracer

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        task: str,
        *,
        persona: str | None = None,
        skill: str | None = None,
        system_prompt: str | None = None,
        tools: list[str] | None = None,
        model: str | None = None,
        context_facts: list[str] | None = None,
        memory_refs: list[str] | None = None,
        input_artifact: str | None = None,
        workspace_root: str | None = None,
        timeout_seconds: int | None = None,
        on_complete: dict | None = None,
        on_failure: dict | None = None,
        concurrency_key: str | None = None,
        max_retries: int = 2,
        conversation_id: str | None = None,
    ) -> SubagentDispatchResult:
        """Dispatch a sub-agent task asynchronously.

        Creates a pending row in the `tasks` table and returns the task_id.
        The heartbeat worker picks it up on the next cycle and executes it
        via `execute_task()`.
        """
        if not persona and not skill and not system_prompt:
            raise ValueError(
                "dispatch requires at least one of: persona, skill, system_prompt"
            )

        if persona:
            loaded = self.load_persona(persona)
            if loaded is None:
                raise ValueError(f"Unknown persona: {persona}")

        params: dict = {
            "task": task,
            "persona": persona,
            "skill": skill,
            "system_prompt": system_prompt,
            "tools": tools,
            "model": model,
            "context_facts": context_facts,
            "memory_refs": memory_refs,
            "input_artifact": input_artifact,
            "workspace_root": workspace_root,
            "timeout_seconds": timeout_seconds,
            "on_complete": on_complete,
            "on_failure": on_failure,
            "conversation_id": conversation_id,
        }

        task_id = str(uuid.uuid4())
        resolved_concurrency = concurrency_key or "default"
        max_runtime = timeout_seconds or DEFAULT_TIMEOUT_SECONDS
        if persona:
            loaded_persona = self.load_persona(persona)
            if loaded_persona:
                max_runtime = timeout_seconds or loaded_persona.max_runtime_seconds

        await self.db.execute(
            "INSERT INTO tasks "
            "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
            "cancel_requested, max_retries, arguments_json, conversation_id, description) "
            "VALUES (?, 'subagent', 'pending', ?, ?, ?, 0, ?, ?, ?, ?)",
            (
                task_id,
                persona,
                resolved_concurrency,
                max_runtime,
                max_retries,
                json.dumps(params),
                conversation_id,
                task[:500],
            ),
        )

        return SubagentDispatchResult(task_id=task_id, status="pending")

    async def spawn(
        self,
        instruction: str,
        parent_conversation_id: str,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> str:
        """Legacy spawn API used by peer messaging.

        Thin wrapper around dispatch() that matches the old signature so
        `odigos/core/heartbeat/peers.py` keeps working without changes.
        Returns the task_id (referred to as subagent_id in peer code).
        """
        result = await self.dispatch(
            task=instruction,
            timeout_seconds=timeout,
            conversation_id=parent_conversation_id,
            concurrency_key="default",
        )
        return result.task_id

    # ------------------------------------------------------------------
    # Delivery (peer compatibility layer)
    # ------------------------------------------------------------------

    async def get_completed_all(self) -> list[dict]:
        """Return completed/failed sub-agent tasks not yet delivered.

        Returns dicts with the legacy field names peers.py expects:
        `id`, `instruction`, `status`, `result`, `parent_conversation_id`.
        """
        rows = await self.db.fetch_all(
            "SELECT id, status, result_json, arguments_json, conversation_id "
            "FROM tasks "
            "WHERE type = 'subagent' "
            "AND status IN ('done', 'failed') "
            "AND delivered_at IS NULL"
        )
        output: list[dict] = []
        for row in rows:
            try:
                params = json.loads(row["arguments_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                params = {}
            try:
                result_obj = json.loads(row["result_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                result_obj = {}
            output.append({
                "id": row["id"],
                "instruction": params.get("task", ""),
                "status": row["status"],
                "result": result_obj.get("result", "") or row.get("result_json") or "",
                "parent_conversation_id": row["conversation_id"] or "",
            })
        return output

    async def mark_delivered(self, task_id: str) -> None:
        """Mark a sub-agent task as delivered to its parent conversation."""
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            "UPDATE tasks SET delivered_at = ? WHERE id = ?",
            (now, task_id),
        )

    # ------------------------------------------------------------------
    # Execution (called by heartbeat worker)
    # ------------------------------------------------------------------

    async def execute_task(self, task_row: dict) -> None:
        """Execute a single pending sub-agent task.

        Called by the heartbeat worker after gating. Reads the task's
        `arguments_json`, dispatches the LLM call, stores the result,
        creates the notification, and handles on_complete/on_failure.
        """
        task_id = task_row["id"]
        start = datetime.now(timezone.utc)

        try:
            params = json.loads(task_row["arguments_json"] or "{}")
            max_runtime = task_row.get("max_runtime_seconds") or DEFAULT_TIMEOUT_SECONDS
            workspace_root = params.get("workspace_root") or f"data/subagent_workspace/{task_id}"

            Path(workspace_root).mkdir(parents=True, exist_ok=True)

            result = await asyncio.wait_for(
                self._run_inline(params, task_id, workspace_root),
                timeout=max_runtime,
            )

            await self.db.execute(
                "UPDATE tasks SET status = 'done', result_json = ?, "
                "completed_at = ?, duration_ms = ?, cost_usd = ?, "
                "artifact_path = ? WHERE id = ?",
                (
                    json.dumps({"result": result.get("result", "")}),
                    datetime.now(timezone.utc).isoformat(),
                    result.get("duration_ms", 0),
                    result.get("cost_usd", 0.0),
                    result.get("artifact_path"),
                    task_id,
                ),
            )

            if self.tracer:
                try:
                    await self.tracer.emit(
                        "subagent_completed",
                        task_row.get("conversation_id") or "heartbeat",
                        {"task_id": task_id, "persona": task_row.get("persona")},
                    )
                except Exception:
                    logger.debug("Failed to emit subagent trace", exc_info=True)

            if params.get("on_complete"):
                try:
                    await self._dispatch_chained(task_row, result, params["on_complete"])
                except Exception:
                    logger.debug("on_complete dispatch failed", exc_info=True)

        except asyncio.TimeoutError:
            await self.db.execute(
                "UPDATE tasks SET status = 'failed', error = 'timeout', "
                "completed_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), task_id),
            )
            await self._handle_failure(task_row, "timeout")
        except Exception as exc:
            logger.exception("Sub-agent task failed: %s", task_id[:8])
            await self.db.execute(
                "UPDATE tasks SET status = 'failed', error = ?, completed_at = ? WHERE id = ?",
                (str(exc)[:500], datetime.now(timezone.utc).isoformat(), task_id),
            )
            await self._handle_failure(task_row, str(exc))

    async def _run_inline(
        self,
        params: dict,
        task_id: str,
        workspace_root: str,
    ) -> dict:
        """Execute the sub-agent LLM call with scoped tools and context."""
        start = datetime.now(timezone.utc)

        persona_name = params.get("persona")
        skill_name = params.get("skill")
        explicit_tools = params.get("tools")
        explicit_system = params.get("system_prompt")
        model = params.get("model")
        context_facts = list(params.get("context_facts") or [])
        memory_refs = params.get("memory_refs") or []
        input_artifact = params.get("input_artifact")
        task_text = params.get("task", "")

        persona = self.load_persona(persona_name) if persona_name else None

        skill = None
        if skill_name and self.skill_registry:
            skill = self.skill_registry.get(skill_name)
        elif persona and persona.skill and self.skill_registry:
            skill = self.skill_registry.get(persona.skill)

        persona_tools = persona.tools if persona else []
        skill_tools = list(getattr(skill, "tools", []) or [])
        tools_override = persona.tools_override if persona else False
        resolved_tools = resolve_tools(
            persona_tools=persona_tools,
            skill_tools=skill_tools,
            explicit_tools=explicit_tools,
            tools_override=tools_override,
        )
        # Enforce recursion prevention: strip sub-agent orchestration tools
        resolved_tools = [t for t in resolved_tools if t not in _RECURSION_BLOCKED_TOOLS]

        if memory_refs and self.memory_recall:
            for ref in memory_refs:
                try:
                    results = await self.memory_recall.search(ref, limit=3)
                    for r in results:
                        content = getattr(r, "content_preview", None) or getattr(r, "content", "")
                        if content:
                            context_facts.append(content[:200])
                except Exception:
                    logger.debug("memory_refs resolution failed for %r", ref)

        system_prompt = build_scoped_system_prompt(
            persona=persona,
            skill=skill,
            explicit_system_prompt=explicit_system,
            context_facts=context_facts,
            input_artifact=input_artifact,
            workspace_root=workspace_root,
        )

        resolved_model = model or (persona.model if persona else "default")

        response = await self.llm_provider.complete(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task_text},
            ],
            temperature=0.5,
            max_tokens=4000,
            model=resolved_model,
        )

        result_text = response.content or ""
        duration_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        cost = getattr(response, "cost_usd", 0.0) or 0.0

        artifact_path: str | None = None
        if len(result_text) > MIN_ARTIFACT_SIZE_CHARS:
            try:
                artifacts_dir = Path("data/artifacts")
                artifacts_dir.mkdir(parents=True, exist_ok=True)
                artifact_path = str(artifacts_dir / f"subagent-{task_id}.md")
                Path(artifact_path).write_text(result_text)
            except Exception:
                logger.debug("artifact write failed", exc_info=True)
                artifact_path = None

        return {
            "result": result_text,
            "artifact_path": artifact_path,
            "duration_ms": duration_ms,
            "cost_usd": cost,
            "tool_calls": [],
        }

    # ------------------------------------------------------------------
    # Chaining
    # ------------------------------------------------------------------

    async def _dispatch_chained(
        self,
        parent_row: dict,
        result: dict,
        on_complete: dict,
    ) -> None:
        """Dispatch an on_complete follow-up sub-agent."""
        input_from = on_complete.get("input_from", "result")
        if input_from == "result":
            input_artifact = result.get("result", "")
        elif input_from == "artifact":
            input_artifact = result.get("artifact_path", "")
        else:
            input_artifact = ""

        chained_params = {
            "task": on_complete.get("task", ""),
            "persona": on_complete.get("persona"),
            "tools": on_complete.get("tools"),
            "model": on_complete.get("model"),
            "input_artifact": input_artifact,
            "on_complete": on_complete.get("on_complete"),
            "on_failure": on_complete.get("on_failure"),
        }

        chained_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO tasks "
            "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
            "arguments_json, parent_task_id, max_retries, retry_count, description) "
            "VALUES (?, 'subagent', 'pending', ?, ?, ?, ?, ?, 2, 0, ?)",
            (
                chained_id,
                on_complete.get("persona"),
                parent_row.get("concurrency_key") or "default",
                on_complete.get("max_runtime_seconds", DEFAULT_TIMEOUT_SECONDS),
                json.dumps(chained_params),
                parent_row["id"],
                (on_complete.get("task") or "")[:500],
            ),
        )
        logger.info(
            "Sub-agent chain: dispatched %s (parent=%s)",
            chained_id[:8],
            parent_row["id"][:8],
        )

    async def _handle_failure(self, task_row: dict, error: str) -> None:
        """If the task has an on_failure handler, dispatch it."""
        try:
            params = json.loads(task_row.get("arguments_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            return
        on_failure = params.get("on_failure")
        if not on_failure:
            return

        handler_params = {
            "task": on_failure.get("task", "Explain the previous failure"),
            "persona": on_failure.get("persona"),
            "context_facts": [
                f"Original task: {params.get('task', '')[:300]}",
                f"Error: {error[:300]}",
            ],
        }

        handler_id = str(uuid.uuid4())
        try:
            await self.db.execute(
                "INSERT INTO tasks "
                "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
                "arguments_json, parent_task_id, max_retries, retry_count, description) "
                "VALUES (?, 'subagent', 'pending', ?, ?, ?, ?, ?, 1, 0, ?)",
                (
                    handler_id,
                    on_failure.get("persona"),
                    task_row.get("concurrency_key") or "default",
                    on_failure.get("max_runtime_seconds", 300),
                    json.dumps(handler_params),
                    task_row["id"],
                    (on_failure.get("task") or "failure recovery")[:500],
                ),
            )
            logger.info(
                "Sub-agent on_failure: dispatched %s (parent=%s)",
                handler_id[:8],
                task_row["id"][:8],
            )
        except Exception:
            logger.debug("on_failure insert failed", exc_info=True)

    # ------------------------------------------------------------------
    # Persona helpers (instance methods delegating to module functions)
    # ------------------------------------------------------------------

    def load_persona(self, name: str) -> SubagentPersona | None:
        """Load a persona by name from this manager's personas_dir."""
        return load_persona(name, personas_dir=self.personas_dir)

    def validate_persona(self, persona: SubagentPersona) -> list[str]:
        """Validate a persona against this manager's tool registry."""
        known = {tool.name for tool in self.tool_registry.list()}
        return validate_persona(persona, known)


# ---------------------------------------------------------------------------
# Backward-compat top-level function used by orchestration tools during
# migration. Prefer SubagentManager.dispatch() for new code.
# ---------------------------------------------------------------------------

async def run_subagent(
    task: str,
    *,
    persona: str | None = None,
    skill: str | None = None,
    system_prompt: str | None = None,
    tools: list[str] | None = None,
    model: str | None = None,
    context_facts: list[str] | None = None,
    memory_refs: list[str] | None = None,
    input_artifact: str | None = None,
    workspace_root: str | None = None,
    wait_for_result: bool = False,
    timeout_seconds: int | None = None,
    on_complete: dict | None = None,
    on_failure: dict | None = None,
    concurrency_key: str | None = None,
    max_retries: int = 2,
    conversation_id: str | None = None,
    db=None,
    personas_dir: str = "data/subagents",
) -> SubagentDispatchResult:
    """Legacy top-level dispatch function.

    Kept for tests and transitional code that calls `run_subagent()` directly.
    New code should use `SubagentManager.dispatch()` instead.

    This function creates a throwaway manager with just the DB — no LLM,
    no tool registry. It only supports the dispatch (pending row creation)
    path, not the execute path.
    """
    if db is None:
        raise ValueError("db is required")

    if not persona and not skill and not system_prompt:
        raise ValueError(
            "run_subagent requires at least one of: persona, skill, system_prompt"
        )

    if persona:
        loaded = load_persona(persona, personas_dir=personas_dir)
        if loaded is None:
            raise ValueError(f"Unknown persona: {persona}")

    params: dict = {
        "task": task,
        "persona": persona,
        "skill": skill,
        "system_prompt": system_prompt,
        "tools": tools,
        "model": model,
        "context_facts": context_facts,
        "memory_refs": memory_refs,
        "input_artifact": input_artifact,
        "workspace_root": workspace_root,
        "timeout_seconds": timeout_seconds,
        "on_complete": on_complete,
        "on_failure": on_failure,
        "conversation_id": conversation_id,
    }

    task_id = str(uuid.uuid4())
    resolved_concurrency = concurrency_key or "default"
    max_runtime = timeout_seconds or DEFAULT_TIMEOUT_SECONDS
    if persona:
        loaded_persona = load_persona(persona, personas_dir=personas_dir)
        if loaded_persona:
            max_runtime = timeout_seconds or loaded_persona.max_runtime_seconds

    await db.execute(
        "INSERT INTO tasks "
        "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
        "cancel_requested, max_retries, arguments_json, conversation_id, description) "
        "VALUES (?, 'subagent', 'pending', ?, ?, ?, 0, ?, ?, ?, ?)",
        (
            task_id, persona, resolved_concurrency, max_runtime,
            max_retries, json.dumps(params), conversation_id, task[:500],
        ),
    )

    return SubagentDispatchResult(task_id=task_id, status="pending")
