"""Heartbeat idle thinking module."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from odigos.core.json_utils import parse_json_response
from odigos.core.prompt_loader import load_prompt

if TYPE_CHECKING:
    from odigos.core.heartbeat_old import Heartbeat

logger = logging.getLogger(__name__)

_IDLE_THINK_FALLBACK = (
    "You are reviewing your active goals during idle time. "
    "If there's something useful you could do right now, respond with a JSON object: "
    '{"todo": "description of work item"}. '
    "If you have a progress observation, respond with: "
    '{"note": "goal_id", "progress": "observation"}. '
    'If nothing to do, respond with: {"idle": true}'
)


async def idle_think(hb: "Heartbeat") -> None:
    now = time.monotonic()
    if now - hb._last_idle < hb._idle_think_interval:
        return
    hb._last_idle = now

    goals = await hb.goal_store.list_goals(status="active")
    if not goals:
        return

    goal_text = "\n".join(
        f"- [{g['id'][:8]}] {g['description']}"
        + (f" (progress: {g['progress_note']})" if g.get("progress_note") else "")
        for g in goals
    )

    research_context = ""
    try:
        from odigos.core.idle_research import (
            find_research_opportunities,
            format_research_prompt,
        )
        opportunities = await find_research_opportunities(hb.db)
        research_context = format_research_prompt(opportunities)
    except Exception:
        logger.debug("Idle research lookup failed", exc_info=True)

    user_content = f"Active goals:\n{goal_text}"
    if research_context:
        user_content += f"\n\n{research_context}"

    try:
        from odigos.core.llm_prompt import call_llm
        response = await call_llm(
            hb.provider,
            [
                {
                    "role": "system",
                    "content": load_prompt("heartbeat_idle.md", _IDLE_THINK_FALLBACK),
                },
                {"role": "user", "content": user_content},
            ],
            max_tokens=200,
            temperature=0.3,
            model=hb._background_model or None,
            log_name="idle_think",
        )
        if not response:
            return
        logger.debug("Idle thought: %s", response.content[:100])
        await process_idle_response(hb, response.content, goals)
    except Exception:
        logger.debug("Idle think failed", exc_info=True)


async def process_idle_response(hb: "Heartbeat", response: str, goals: list[dict]) -> None:
    parsed = parse_json_response(response)
    if parsed is None:
        return
    if parsed.get("idle"):
        return
    if "todo" in parsed:
        await hb.goal_store.create_todo(
            description=parsed["todo"], created_by="agent",
        )
        logger.info("Idle-think created todo: %s", parsed["todo"][:50])
    elif "note" in parsed and "progress" in parsed:
        goal_id_prefix = parsed["note"]
        for g in goals:
            if g["id"].startswith(goal_id_prefix):
                await hb.goal_store.update_goal(
                    g["id"],
                    progress_note=parsed["progress"],
                    reviewed_at=datetime.now(timezone.utc).isoformat(),
                )
                logger.info("Idle-think updated goal %s", g["id"][:8])
                break
