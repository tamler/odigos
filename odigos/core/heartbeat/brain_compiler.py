"""Heartbeat Phase 3f: brain compilation trigger and lifecycle.

Checks if enough new content has accumulated since the last compilation.
If yes, dispatches a brain-compiler sub-agent. On the next cycle, checks
if the sub-agent completed and applies the manifest to disk.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.core.heartbeat.orchestrator import Heartbeat

logger = logging.getLogger(__name__)

MEMORY_THRESHOLD = 10
ENTITY_THRESHOLD = 5
FALLBACK_HOURS = 24
MAX_MEMORIES_IN_CONTEXT = 50
MAX_CONTEXT_CHARS = 6000
BRAIN_DIR = "data/brain"


async def should_compile(db) -> bool:
    """Check if brain compilation should be triggered."""
    # Check for pending task
    pending = await db.fetch_one(
        "SELECT value FROM kv WHERE key = 'brain_compile_task'"
    )
    if pending and pending["value"]:
        return False

    last_compiled = await db.fetch_one(
        "SELECT value FROM kv WHERE key = 'brain_last_compiled'"
    )
    last_ts = last_compiled["value"] if last_compiled else None

    # First compile: need at least 1 entity
    if not last_ts:
        entity_count = await db.fetch_one(
            "SELECT COUNT(*) as c FROM entities WHERE status = 'active'"
        )
        return (entity_count["c"] if entity_count else 0) > 0

    # Count new memories since last compile
    mem_count = await db.fetch_one(
        "SELECT COUNT(*) as c FROM memories WHERE created_at > ? AND status = 'active'",
        (last_ts,),
    )
    new_memories = mem_count["c"] if mem_count else 0

    # Count new/updated entities since last compile
    ent_count = await db.fetch_one(
        "SELECT COUNT(*) as c FROM entities WHERE updated_at > ?",
        (last_ts,),
    )
    new_entities = ent_count["c"] if ent_count else 0

    if new_memories >= MEMORY_THRESHOLD or new_entities >= ENTITY_THRESHOLD:
        return True

    # 24h fallback
    try:
        compiled_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        if compiled_dt.tzinfo is None:
            compiled_dt = compiled_dt.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - compiled_dt).total_seconds() / 3600
        if age_hours >= FALLBACK_HOURS and new_memories >= 1:
            return True
    except (ValueError, AttributeError):
        pass

    return False


async def build_compilation_context(db, brain_dir: str = BRAIN_DIR) -> dict:
    """Build the input context for the brain-compiler sub-agent.

    Returns a dict with keys: current_articles, new_memories, new_entities,
    existing_slugs, current_index.
    """
    brain = Path(brain_dir)
    last_compiled = await db.fetch_one(
        "SELECT value FROM kv WHERE key = 'brain_last_compiled'"
    )
    last_ts = last_compiled["value"] if last_compiled else "1970-01-01T00:00:00Z"

    # Current brain article summaries
    current_articles: list[str] = []
    for subdir in ["entities", "concepts"]:
        path = brain / subdir
        if not path.exists():
            continue
        for f in sorted(path.glob("*.md")):
            first_line = f.read_text(encoding="utf-8").split("\n")[0][:100]
            current_articles.append(f"{subdir}/{f.name}: {first_line}")

    # Existing slugs (all filenames without extension)
    existing_slugs: list[str] = []
    for subdir in ["entities", "concepts", "archive/entities", "archive/concepts"]:
        path = brain / subdir
        if not path.exists():
            continue
        for f in path.glob("*.md"):
            existing_slugs.append(f.stem)

    # New memories — prioritize high-confidence, fact/preference types first
    rows = await db.fetch_all(
        "SELECT id, content, memory_type, keywords_json, context_description, "
        "confidence, status, superseded_by "
        "FROM memories WHERE created_at > ? AND status = 'active' "
        "ORDER BY "
        "  CASE WHEN memory_type IN ('fact', 'preference') THEN 0 ELSE 1 END, "
        "  confidence DESC "
        "LIMIT ?",
        (last_ts, MAX_MEMORIES_IN_CONTEXT),
    )
    new_memories: list[dict] = []
    total_chars = 0
    for row in rows:
        content = (row["context_description"] or row["content"] or "")
        # Truncate general/summary to 100 chars
        if row["memory_type"] in ("general", "summary"):
            content = content[:100]
        else:
            content = content[:200]
        if total_chars + len(content) > MAX_CONTEXT_CHARS:
            break
        new_memories.append({
            "id": row["id"],
            "type": row["memory_type"],
            "content": content,
            "keywords": row["keywords_json"] or "[]",
            "confidence": row["confidence"],
            "status": row["status"],
            "superseded_by": row["superseded_by"],
        })
        total_chars += len(content)

    # New/updated entities
    ent_rows = await db.fetch_all(
        "SELECT id, name, type, summary FROM entities WHERE updated_at > ? LIMIT 20",
        (last_ts,),
    )
    new_entities = [
        {"id": r["id"], "name": r["name"], "type": r["type"],
         "summary": (r["summary"] or "")[:200]}
        for r in ent_rows
    ]

    # Current index
    index_path = brain / "index.md"
    current_index = ""
    if index_path.exists():
        current_index = index_path.read_text(encoding="utf-8")[:2000]

    return {
        "current_articles": current_articles,
        "new_memories": new_memories,
        "new_entities": new_entities,
        "existing_slugs": existing_slugs,
        "current_index": current_index,
    }


async def dispatch_compilation(hb: "Heartbeat") -> str | None:
    """Dispatch the brain-compiler sub-agent.

    Returns the task_id if dispatched, None otherwise.
    """
    if not getattr(hb, "subagent_manager", None):
        return None

    context = await build_compilation_context(hb.db, brain_dir=BRAIN_DIR)

    # Format as the sub-agent's input
    input_text = json.dumps(context, indent=2, default=str)

    task_description = (
        f"Compile the brain wiki. "
        f"{len(context['new_memories'])} new memories, "
        f"{len(context['new_entities'])} new/updated entities, "
        f"{len(context['existing_slugs'])} existing slugs."
    )

    try:
        result = await hb.subagent_manager.dispatch(
            task=task_description,
            persona="brain-compiler",
            input_artifact=input_text,
            concurrency_key="heavy",
        )
        # Store task_id for polling
        await hb.db.execute(
            "INSERT OR REPLACE INTO kv (key, value) VALUES ('brain_compile_task', ?)",
            (result.task_id,),
        )
        logger.info("Brain compilation dispatched: task=%s", result.task_id[:8])
        return result.task_id
    except Exception:
        logger.warning("Brain compilation dispatch failed", exc_info=True)
        return None


async def check_compilation(hb: "Heartbeat") -> bool:
    """Check if a pending brain compilation has completed and apply the result.

    Returns True if a compilation was applied.
    """
    row = await hb.db.fetch_one(
        "SELECT value FROM kv WHERE key = 'brain_compile_task'"
    )
    if not row or not row["value"]:
        return False

    task_id = row["value"]
    task_row = await hb.db.fetch_one(
        "SELECT status, result_json, error FROM tasks WHERE id = ?",
        (task_id,),
    )

    if not task_row:
        # Task disappeared — clear the kv
        await hb.db.execute("DELETE FROM kv WHERE key = 'brain_compile_task'")
        return False

    if task_row["status"] == "done":
        from odigos.core.brain_apply import apply_compilation

        result_json = task_row["result_json"] or "{}"
        # Extract the result text from the sub-agent wrapper
        try:
            result_obj = json.loads(result_json)
            manifest = result_obj.get("result", result_json)
        except (json.JSONDecodeError, TypeError):
            manifest = result_json

        stats = await apply_compilation(manifest, brain_dir=BRAIN_DIR)

        # Update last_compiled timestamp
        now = datetime.now(timezone.utc).isoformat()
        await hb.db.execute(
            "INSERT OR REPLACE INTO kv (key, value) VALUES ('brain_last_compiled', ?)",
            (now,),
        )

        # Clear the pending task
        await hb.db.execute("DELETE FROM kv WHERE key = 'brain_compile_task'")

        # Notification
        summary = stats.get("summary", "Brain compiled.")
        try:
            if hasattr(hb, "notifier") and hb.notifier:
                await hb.notifier.create(
                    type="status",
                    title="Brain compiled",
                    body=f"{summary} (created: {stats['created']}, updated: {stats['updated']}, archived: {stats['archived']})",
                )
        except Exception:
            logger.debug("Notification failed", exc_info=True)

        logger.info(
            "Brain compilation applied: created=%d, updated=%d, archived=%d, errors=%d",
            stats["created"], stats["updated"], stats["archived"], len(stats.get("errors", [])),
        )
        return True

    elif task_row["status"] == "failed":
        await hb.db.execute("DELETE FROM kv WHERE key = 'brain_compile_task'")
        logger.warning("Brain compilation failed: %s", task_row.get("error", "unknown"))
        return False

    # Still running — do nothing
    return False
