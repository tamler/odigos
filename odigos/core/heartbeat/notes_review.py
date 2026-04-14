"""Heartbeat phase: review shared notebooks and add anchored observations."""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.core.heartbeat.orchestrator import Heartbeat

logger = logging.getLogger(__name__)

REVIEW_INTERVAL_HOURS = 24
MAX_NOTEBOOKS_PER_CYCLE = 1
MIN_CONTENT_CHARS = 500
MAX_ACTIVE_NOTES_PER_NOTEBOOK = 10
MAX_REVIEW_CONTENT_CHARS = 8000


async def review_notebooks(hb: "Heartbeat") -> int:
    """Review the oldest stale shared notebook. Returns 0 or 1."""
    try:
        notebook = await _pick_notebook(hb.db)
        if not notebook:
            return 0

        nb_id = notebook["id"]
        nb_title = notebook["title"]

        user_content = await _load_user_content(hb.db, nb_id)
        if len(user_content) < MIN_CONTENT_CHARS:
            logger.debug("Skipping review: notebook %s content too short", nb_id[:8])
            return 0

        existing_notes = await _load_existing_agent_notes(hb.db, nb_id)
        active_notes = [n for n in existing_notes if n.get("status") == "active"]
        if len(active_notes) >= MAX_ACTIVE_NOTES_PER_NOTEBOOK:
            logger.debug("Skipping review: notebook %s has %d active notes", nb_id[:8], len(active_notes))
            return 0

        # Mark stale quotes before adding new notes
        await _mark_stale_quotes(hb.db, active_notes, user_content)

        # Truncate content window
        if len(user_content) > MAX_REVIEW_CONTENT_CHARS:
            user_content = user_content[-MAX_REVIEW_CONTENT_CHARS:]
            logger.debug("Truncated review content for notebook %s", nb_id[:8])

        # Build review prompt
        prompt = await _build_review_prompt(user_content, active_notes)

        response = await hb.llm_provider.complete(
            messages=[{"role": "system", "content": prompt}],
            temperature=0.4,
            max_tokens=1500,
            intelligence="background",
        )

        parsed = _parse_observations(response.content)
        observations = parsed.get("observations", [])

        # Insert valid observations
        inserted_ids = []
        for obs in observations:
            quote = obs.get("quote", "").strip()
            comment = obs.get("comment", "").strip()
            if not quote or not comment:
                continue
            if quote.lower() not in user_content.lower():
                logger.debug("Skipping hallucinated quote: %r", quote[:60])
                continue

            entry_id = str(uuid.uuid4())
            await hb.db.execute(
                "INSERT INTO notebook_entries "
                "(id, notebook_id, content, entry_type, status, quote, trigger_type, created_at, updated_at) "
                "VALUES (?, ?, ?, 'agent', 'active', ?, 'heartbeat', datetime('now'), datetime('now'))",
                (entry_id, nb_id, comment, quote),
            )
            inserted_ids.append(entry_id)

        # Update last_reviewed_at regardless of whether observations were found
        now_iso = datetime.now(timezone.utc).isoformat()
        await hb.db.execute(
            "UPDATE notebooks SET last_reviewed_at = ? WHERE id = ?",
            (now_iso, nb_id),
        )

        # Regenerate backup files
        if inserted_ids:
            try:
                from odigos.api.notebooks import _backup_to_disk
                await _backup_to_disk(hb.db, nb_id)
            except Exception:
                logger.debug("Backup after review failed", exc_info=True)

            # Publish WebSocket + notifications
            for entry_id in inserted_ids:
                try:
                    if hasattr(hb, "message_bus") and hb.message_bus:
                        await hb.message_bus.publish(
                            {"type": "note_added", "notebook_id": nb_id, "entry_id": entry_id},
                        )
                except Exception:
                    logger.debug("message_bus publish failed", exc_info=True)

                try:
                    if hasattr(hb, "notifier") and hb.notifier:
                        await hb.notifier.create(
                            type="suggestion",
                            title=f"Agent reviewed {nb_title}",
                            body=comment[:200],
                            metadata={"notebook_id": nb_id, "entry_id": entry_id},
                        )
                except Exception:
                    logger.debug("notifier.create failed", exc_info=True)

        logger.info(
            "Notebook review: %s (%d observations added)", nb_title, len(inserted_ids),
        )
        return 1

    except Exception:
        logger.debug("Notebook review failed", exc_info=True)
        return 0


async def _pick_notebook(db) -> dict | None:
    """Find the oldest share_with_agent=true notebook not reviewed recently."""
    cutoff = (
        datetime.now(timezone.utc) - _hours(REVIEW_INTERVAL_HOURS)
    ).isoformat()
    row = await db.fetch_one(
        "SELECT id, title, last_reviewed_at FROM notebooks "
        "WHERE share_with_agent = 1 "
        "AND (last_reviewed_at IS NULL OR last_reviewed_at < ?) "
        "ORDER BY COALESCE(last_reviewed_at, '1970-01-01') ASC LIMIT 1",
        (cutoff,),
    )
    return dict(row) if row else None


def _hours(n: int):
    from datetime import timedelta
    return timedelta(hours=n)


async def _load_user_content(db, notebook_id: str) -> str:
    """Concatenate all user entries into a single string."""
    rows = await db.fetch_all(
        "SELECT content FROM notebook_entries "
        "WHERE notebook_id = ? AND entry_type = 'user' AND status = 'active' "
        "ORDER BY created_at ASC",
        (notebook_id,),
    )
    return "\n\n".join(r["content"] for r in rows if r.get("content"))


async def _load_existing_agent_notes(db, notebook_id: str) -> list[dict]:
    rows = await db.fetch_all(
        "SELECT id, content, quote, status FROM notebook_entries "
        "WHERE notebook_id = ? AND entry_type = 'agent' "
        "ORDER BY created_at DESC",
        (notebook_id,),
    )
    return [dict(r) for r in rows]


async def _mark_stale_quotes(db, active_notes: list[dict], content: str) -> None:
    """Mark active agent notes whose quotes no longer exist in the content."""
    content_lower = content.lower()
    for note in active_notes:
        quote = note.get("quote")
        if not quote:
            continue
        if quote.lower() not in content_lower:
            await db.execute(
                "UPDATE notebook_entries SET status = 'stale' WHERE id = ?",
                (note["id"],),
            )
            logger.debug("Marked note %s as stale", note["id"][:8])


async def _build_review_prompt(user_content: str, existing_notes: list[dict]) -> str:
    """Build the review prompt from the template."""
    prompt_path = Path("data/prompts/notebook_review.md")
    if prompt_path.exists():
        template = prompt_path.read_text()
    else:
        template = "Review the notebook and return observations as JSON.\n\n{notebook_content}"

    principles_path = Path("data/agent/behavioral_principles.md")
    principles = ""
    if principles_path.exists():
        raw = principles_path.read_text()
        # Strip frontmatter
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                raw = parts[2]
        principles = raw.strip() or "(none defined)"
    else:
        principles = "(none defined)"

    existing_summary = "\n".join(
        f"- {(n.get('content') or '')[:100]}" for n in existing_notes[:5]
    ) or "(none)"

    return template.format(
        agent_principles=principles,
        existing_notes_summary=existing_summary,
        notebook_content=user_content,
    )


def _parse_observations(text: str) -> dict:
    """Parse JSON response, handling markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text, count=1)
        text = re.sub(r"\n?```\s*$", "", text.rstrip())
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse review JSON: %s", text[:200])
        return {"observations": []}
