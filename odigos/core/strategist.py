"""Strategist: analyzes evaluation trends and proposes improvement hypotheses.

Runs periodically in heartbeat Phase 5 when enough new evaluations accumulate.
Generates two types of output:
- trial_hypothesis: self-improvement proposals (auto-created if confidence > 0.7)
- specialization_proposal: new agent suggestions (stored for user approval)
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.core.evolution import EvolutionEngine
    from odigos.db import Database
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

AUTO_TRIAL_CONFIDENCE = 0.7
MIN_EVALS_TO_RUN = 10


class Strategist:

    def __init__(
        self,
        db: Database,
        provider: LLMProvider,
        evolution_engine: EvolutionEngine,
        agent_description: str = "",
        agent_tools: list[str] | None = None,
    ) -> None:
        self.db = db
        self.provider = provider
        self.evolution = evolution_engine
        self._agent_description = agent_description
        self._agent_tools = agent_tools or []
        self._last_eval_count: int = 0

    async def should_run(self) -> bool:
        """Check if enough new evaluations have accumulated since last run."""
        row = await self.db.fetch_one(
            "SELECT COUNT(*) as cnt FROM evaluations"
        )
        total = row["cnt"] if row else 0
        return (total - self._last_eval_count) >= MIN_EVALS_TO_RUN

    async def analyze(self) -> dict | None:
        """Run the full strategist cycle: analyze, hypothesize, act."""
        # Gather context
        recent_evals = await self._get_evaluation_summary()
        failed_trials = await self.evolution.get_failed_trials(limit=10)
        directions = await self.evolution.get_recent_directions(limit=3)

        # Build prompt
        prompt = self._build_prompt(recent_evals, failed_trials, directions)

        # Ask LLM
        try:
            response = await self.provider.complete(
                [{"role": "user", "content": prompt}],
                model=getattr(self.provider, "fallback_model", None),
                max_tokens=800,
                temperature=0.4,
            )
            result = _parse_json(response.content)
            if result is None:
                logger.warning("Strategist: failed to parse LLM response")
                return None
        except Exception:
            logger.warning("Strategist: LLM call failed", exc_info=True)
            return None

        # Record the run
        run_id = str(uuid.uuid4())
        row = await self.db.fetch_one("SELECT COUNT(*) as cnt FROM evaluations")
        self._last_eval_count = row["cnt"] if row else 0

        # Log direction
        direction_id = await self.evolution.log_direction(
            analysis=result.get("analysis", ""),
            direction=result.get("direction", ""),
            opportunities=[],
            hypotheses=result.get("hypotheses", []),
            confidence=0.5,
            based_on_evaluations=self._last_eval_count,
        )

        await self.db.execute(
            "INSERT INTO strategist_runs (id, evaluations_analyzed, hypotheses_generated, "
            "specialization_proposals, direction_log_id) VALUES (?, ?, ?, ?, ?)",
            (
                run_id,
                self._last_eval_count,
                json.dumps(result.get("hypotheses", [])),
                json.dumps(result.get("specialization_proposals", [])),
                direction_id,
            ),
        )

        # Act on hypotheses
        for h in result.get("hypotheses", []):
            if h.get("type") == "trial_hypothesis" and h.get("confidence", 0) >= AUTO_TRIAL_CONFIDENCE:
                target_name = h.get("target_name", "voice")
                await self.evolution.create_trial(
                    hypothesis=h["hypothesis"],
                    target=h.get("target", "prompt_section"),
                    change_description=h.get("change", ""),
                    overrides={target_name: h.get("change", "")},
                    direction_log_id=direction_id,
                )
                logger.info("Strategist auto-created trial: %s", h["hypothesis"][:50])
                break  # Only one trial at a time

        # Store specialization proposals
        for sp in result.get("specialization_proposals", []):
            await self.db.execute(
                "INSERT INTO specialization_proposals "
                "(id, proposed_by, role, specialty, description, rationale) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    "strategist",
                    sp.get("role", "specialist"),
                    sp.get("specialty"),
                    sp.get("description", ""),
                    sp.get("rationale", ""),
                ),
            )
            logger.info("Strategist proposed specialist: %s", sp.get("role"))

        return result

    async def _get_evaluation_summary(self) -> dict:
        """Summarize recent evaluations by task type."""
        rows = await self.db.fetch_all(
            "SELECT task_type, COUNT(*) as cnt, AVG(overall_score) as avg_score, "
            "AVG(implicit_feedback) as avg_feedback "
            "FROM evaluations "
            "WHERE created_at > datetime('now', '-7 days') "
            "GROUP BY task_type "
            "ORDER BY cnt DESC LIMIT 10"
        )
        return {
            "by_task_type": [dict(r) for r in rows],
            "total_recent": sum(r["cnt"] for r in rows) if rows else 0,
        }

    def _build_prompt(self, eval_summary: dict, failed_trials: list, directions: list) -> str:
        failed_summary = ""
        if failed_trials:
            failed_summary = "\n".join(
                f"- {f.get('hypothesis', '?')}: {f.get('failure_reason', '?')} -- {f.get('lessons', '')}"
                for f in failed_trials[:5]
            )

        direction_summary = ""
        if directions:
            direction_summary = "\n".join(
                f"- {d.get('direction', '?')} (confidence: {d.get('confidence', '?')})"
                for d in directions[:3]
            )

        task_summary = ""
        if eval_summary.get("by_task_type"):
            task_summary = "\n".join(
                f"- {t.get('task_type', '?')}: {t.get('cnt', 0)} actions, avg score {(t.get('avg_score') or 0):.1f}, "
                f"avg feedback {(t.get('avg_feedback') or 0):.1f}"
                for t in eval_summary["by_task_type"]
            )

        return f"""You are the strategist for an AI agent's self-improvement system.
Analyze this agent's recent performance and propose improvements.

## Agent Context
Description: {self._agent_description or 'No description set'}
Available tools: {', '.join(self._agent_tools) if self._agent_tools else 'None listed'}

## Recent Evaluation Summary (last 7 days)
{task_summary or 'No evaluations yet.'}

## Failed Trials (avoid repeating these)
{failed_summary or 'None.'}

## Recent Direction Log
{direction_summary or 'No prior direction set.'}

## Instructions
Based on the above, produce a JSON object with:
1. "analysis" -- 1-2 sentence summary of current performance
2. "direction" -- 1 sentence on what to focus on improving
3. "hypotheses" -- Array of 0-3 improvement proposals. Each has:
   - "type": "trial_hypothesis"
   - "hypothesis": what to try
   - "target": "prompt_section"
   - "target_name": which section to modify (e.g. "voice", "identity", "meta")
   - "change": the new content for that section
   - "confidence": 0.0-1.0
4. "specialization_proposals" -- Array of 0-1 proposals if a domain is consistently weak and would benefit from a dedicated specialist agent. Each has:
   - "role": short role name
   - "specialty": routing tag
   - "description": 1-2 sentences
   - "rationale": why this specialist is needed

Do NOT propose changes that have already failed (see failed trials above).
Return ONLY the JSON object, no markdown."""


def _parse_json(text: str) -> dict | None:
    """Extract JSON from LLM response."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, TypeError):
            pass
    return None
