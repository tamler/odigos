"""EvolutionEngine: orchestrates the self-improvement trial lifecycle.

Creates trials, monitors evaluation scores, promotes or reverts,
maintains failed-trial log and direction log.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.config import EvolutionConfig
    from odigos.core.checkpoint import CheckpointManager
    from odigos.core.evaluator import Evaluator
    from odigos.db import Database
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class EvolutionEngine:

    def __init__(
        self,
        db: Database,
        checkpoint_manager: CheckpointManager,
        evaluator: Evaluator,
        provider: LLMProvider,
        evolution_config: EvolutionConfig | None = None,
    ) -> None:
        self.db = db
        self.checkpoint = checkpoint_manager
        self.evaluator = evaluator
        self.provider = provider

        if evolution_config is None:
            from odigos.config import EvolutionConfig
            evolution_config = EvolutionConfig()
        self._config = evolution_config

    async def create_trial(
        self,
        hypothesis: str,
        target: str,
        change_description: str,
        overrides: dict[str, str],
        trial_hours: int | None = None,
        min_evaluations: int | None = None,
        direction_log_id: str | None = None,
    ) -> str:
        if trial_hours is None:
            trial_hours = self._config.trial_duration_hours
        if min_evaluations is None:
            min_evaluations = self._config.min_evaluations

        active = await self.checkpoint.get_active_trial()
        if active:
            logger.warning("Cannot create trial: trial %s already active", active["id"][:8])
            return active["id"]

        cp_id = await self.checkpoint.create_checkpoint(label="pre-trial")
        baseline = await self._get_baseline_score()

        trial_id = str(uuid.uuid4())
        expires = (datetime.now(timezone.utc) + timedelta(hours=trial_hours)).isoformat()

        await self.db.execute(
            "INSERT INTO trials (id, checkpoint_id, hypothesis, target, "
            "change_description, expires_at, min_evaluations, "
            "baseline_avg_score, direction_log_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                trial_id, cp_id, hypothesis, target,
                change_description, expires, min_evaluations,
                baseline, direction_log_id,
            ),
        )

        for name, content in overrides.items():
            await self.db.execute(
                "INSERT INTO trial_overrides (id, trial_id, target_type, target_name, "
                "override_content) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), trial_id, target, name, content),
            )

        logger.info(
            "Created trial %s: %s (expires %s)",
            trial_id[:8], hypothesis[:50], expires,
        )
        return trial_id

    async def check_active_trial(self) -> str | None:
        await self.checkpoint.expire_stale_trials()
        trial = await self.checkpoint.get_active_trial()
        if trial is None:
            return None

        trial_id = trial["id"]
        eval_count = trial["evaluation_count"] or 0
        min_evals = trial["min_evaluations"] or self._config.min_evaluations

        if eval_count < min_evals:
            return "continue"

        avg = trial["avg_score"] or 0.0
        baseline = trial["baseline_avg_score"] or 0.0
        delta = avg - baseline

        if delta >= self._config.promote_threshold:
            await self.checkpoint.promote_trial(trial_id)
            logger.info(
                "Promoted trial %s: score %.1f vs baseline %.1f (+%.1f)",
                trial_id[:8], avg, baseline, delta,
            )
            return "promoted"

        if delta <= self._config.revert_threshold:
            await self._revert_with_log(trial, reason="worse_than_baseline")
            return "reverted"

        return "continue"

    async def score_past_actions(self, limit: int = 3) -> int:
        trial = await self.checkpoint.get_active_trial()
        trial_id = trial["id"] if trial else None

        unscored = await self.evaluator.get_unscored_messages(limit=limit)
        scored = 0

        for msg in unscored:
            result = await self.evaluator.evaluate_action(
                msg["id"], msg["conversation_id"], trial_id=trial_id,
            )
            if result:
                scored += 1
                if trial_id:
                    await self._update_trial_score(trial_id, result["overall_score"])

        return scored

    async def _update_trial_score(self, trial_id: str, new_score: float) -> None:
        trial = await self.db.fetch_one(
            "SELECT evaluation_count, avg_score FROM trials WHERE id = ?", (trial_id,)
        )
        if not trial:
            return
        count = (trial["evaluation_count"] or 0) + 1
        old_avg = trial["avg_score"] or 0.0
        new_avg = old_avg + (new_score - old_avg) / count
        await self.db.execute(
            "UPDATE trials SET evaluation_count = ?, avg_score = ? WHERE id = ?",
            (count, new_avg, trial_id),
        )

    async def _get_baseline_score(self, lookback: int = 20) -> float:
        row = await self.db.fetch_one(
            "SELECT AVG(overall_score) as avg FROM evaluations "
            "WHERE trial_id IS NULL "
            "ORDER BY created_at DESC LIMIT ?",
            (lookback,),
        )
        return row["avg"] if row and row["avg"] else 5.0

    async def _revert_with_log(self, trial: dict, reason: str) -> None:
        trial_id = trial["id"]
        lessons = await self._generate_lessons(trial)
        await self.db.execute(
            "INSERT INTO failed_trials_log (id, trial_id, hypothesis, target, "
            "change_description, scores_summary, failure_reason, lessons) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                trial_id,
                trial["hypothesis"],
                trial["target"],
                trial.get("change_description"),
                json.dumps({"avg": trial.get("avg_score"), "baseline": trial.get("baseline_avg_score")}),
                reason,
                lessons,
            ),
        )
        await self.checkpoint.revert_trial(trial_id, reason=reason)
        logger.info("Reverted trial %s: %s", trial_id[:8], reason)

    async def _generate_lessons(self, trial: dict) -> str:
        try:
            response = await self.provider.complete(
                [{"role": "user", "content": (
                    f"A self-improvement trial failed.\n"
                    f"Hypothesis: {trial['hypothesis']}\n"
                    f"Change: {trial.get('change_description', 'N/A')}\n"
                    f"Score: {trial.get('avg_score', 'N/A')} vs baseline: {trial.get('baseline_avg_score', 'N/A')}\n\n"
                    "In 1-2 sentences, what should be learned from this failure? "
                    "What does it suggest about what to try differently?"
                )}],
                model=getattr(self.provider, "fallback_model", None),
                max_tokens=150,
                temperature=0.3,
            )
            return response.content.strip()
        except Exception:
            return "Lesson generation failed."

    async def get_failed_trials(self, limit: int = 20) -> list[dict]:
        rows = await self.db.fetch_all(
            "SELECT * FROM failed_trials_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    async def log_direction(
        self,
        analysis: str,
        direction: str,
        opportunities: list[dict],
        hypotheses: list[dict],
        confidence: float,
        based_on_evaluations: int,
    ) -> str:
        entry_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO direction_log (id, analysis, direction, opportunities, "
            "hypotheses, confidence, based_on_evaluations) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entry_id,
                analysis,
                direction,
                json.dumps(opportunities),
                json.dumps(hypotheses),
                confidence,
                based_on_evaluations,
            ),
        )
        return entry_id

    async def get_recent_directions(self, limit: int = 3) -> list[dict]:
        rows = await self.db.fetch_all(
            "SELECT * FROM direction_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]
