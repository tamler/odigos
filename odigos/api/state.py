"""Agent State Inspector API — comprehensive snapshot of agent internals."""
from __future__ import annotations

import os
import platform
import sys
import time

from fastapi import APIRouter, Depends, Request

from odigos.api.deps import require_auth, get_db
from odigos.db import Database

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_auth)],
)

_start_time = time.monotonic()


def _format_uptime(seconds: float) -> str:
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


@router.get("/state")
async def get_state(request: Request, db: Database = Depends(get_db)):
    """Return a comprehensive snapshot of agent internal state."""
    settings = request.app.state.settings
    agent = request.app.state.agent
    budget_tracker = request.app.state.budget_tracker

    uptime_seconds = time.monotonic() - _start_time
    uptime_formatted = _format_uptime(uptime_seconds)

    # -- Agent info --
    active_convs = await db.fetch_one(
        "SELECT COUNT(DISTINCT conversation_id) AS cnt FROM messages "
        "WHERE timestamp > datetime('now', '-1 hour')"
    )
    total_convs = await db.fetch_one(
        "SELECT COUNT(*) AS cnt FROM conversations"
    )
    agent_info = {
        "name": settings.agent.name,
        "role": settings.agent.role,
        "uptime": uptime_formatted,
        "uptime_seconds": round(uptime_seconds, 1),
        "active_conversations": active_convs["cnt"] if active_convs else 0,
    }

    # -- Budget --
    budget_status = await budget_tracker.check_budget()
    budget_info = {
        "daily_spend": round(budget_status.daily_spend, 4),
        "daily_limit": budget_status.daily_limit,
        "monthly_spend": round(budget_status.monthly_spend, 4),
        "monthly_limit": budget_status.monthly_limit,
        "within_budget": budget_status.within_budget,
        "warning": budget_status.warning,
    }

    # -- Memory --
    mem_total = await db.fetch_one("SELECT COUNT(*) AS cnt FROM memory_entries")
    mem_recent = await db.fetch_one(
        "SELECT COUNT(*) AS cnt FROM memory_entries WHERE created_at > datetime('now', '-24 hours')"
    )
    memory_info = {
        "total": mem_total["cnt"] if mem_total else 0,
        "recent_24h": mem_recent["cnt"] if mem_recent else 0,
    }

    # -- Conversations --
    recent_activity = await db.fetch_one(
        "SELECT COUNT(*) AS cnt FROM messages WHERE timestamp > datetime('now', '-1 hour')"
    )
    conversations_info = {
        "active": active_convs["cnt"] if active_convs else 0,
        "total": total_convs["cnt"] if total_convs else 0,
        "recent_messages_1h": recent_activity["cnt"] if recent_activity else 0,
    }

    # -- Tools --
    tool_registry = agent.executor.tool_registry
    tool_names = []
    if tool_registry:
        tool_names = [t.name for t in tool_registry.list()]

    # -- Skills --
    skill_registry = getattr(request.app.state, "skill_registry", None)
    skills_info = []
    if skill_registry:
        for s in skill_registry.list():
            skills_info.append({
                "name": s.name,
                "description": s.description,
                "complexity": s.complexity,
                "enabled": True,
            })

    # -- Plugins --
    plugin_manager = getattr(request.app.state, "plugin_manager", None)
    plugins_info = []
    if plugin_manager:
        for p in plugin_manager.loaded_plugins:
            plugins_info.append({
                "name": p.get("name", "unknown"),
                "status": p.get("status", "unknown"),
            })

    # -- Evolution --
    eval_count_row = await db.fetch_one("SELECT COUNT(*) AS cnt FROM evaluations")
    recent_evals = await db.fetch_all(
        "SELECT overall_score FROM evaluations ORDER BY created_at DESC LIMIT 20"
    )
    scores = [r["overall_score"] for r in recent_evals if r["overall_score"] is not None]
    avg_score = round(sum(scores) / len(scores), 2) if scores else None

    active_trial = await db.fetch_one(
        "SELECT id, hypothesis, target, status FROM trials "
        "WHERE status = 'active' ORDER BY started_at DESC LIMIT 1"
    )
    trial_count_row = await db.fetch_one("SELECT COUNT(*) AS cnt FROM trials")

    evolution_info = {
        "cycle_count": trial_count_row["cnt"] if trial_count_row else 0,
        "evaluation_count": eval_count_row["cnt"] if eval_count_row else 0,
        "recent_avg_score": avg_score,
        "active_trial": dict(active_trial) if active_trial else None,
    }

    # -- Heartbeat --
    heartbeat = getattr(agent, "heartbeat", None)
    heartbeat_info = {
        "interval": heartbeat._interval if heartbeat else None,
        "paused": heartbeat.paused if heartbeat else None,
        "uptime": uptime_formatted,
    }

    # -- Cron --
    cron_manager = getattr(request.app.state, "cron_manager", None)
    cron_info = None
    if cron_manager:
        entries = getattr(cron_manager, "entries", [])
        cron_info = {
            "total": len(entries),
            "enabled": sum(1 for e in entries if getattr(e, "enabled", True)),
        }

    # -- System --
    system_info = {
        "python_version": sys.version,
        "platform": platform.platform(),
        "pid": os.getpid(),
    }

    return {
        "agent": agent_info,
        "budget": budget_info,
        "memory": memory_info,
        "conversations": conversations_info,
        "tools": tool_names,
        "skills": skills_info,
        "plugins": plugins_info,
        "evolution": evolution_info,
        "heartbeat": heartbeat_info,
        "cron": cron_info,
        "system": system_info,
    }
