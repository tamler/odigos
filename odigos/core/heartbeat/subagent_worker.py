"""Heartbeat Phase 3d: poll and execute sub-agent tasks."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Concurrency pools — tasks with the same key share a slot
CONCURRENCY_POOLS: dict[str, int] = {
    "default": 3,
    "research": 2,
    "fast": 5,
    "heavy": 1,
}

SUBAGENT_POLL_LIMIT = 5  # max pending tasks checked per heartbeat cycle

# Module-level task registry for cancellation
_running_tasks: dict[str, asyncio.Task] = {}


async def poll_subagent_tasks(hb) -> int:
    """Phase 3d: poll and start pending sub-agent tasks.

    Returns the number of tasks started in this cycle.
    """
    # Budget gating
    try:
        within_budget = await hb.budget_tracker.is_within_budget()
        if not within_budget:
            logger.debug("Sub-agent worker: budget exceeded, skipping")
            return 0
    except Exception:
        logger.debug("Budget check failed, assuming within budget", exc_info=True)

    # Get running task counts per concurrency pool
    running_rows = await hb.db.fetch_all(
        "SELECT concurrency_key, COUNT(*) as c FROM tasks "
        "WHERE type = 'subagent' AND status = 'running' "
        "GROUP BY concurrency_key",
    )
    running_counts: dict[str, int] = {
        r["concurrency_key"] or "default": r["c"] for r in running_rows
    }

    # Fetch pending tasks
    pending = await hb.db.fetch_all(
        "SELECT * FROM tasks WHERE type = 'subagent' AND status = 'pending' "
        "AND cancel_requested = 0 ORDER BY created_at ASC LIMIT ?",
        (SUBAGENT_POLL_LIMIT,),
    )

    if not pending:
        return 0

    started = 0
    for task_row in pending:
        key = task_row["concurrency_key"] or "default"
        limit = CONCURRENCY_POOLS.get(key, 3)
        current = running_counts.get(key, 0)
        if current >= limit:
            continue

        # Mark as running
        await hb.db.execute(
            "UPDATE tasks SET status = 'running', started_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), task_row["id"]),
        )
        running_counts[key] = current + 1

        # Launch the execution asynchronously
        task = asyncio.create_task(_execute_subagent_task(hb, dict(task_row)))
        _running_tasks[task_row["id"]] = task
        started += 1

    if started > 0:
        logger.info("Sub-agent worker: started %d task(s)", started)
    return started


async def recover_orphaned_tasks(hb) -> int:
    """Mark tasks that have been running past their timeout as failed.

    Called on heartbeat startup to recover from crashes.
    """
    rows = await hb.db.fetch_all(
        "SELECT id, started_at, max_runtime_seconds FROM tasks "
        "WHERE type = 'subagent' AND status = 'running'",
    )
    recovered = 0
    now = datetime.now(timezone.utc)
    for row in rows:
        if not row["started_at"]:
            continue
        try:
            started = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            continue

        age = (now - started).total_seconds()
        limit = (row["max_runtime_seconds"] or 600) + 60  # grace period
        if age > limit:
            await hb.db.execute(
                "UPDATE tasks SET status = 'failed', "
                "error = 'interrupted (process restart)' WHERE id = ?",
                (row["id"],),
            )
            recovered += 1

    if recovered > 0:
        logger.info("Sub-agent worker: recovered %d orphaned task(s)", recovered)
    return recovered


async def _execute_subagent_task(hb, task_row: dict) -> None:
    """Execute a single sub-agent task. Called via asyncio.create_task."""
    task_id = task_row["id"]

    try:
        params = json.loads(task_row["arguments_json"] or "{}")
        max_runtime = task_row.get("max_runtime_seconds") or 600
        workspace_root = params.get("workspace_root") or f"data/subagent_workspace/{task_id}"

        # Create workspace directory
        from pathlib import Path as _Path
        _Path(workspace_root).mkdir(parents=True, exist_ok=True)

        # Run the execution inline with timeout
        result = await asyncio.wait_for(
            _execute_subagent_inline(hb, params, task_id, workspace_root),
            timeout=max_runtime,
        )

        # Store result
        await hb.db.execute(
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

        # Publish completion event
        try:
            await hb.message_bus.publish({
                "type": "subagent_complete",
                "task_id": task_id,
                "persona": task_row.get("persona"),
                "artifact_path": result.get("artifact_path"),
            })
        except Exception:
            logger.debug("message_bus publish failed", exc_info=True)

        # Create notification
        try:
            preview = (result.get("result") or "")[:200]
            persona_name = task_row.get("persona") or "sub-agent"
            await hb.notifier.create(
                type="suggestion",
                title=f"Sub-agent task complete: {persona_name}",
                body=preview,
                metadata={
                    "task_id": task_id,
                    "artifact_path": result.get("artifact_path"),
                    "parent_task_id": task_row.get("parent_task_id"),
                },
            )
        except Exception:
            logger.debug("notifier.create failed", exc_info=True)

        # Handle on_complete chaining (added in Task 7)
        if params.get("on_complete"):
            await _dispatch_chained_subagent(hb, task_row, result, params["on_complete"])

    except asyncio.TimeoutError:
        await hb.db.execute(
            "UPDATE tasks SET status = 'failed', error = 'timeout', "
            "completed_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), task_id),
        )
    except Exception as exc:
        logger.exception("Sub-agent task failed: %s", task_id[:8])
        await hb.db.execute(
            "UPDATE tasks SET status = 'failed', error = ?, completed_at = ? WHERE id = ?",
            (str(exc)[:500], datetime.now(timezone.utc).isoformat(), task_id),
        )
        # on_failure handler
        try:
            params = json.loads(task_row["arguments_json"] or "{}")
            if params.get("on_failure"):
                await _dispatch_failure_handler(hb, task_row, str(exc), params["on_failure"])
        except Exception:
            logger.debug("on_failure dispatch failed", exc_info=True)
    finally:
        _running_tasks.pop(task_id, None)


async def _execute_subagent_inline(hb, params: dict, task_id: str, workspace_root: str) -> dict:
    """Execute the sub-agent LLM call with scoped tools and context.

    Returns a dict with keys: result, artifact_path, duration_ms, cost_usd, tool_calls.
    """
    from odigos.core.subagent import (
        load_persona, resolve_tools, build_scoped_system_prompt,
    )

    start = datetime.now(timezone.utc)

    persona_name = params.get("persona")
    skill_name = params.get("skill")
    explicit_tools = params.get("tools")
    explicit_system = params.get("system_prompt")
    model = params.get("model")
    context_facts = params.get("context_facts") or []
    memory_refs = params.get("memory_refs") or []
    input_artifact = params.get("input_artifact")
    task_text = params.get("task", "")

    persona = load_persona(persona_name) if persona_name else None

    # Resolve skill
    skill = None
    if skill_name and hasattr(hb, "skill_registry"):
        skill = hb.skill_registry.get(skill_name)
    elif persona and persona.skill and hasattr(hb, "skill_registry"):
        skill = hb.skill_registry.get(persona.skill)

    # Resolve tools
    persona_tools = persona.tools if persona else []
    skill_tools = (skill.tools if skill else []) or []
    tools_override = persona.tools_override if persona else False
    resolve_tools(
        persona_tools=persona_tools,
        skill_tools=skill_tools,
        explicit_tools=explicit_tools,
        tools_override=tools_override,
    )

    # Resolve model
    resolved_model = model or (persona.model if persona else "default")

    # Resolve memory_refs at execution time
    resolved_facts = list(context_facts)
    if memory_refs and hasattr(hb, "memory_recall") and hb.memory_recall:
        for ref in memory_refs:
            try:
                results = await hb.memory_recall.search(ref, limit=3)
                for r in results:
                    resolved_facts.append(r.content_preview or r.content[:200])
            except Exception:
                logger.debug("memory_refs resolution failed for %r", ref)

    # Build system prompt
    system_prompt = build_scoped_system_prompt(
        persona=persona,
        skill=skill,
        explicit_system_prompt=explicit_system,
        context_facts=resolved_facts,
        input_artifact=input_artifact,
        workspace_root=workspace_root,
    )

    # Run LLM call
    response = await hb.llm_provider.complete(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_text},
        ],
        temperature=0.5,
        max_tokens=4000,
        model=resolved_model if resolved_model != "default" else hb.background_model,
    )

    result_text = response.content or ""
    duration_ms = int(
        (datetime.now(timezone.utc) - start).total_seconds() * 1000
    )
    cost = getattr(response, "cost_usd", 0.0) or 0.0

    # Optional artifact write
    artifact_path: str | None = None
    if len(result_text) > 500:
        try:
            from pathlib import Path as _Path
            artifacts_dir = _Path("data/artifacts")
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = str(artifacts_dir / f"subagent-{task_id}.md")
            _Path(artifact_path).write_text(result_text)
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


async def _dispatch_chained_subagent(hb, parent_row: dict, result: dict, on_complete: dict) -> None:
    """Create a follow-up sub-agent task using the parent's result as input."""
    import uuid as _uuid

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
        "on_complete": on_complete.get("on_complete"),  # nested chain support
        "on_failure": on_complete.get("on_failure"),
    }

    chained_id = str(_uuid.uuid4())
    await hb.db.execute(
        "INSERT INTO tasks "
        "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
        "arguments_json, parent_task_id, max_retries, retry_count) "
        "VALUES (?, 'subagent', 'pending', ?, ?, ?, ?, ?, 2, 0)",
        (
            chained_id,
            on_complete.get("persona"),
            parent_row.get("concurrency_key") or "default",
            on_complete.get("max_runtime_seconds", 600),
            json.dumps(chained_params),
            parent_row["id"],
        ),
    )
    logger.info(
        "Sub-agent chain: dispatched %s (parent=%s)",
        chained_id[:8], parent_row["id"][:8],
    )


async def _dispatch_failure_handler(hb, parent_row: dict, error: str, on_failure: dict) -> None:
    """Create a recovery sub-agent task when the parent failed."""
    import uuid as _uuid

    handler_params = {
        "task": on_failure.get("task", "Explain the previous failure"),
        "persona": on_failure.get("persona"),
        "context_facts": [
            f"Original task: {json.loads(parent_row['arguments_json']).get('task', '')}",
            f"Error: {error[:300]}",
        ],
    }

    handler_id = str(_uuid.uuid4())
    await hb.db.execute(
        "INSERT INTO tasks "
        "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
        "arguments_json, parent_task_id, max_retries, retry_count) "
        "VALUES (?, 'subagent', 'pending', ?, ?, ?, ?, ?, 1, 0)",
        (
            handler_id,
            on_failure.get("persona"),
            parent_row.get("concurrency_key") or "default",
            on_failure.get("max_runtime_seconds", 300),
            json.dumps(handler_params),
            parent_row["id"],
        ),
    )
    logger.info(
        "Sub-agent on_failure: dispatched %s (parent=%s)",
        handler_id[:8], parent_row["id"][:8],
    )
