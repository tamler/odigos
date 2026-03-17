"""Strategist: analyzes evaluation trends and proposes improvement hypotheses.

Runs periodically in heartbeat Phase 5 when enough new evaluations accumulate.
Generates two types of output:
- trial_hypothesis: self-improvement proposals (auto-created if confidence > 0.7)
- specialization_proposal: new agent suggestions (stored for user approval)
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING

from odigos.core.llm_prompt import run_prompt
from odigos.core.prompt_loader import load_prompt

if TYPE_CHECKING:
    from odigos.config import EvolutionConfig
    from odigos.core.evolution import EvolutionEngine
    from odigos.db import Database
    from odigos.providers.base import LLMProvider
    from odigos.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

_STRATEGIST_FALLBACK = """\
You are the strategist for an AI agent's self-improvement system.
Analyze this agent's recent performance and propose improvements.

## Agent Context
Description: {agent_description}
Available tools: {agent_tools}

## Recent Evaluation Summary (last 7 days)
{task_summary}

## Failed Trials (avoid repeating these)
{failed_summary}

## Recent Direction Log
{direction_summary}

## Query Classification Performance (last 7 days)
{query_log_summary}

## Skill Usage Performance (last 7 days)
{skill_usage_summary}

Skills with high scores are working well. Skills with low scores may need improvement or the agent may be using them inappropriately.

## Skill Mining Opportunities
{skill_mining_summary}

If you see a repeated pattern that could be a reusable skill, include it in your hypotheses with target="new_skill".

## Plan Outcome Evaluations (last 7 days)
{outcome_summary}

Plans that failed to achieve their goals may indicate systemic issues with planning or execution.

When proposing hypotheses, consider:
- Classifications with low average scores may need better routing
- High duration classifications may benefit from pipeline optimization
- You can propose changes to data/agent/classification_rules.md to improve heuristic routing
- Repeated tool combinations with high scores may indicate a new skill opportunity

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
   When target="new_skill", also include:
   - "skill_name": lowercase alphanumeric name for the skill
   - "skill_instructions": full system prompt for the new skill
   - "description": one-line description
4. "specialization_proposals" -- Array of 0-1 proposals if a domain is consistently weak and would benefit from a dedicated specialist agent. Each has:
   - "role": short role name
   - "specialty": routing tag
   - "description": 1-2 sentences
   - "rationale": why this specialist is needed

