"""Fitness functions — user-defined optimization targets for the evolution engine.

Fitness functions tell the evolution engine WHAT to optimize. Instead of
just improving "overall score", the agent targets specific metrics like
response speed, document recall accuracy, or user satisfaction.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database

logger = logging.getLogger(__name__)


async def list_fitness_functions(db: Database, enabled_only: bool = True) -> list[dict]:
    """List all fitness functions."""
    if enabled_only:
        rows = await db.fetch_all(
            "SELECT * FROM fitness_functions WHERE enabled = 1 ORDER BY weight DESC"
        )
    else:
        rows = await db.fetch_all("SELECT * FROM fitness_functions ORDER BY weight DESC")
    return [dict(r) for r in rows]


async def create_fitness_function(
    db: Database,
    name: str,
    description: str,
    metric: str,
    target_score: float | None = None,
    weight: float = 1.0,
) -> str:
    """Create a new fitness function."""
    func_id = uuid.uuid4().hex[:16]
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO fitness_functions (id, name, description, metric, target_score, weight, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (func_id, name, description, metric, target_score, weight, now, now),
    )
    return func_id


async def update_fitness_score(db: Database, func_id: str, score: float) -> None:
    """Update the current score for a fitness function."""
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "UPDATE fitness_functions SET current_score = ?, updated_at = ? WHERE id = ?",
        (score, now, func_id),
    )


async def get_fitness_summary(db: Database) -> str:
    """Get a formatted summary of fitness functions for the strategist prompt."""
    functions = await list_fitness_functions(db)
    if not functions:
        return "No fitness functions defined. Optimizing overall score."

    lines = []
    for f in functions:
        target = f"target: {f['target_score']}" if f['target_score'] is not None else "no target"
        status = ""
        if f['target_score'] is not None:
            if f['current_score'] >= f['target_score']:
                status = " [ACHIEVED]"
            else:
                gap = f['target_score'] - f['current_score']
                status = f" [gap: {gap:.2f}]"
        lines.append(
            f"- **{f['name']}** ({f['metric']}): current={f['current_score']:.2f}, "
            f"{target}, weight={f['weight']}{status}"
        )
        if f['description']:
            lines.append(f"  {f['description']}")

    return "\n".join(lines)


async def store_trial_pattern(
    db: Database,
    trial_id: str,
    pattern_type: str,
    target: str,
    target_name: str,
    hypothesis: str,
    score_delta: float,
    context: dict | None = None,
) -> None:
    """Record a success/failure pattern from a completed trial."""
    pattern_id = uuid.uuid4().hex[:16]
    await db.execute(
        "INSERT INTO trial_patterns (id, trial_id, pattern_type, target, target_name, "
        "hypothesis, score_delta, context, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (
            pattern_id, trial_id, pattern_type, target, target_name,
            hypothesis, score_delta,
            json.dumps(context) if context else None,
        ),
    )


async def get_trial_patterns_summary(db: Database, limit: int = 20) -> str:
    """Get a formatted summary of trial patterns for the strategist prompt."""
    patterns = await db.fetch_all(
        "SELECT pattern_type, target, target_name, hypothesis, score_delta "
        "FROM trial_patterns ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    if not patterns:
        return "No trial history yet."

    successes = [p for p in patterns if p["pattern_type"] == "success"]
    failures = [p for p in patterns if p["pattern_type"] == "failure"]

    lines = []
    if successes:
        lines.append("### Successful Patterns (repeat these)")
        for p in successes:
            lines.append(f"- {p['target']}/{p['target_name']}: {p['hypothesis'][:100]} (score +{p['score_delta']:.2f})")

    if failures:
        lines.append("### Failed Patterns (avoid these)")
        for p in failures:
            lines.append(f"- {p['target']}/{p['target_name']}: {p['hypothesis'][:100]} (score {p['score_delta']:.2f})")

    return "\n".join(lines)


# Operating modes
EVOLUTION_MODES = {
    "continuous": "Keep improving indefinitely (default). Always propose new trials.",
    "converge": "Stop when all fitness function targets are met.",
    "supervised": "Propose trials but require user approval before starting.",
}


async def get_evolution_mode(db: Database) -> str:
    """Get the current evolution operating mode."""
    try:
        row = await db.fetch_one("SELECT value FROM agent_meta WHERE key = 'evolution_mode'")
        return row["value"] if row else "continuous"
    except Exception:
        return "continuous"


async def set_evolution_mode(db: Database, mode: str) -> None:
    """Set the evolution operating mode."""
    if mode not in EVOLUTION_MODES:
        raise ValueError(f"Invalid mode: {mode}. Must be one of: {list(EVOLUTION_MODES.keys())}")
    await db.execute(
        "INSERT INTO agent_meta (key, value) VALUES ('evolution_mode', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (mode,),
    )
