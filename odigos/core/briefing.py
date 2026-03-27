"""Morning briefing — daily proactive summary of calendar, email, tasks, feeds."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from odigos.core.llm_prompt import run_prompt

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

_BRIEFING_PROMPT = """\
You are composing a concise morning briefing for the user. Based on the data below, \
write a friendly, natural summary highlighting what matters today. Be brief — \
aim for 3-8 sentences. Include specific details (event names, task titles, sender names). \
If a section has no items, skip it entirely. End with an encouraging note.

Format: Use markdown. Use bullet lists for multiple items. Include links where provided.

{data}
"""

_META_KEY = "last_briefing_date"


async def _get_meta(db: Database, key: str) -> str | None:
    row = await db.fetch_one("SELECT value FROM agent_meta WHERE key = ?", (key,))
    return row["value"] if row else None


async def _set_meta(db: Database, key: str, value: str) -> None:
    await db.execute(
        "INSERT INTO agent_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


async def should_send_briefing(db: Database) -> bool:
    """Check if we should send a briefing today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    last = await _get_meta(db, _META_KEY)
    return last != today


async def mark_briefing_sent(db: Database) -> None:
    """Mark today's briefing as sent."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    await _set_meta(db, _META_KEY, today)


async def gather_briefing_data(db: Database, settings=None) -> str:
    """Collect all data sources for the briefing."""
    sections = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1. Kanban cards due today or overdue
    try:
        due_cards = await db.fetch_all(
            "SELECT c.title as card_title, c.due_at, c.priority, b.title as board_title "
            "FROM kanban_cards c JOIN kanban_boards b ON c.board_id = b.id "
            "WHERE c.due_at IS NOT NULL AND c.due_at <= ? "
            "ORDER BY c.due_at LIMIT 10",
            (today + "T23:59:59",),
        )
        if due_cards:
            lines = ["## Due Tasks"]
            for card in due_cards:
                overdue = card["due_at"] < today
                marker = " (OVERDUE)" if overdue else ""
                lines.append(f"- **{card['card_title']}**{marker} — {card['board_title']} [{card['priority']}]")
            sections.append("\n".join(lines))
    except Exception:
        logger.debug("Briefing: kanban query failed", exc_info=True)

    # 2. Pending todos
    try:
        todos = await db.fetch_all(
            "SELECT description FROM todos WHERE status = 'pending' ORDER BY created_at LIMIT 10"
        )
        if todos:
            lines = ["## Pending Todos"]
            for t in todos:
                lines.append(f"- {t['description']}")
            sections.append("\n".join(lines))
    except Exception:
        logger.debug("Briefing: todos query failed", exc_info=True)

    # 3. Active reminders due today
    try:
        reminders = await db.fetch_all(
            "SELECT description, due_at FROM reminders "
            "WHERE status = 'pending' AND due_at <= ? ORDER BY due_at LIMIT 10",
            (today + "T23:59:59",),
        )
        if reminders:
            lines = ["## Reminders"]
            for r in reminders:
                due = r["due_at"][:16] if r["due_at"] else "now"
                lines.append(f"- {r['description']} (due: {due})")
            sections.append("\n".join(lines))
    except Exception:
        logger.debug("Briefing: reminders query failed", exc_info=True)

    # 4. Recent feed items (last 24h)
    try:
        feed_items = await db.fetch_all(
            "SELECT title, source_name FROM feed_items "
            "WHERE created_at >= datetime('now', '-1 day') ORDER BY created_at DESC LIMIT 5"
        )
        if feed_items:
            lines = ["## Recent Feed Items"]
            for item in feed_items:
                lines.append(f"- {item['title']} — {item['source_name']}")
            sections.append("\n".join(lines))
    except Exception:
        logger.debug("Briefing: feed query failed", exc_info=True)

    # 5. Unread emails (if email table exists)
    try:
        emails = await db.fetch_all(
            "SELECT sender, subject FROM emails "
            "WHERE read = 0 ORDER BY received_at DESC LIMIT 5"
        )
        if emails:
            lines = ["## Unread Emails"]
            for e in emails:
                lines.append(f"- **{e['subject']}** from {e['sender']}")
            sections.append("\n".join(lines))
    except Exception:
        logger.debug("Briefing: email query failed", exc_info=True)

    # 5b. Live email count (if email config is enabled)
    if settings and getattr(settings, "email", None):
        email_cfg = settings.email
        if getattr(email_cfg, "enabled", False):
            try:
                from odigos.tools.email import CheckEmailTool
                tool = CheckEmailTool(email_config=email_cfg)
                result = await tool.execute(
                    {"limit": 1, "unread_only": True},
                )
                if result.success and "No new emails" not in result.data:
                    count = result.data.count("From:")
                    if count > 0:
                        sections.append(
                            f"## Email Inbox\n"
                            f"- {count} unread email(s) in inbox"
                        )
            except Exception:
                logger.debug(
                    "Briefing: live email check failed",
                    exc_info=True,
                )

    # 6. Calendar events today (if calendar configured)
    if settings and getattr(settings, 'calendar', None) and settings.calendar.enabled:
        try:
            from odigos.tools.calendar import _get_caldav_events
            events = await _get_caldav_events(settings.calendar, today, today)
            if events:
                lines = ["## Calendar Events"]
                for ev in events[:10]:
                    lines.append(f"- {ev.get('summary', 'Event')} at {ev.get('start', '?')}")
                sections.append("\n".join(lines))
        except Exception:
            logger.debug("Briefing: calendar query failed", exc_info=True)

    # 7. Active goals
    try:
        goals = await db.fetch_all(
            "SELECT description FROM goals WHERE status = 'active' ORDER BY created_at LIMIT 5"
        )
        if goals:
            lines = ["## Active Goals"]
            for g in goals:
                lines.append(f"- {g['description']}")
            sections.append("\n".join(lines))
    except Exception:
        logger.debug("Briefing: goals query failed", exc_info=True)

    if not sections:
        return "No items to report. All clear!"

    return "\n\n".join(sections)


async def compose_briefing(
    db: Database,
    provider: LLMProvider,
    settings=None,
    model: str = "",
) -> str:
    """Gather data and compose an LLM-written morning briefing."""
    data = await gather_briefing_data(db, settings=settings)

    if data == "No items to report. All clear!":
        return "Good morning! Your day is clear — no pending tasks, reminders, or new items. Enjoy the calm."

    prompt = _BRIEFING_PROMPT.format(data=data)
    try:
        response = await run_prompt(provider, prompt, model=model)
        return response.content if hasattr(response, 'content') else str(response)
    except Exception as e:
        logger.warning("Briefing LLM call failed: %s", e)
        # Fallback: return raw data
        return f"# Morning Briefing\n\n{data}"
