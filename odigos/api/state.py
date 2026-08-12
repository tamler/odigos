"""Agent State Inspector API — comprehensive snapshot of agent internals."""
from __future__ import annotations

import logging
import os
import platform
import sys
import time

from fastapi import APIRouter, Depends

from odigos.api.deps import (
    get_agent,
    get_budget_tracker,
    get_scheduler,
    get_db,
    get_plugin_manager,
    get_settings,
    get_skill_registry,
    require_auth,
)
from odigos.core.capabilities import degraded_capabilities
from odigos.db import Database

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_auth)],
)

_start_time = time.monotonic()

# -- In-memory TTL cache for heavy aggregate queries --
_STATE_CACHE: dict = {}
_STATE_CACHE_TTL_SECONDS = 60


def _state_cache_get(key: str):
    entry = _STATE_CACHE.get(key)
    if entry is None:
        return None
    value, expires_at = entry
    if time.time() > expires_at:
        return None
    return value


def _state_cache_set(key: str, value):
    _STATE_CACHE[key] = (value, time.time() + _STATE_CACHE_TTL_SECONDS)


def _state_cache_clear():
    _STATE_CACHE.clear()


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
async def get_state(
    db: Database = Depends(get_db),
    settings=Depends(get_settings),
    agent=Depends(get_agent),
    budget_tracker=Depends(get_budget_tracker),
    skill_registry=Depends(get_skill_registry),
    plugin_manager=Depends(get_plugin_manager),
    scheduler=Depends(get_scheduler),
):
    """Return a comprehensive snapshot of agent internal state."""

    uptime_seconds = time.monotonic() - _start_time
    uptime_formatted = _format_uptime(uptime_seconds)

    # -- Cached aggregates (heavy DB queries, 60s TTL) --
    aggregates = _state_cache_get("aggregates")
    if aggregates is None:
        # -- Memory --
        mem_total = await db.fetch_one(
            "SELECT COUNT(*) AS cnt FROM memories WHERE status = 'active'"
        )
        mem_recent = await db.fetch_one(
            "SELECT COUNT(*) AS cnt FROM memories WHERE status = 'active'"
            " AND created_at > datetime('now', '-24 hours')"
        )
        memory_info = {
            "total": mem_total["cnt"] if mem_total else 0,
            "recent_24h": mem_recent["cnt"] if mem_recent else 0,
        }

        # -- Conversations --
        active_convs = await db.fetch_one(
            "SELECT COUNT(DISTINCT conversation_id) AS cnt FROM messages "
            "WHERE created_at > datetime('now', '-1 hour')"
        )
        total_convs = await db.fetch_one(
            "SELECT COUNT(*) AS cnt FROM conversations"
        )
        recent_activity = await db.fetch_one(
            "SELECT COUNT(*) AS cnt FROM messages WHERE created_at > datetime('now', '-1 hour')"
        )
        conversations_info = {
            "active": active_convs["cnt"] if active_convs else 0,
            "total": total_convs["cnt"] if total_convs else 0,
            "recent_messages_1h": recent_activity["cnt"] if recent_activity else 0,
        }

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

        aggregates = {
            "memory": memory_info,
            "conversations": conversations_info,
            "evolution": evolution_info,
        }
        _state_cache_set("aggregates", aggregates)

    # -- Budget (not cached — small query, reflects spend in near-real-time) --
    budget_status = await budget_tracker.check_budget()
    budget_info = {
        "daily_spend": round(budget_status.daily_spend, 4),
        "daily_limit": budget_status.daily_limit,
        "monthly_spend": round(budget_status.monthly_spend, 4),
        "monthly_limit": budget_status.monthly_limit,
        "within_budget": budget_status.within_budget,
        "warning": budget_status.warning,
    }

    # -- Agent info (uptime is live, conversation count from cache) --
    agent_info = {
        "name": settings.agent.name,
        "role": settings.agent.role,
        "uptime": uptime_formatted,
        "uptime_seconds": round(uptime_seconds, 1),
        "active_conversations": aggregates["conversations"]["active"],
    }

    # -- Tools (in-process, not a DB query) --
    tool_registry = agent.executor.tool_registry
    tool_names = []
    if tool_registry:
        tool_names = [t.name for t in tool_registry.list()]

    # -- Skills (in-process) --
    skills_info = []
    if skill_registry:
        for s in skill_registry.list():
            skills_info.append({
                "name": s.name,
                "description": s.description,
                "complexity": s.complexity,
                "enabled": True,
            })

    # -- Plugins (in-process) --
    plugins_info = []
    if plugin_manager:
        for p in plugin_manager.loaded_plugins:
            plugins_info.append({
                "name": p.get("name", "unknown"),
                "status": p.get("status", "unknown"),
            })

    # -- Heartbeat (always live — never cached) --
    heartbeat = getattr(agent, "heartbeat", None)
    heartbeat_status = {
        "current_phase": None,
        "current_activity": None,
        "current_plan": None,
    }
    if heartbeat is not None:
        try:
            heartbeat_status = heartbeat.get_status()
        except Exception:
            logger.debug("Failed to get heartbeat status", exc_info=True)

    heartbeat_info = {
        "interval": heartbeat._interval if heartbeat else None,
        "paused": heartbeat.paused if heartbeat else None,
        "uptime": uptime_formatted,
        **heartbeat_status,
    }

    # -- Cron --
    # Reads the unified Scheduler. This used to read a nonexistent
    # `cron_manager.entries` through getattr with a [] default, so it always
    # reported zero; CronManager itself is gone as of 2026-08-12, and
    # scheduled_tasks is where recurring work has actually lived for a while.
    cron_info = None
    if scheduler:
        try:
            entries = await scheduler.list_tasks()
        except Exception:
            logger.debug("Could not list scheduled tasks", exc_info=True)
            entries = []
        cron_info = {
            "total": len(entries),
            "enabled": sum(1 for e in entries if e.get("enabled", 1)),
        }

    # -- System --
    system_info = {
        "python_version": sys.version,
        "platform": platform.platform(),
        "pid": os.getpid(),
    }

    # Capabilities whose declared dependency failed to import. Empty is healthy.
    # Without this an operator's only signal is a 404 or a quietly skipped path
    # -- which is how passkey auth stayed broken for weeks (01-cleanup.md §0f).
    degraded = degraded_capabilities()

    return {
        "degraded_capabilities": degraded,
        "agent": agent_info,
        "budget": budget_info,
        "memory": aggregates["memory"],
        "conversations": aggregates["conversations"],
        "tools": tool_names,
        "skills": skills_info,
        "plugins": plugins_info,
        "evolution": aggregates["evolution"],
        "heartbeat": heartbeat_info,
        "cron": cron_info,
        "system": system_info,
    }