Do NOT propose changes that have already failed (see failed trials above).
Return ONLY the JSON object, no markdown."""


class Strategist:
    """Analyzes evaluation trends and proposes self-improvement hypotheses.

    Runs periodically during heartbeat Phase 5 when enough new evaluations
    accumulate. Generates trial hypotheses for prompt section changes and
    specialization proposals for new dedicated agents.
    """

    def __init__(
        self,
        db: Database,
        provider: LLMProvider,
        evolution_engine: EvolutionEngine,
        agent_description: str = "",
        agent_tools: list[str] | None = None,
        evolution_config: EvolutionConfig | None = None,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self.db = db
        self.provider = provider
        self.evolution = evolution_engine
        self._agent_description = agent_description
        self._agent_tools = agent_tools or []
        self._last_eval_count: int = 0
        self.skill_registry = skill_registry

        if evolution_config is None:
            from odigos.config import EvolutionConfig
            evolution_config = EvolutionConfig()
        self._config = evolution_config

    async def should_run(self) -> bool:
        """Check if enough new evaluations have accumulated since last run."""
        row = await self.db.fetch_one(
            "SELECT COUNT(*) as cnt FROM evaluations"
        )
        total = row["cnt"] if row else 0
        return (total - self._last_eval_count) >= self._config.strategist_min_evals

    async def analyze(self) -> dict | None:
        """Run the full strategist cycle: analyze, hypothesize, act."""
        # Gather context
        recent_evals = await self._get_evaluation_summary()
        query_log_summary = await self._get_query_log_summary()
        skill_usage_summary = await self._get_skill_usage_summary()
        skill_mining_summary = await self._get_skill_mining_summary()
        outcome_summary = await self._get_outcome_summary()
        failed_trials = await self.evolution.get_failed_trials(limit=10)
        directions = await self.evolution.get_recent_directions(limit=3)

        # Build prompt variables
        prompt_vars = self._build_prompt_vars(
            recent_evals, failed_trials, directions,
            query_log_summary, skill_usage_summary, skill_mining_summary,
            outcome_summary,
        )

        # Ask LLM
        result = await run_prompt(
            self.provider,
            "strategist.md",
            prompt_vars,
            _STRATEGIST_FALLBACK,
            model=getattr(self.provider, "fallback_model", None),
            max_tokens=800,
            temperature=0.4,
        )
        if result is None:
            logger.warning("Strategist: failed to get LLM response")
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
            target = h.get("target", "prompt_section")

            # Skill mining: create new skill from detected pattern
            if target == "new_skill" and h.get("skill_name") and h.get("skill_instructions"):
                if self.skill_registry:
                    try:
                        self.skill_registry.create(
                            name=h["skill_name"],
                            description=h.get("description", "Auto-generated skill"),
                            system_prompt=h["skill_instructions"],
                        )
                        logger.info("Strategist created new skill: %s", h["skill_name"])
                    except Exception:
                        logger.warning("Failed to create proposed skill", exc_info=True)
                continue

            if h.get("type") == "trial_hypothesis" and h.get("confidence", 0) >= self._config.auto_trial_confidence:
                target_name = h.get("target_name", "voice")
                await self.evolution.create_trial(
                    hypothesis=h["hypothesis"],
                    target=target,
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

    async def _get_skill_usage_summary(self) -> str:
        """Summarize recent skill usage and their evaluation scores."""
        try:
            rows = await self.db.fetch_all(
                "SELECT skill_name, skill_type, COUNT(*) as count, "
                "AVG(evaluation_score) as avg_score "
                "FROM skill_usage "
                "WHERE created_at > datetime('now', '-7 days') "
                "AND evaluation_score IS NOT NULL "
                "GROUP BY skill_name ORDER BY count DESC LIMIT 10"
            )
            if not rows:
                return "No skill usage data yet."
            lines = []
            for row in rows:
                avg = row["avg_score"] or 0
                lines.append(f"- {row['skill_name']} ({row['skill_type']}): {row['count']} uses, avg score {avg:.1f}")
            return "\n".join(lines)
        except Exception:
            return "Skill usage data not available."

    async def _get_skill_mining_summary(self) -> str:
        """Find repeated tool combinations that could become reusable skills."""
        try:
            rows = await self.db.fetch_all(
                "SELECT tools_used, COUNT(*) as count, AVG(evaluation_score) as avg_score "
                "FROM query_log WHERE tools_used IS NOT NULL "
                "AND created_at > datetime('now', '-7 days') "
                "AND evaluation_score > 0.7 "
                "GROUP BY tools_used HAVING count >= 3 "
                "ORDER BY count DESC LIMIT 5"
            )
            if not rows:
                return "No repeated patterns found yet."
            lines = []
            for row in rows:
                lines.append(
                    f"- Tools {row['tools_used']} used {row['count']}x "
                    f"with avg score {(row['avg_score'] or 0):.1f}"
                )
            return "\n".join(lines)
        except Exception:
            return "Skill mining data not available."

    async def _get_query_log_summary(self) -> str:
        """Summarize recent query classifications and their outcomes."""
        try:
            rows = await self.db.fetch_all(
                "SELECT classification, COUNT(*) as count, "
                "AVG(evaluation_score) as avg_score, "
                "AVG(duration_ms) as avg_duration, "
                "AVG(context_tokens) as avg_context_tokens, "
                "AVG(total_tokens) as avg_total_tokens "
                "FROM query_log "
                "WHERE created_at > datetime('now', '-7 days') "
                "AND evaluation_score IS NOT NULL "
                "GROUP BY classification "
                "ORDER BY count DESC"
            )
            if not rows:
                return "No query classification data yet."

            lines = []
            for row in rows:
                avg_score = row["avg_score"] or 0
                avg_dur = row["avg_duration"] or 0
                avg_ctx = row["avg_context_tokens"] or 0
                avg_total = row["avg_total_tokens"] or 0
                lines.append(
                    f"- {row['classification']}: {row['count']} queries, "
                    f"avg score {avg_score:.1f}, avg {avg_dur:.0f}ms, "
                    f"avg {avg_ctx:.0f} context tokens, avg {avg_total:.0f} total tokens"
                )
            return "\n".join(lines)
        except Exception:
            return "Query log not available."

    async def _get_outcome_summary(self) -> str:
        """Summarize recent plan outcome evaluations."""
        try:
            rows = await self.db.fetch_all(
                "SELECT status, COUNT(*) as count, AVG(outcome_score) as avg_score "
                "FROM plan_outcomes WHERE created_at > datetime('now', '-7 days') "
                "GROUP BY status"
            )
            if not rows:
                return "No plan outcome data yet."
            lines = []
            for row in rows:
                avg = row["avg_score"]
                avg_text = f", avg score {avg:.1f}" if avg is not None else ""
                lines.append(f"- {row['status']}: {row['count']} plans{avg_text}")
            return "\n".join(lines)
        except Exception:
            return "Plan outcome data not available."

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

    def _build_prompt_vars(self, eval_summary: dict, failed_trials: list, directions: list, query_log_summary: str = "", skill_usage_summary: str = "", skill_mining_summary: str = "", outcome_summary: str = "") -> dict[str, str]:
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

        return {
            "agent_description": self._agent_description or 'No description set',
            "agent_tools": ', '.join(self._agent_tools) if self._agent_tools else 'None listed',
            "task_summary": task_summary or 'No evaluations yet.',
            "failed_summary": failed_summary or 'None.',
            "direction_summary": direction_summary or 'No prior direction set.',
            "query_log_summary": query_log_summary or 'No query classification data yet.',
            "skill_usage_summary": skill_usage_summary or 'No skill usage data yet.',
            "skill_mining_summary": skill_mining_summary or 'No repeated patterns found yet.',
            "outcome_summary": outcome_summary or 'No plan outcome data yet.',
        }


