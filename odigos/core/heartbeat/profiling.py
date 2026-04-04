"""Heartbeat background profiling: user analysis, experience extraction, plan evaluation."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from odigos.core.llm_prompt import run_prompt

if TYPE_CHECKING:
    from odigos.core.heartbeat_old import Heartbeat

logger = logging.getLogger(__name__)

_PROFILE_PROMPT_FALLBACK = (
    "Analyze recent conversations and update the user profile. "
    "Respond with JSON containing: communication_style, expertise_areas, "
    "preferences, recurring_topics, correction_patterns, summary, "
    "activity_pattern, engagement_trend, unmet_needs, relationship_stage."
)

_EXPERIENCE_FALLBACK = (
    "Analyze recent tool interactions and extract tactical lessons. "
    "Respond with a JSON array of objects with: tool_name, situation, outcome, lesson, success, "
    "confidence (0-1), applicability (always|sometimes|rare)."
)


async def dream_analyze_user(hb: "Heartbeat") -> None:
    """Analyze recent conversations to build/update the user profile."""
    try:
        profile = await hb.db.fetch_one(
            "SELECT * FROM user_profile WHERE id = 'owner'"
        )
        if not profile:
            return

        total_convs = await hb.db.fetch_one(
            "SELECT COUNT(*) as cnt FROM conversations"
        )
        conv_count = total_convs["cnt"] if total_convs else 0
        last_count = profile.get("conversation_count") or 0
        if conv_count - last_count < 5:
            return

        convs = await hb.db.fetch_all(
            "SELECT id, title FROM conversations ORDER BY created_at DESC LIMIT 20"
        )
        if not convs:
            return

        conv_ids = [c["id"] for c in convs]
        placeholders = ",".join("?" for _ in conv_ids)
        all_msgs = await hb.db.fetch_all(
            f"SELECT conversation_id, role, content FROM messages "
            f"WHERE conversation_id IN ({placeholders}) "
            f"ORDER BY timestamp ASC",
            tuple(conv_ids),
        )

        msgs_by_conv: dict[str, list] = {}
        for m in all_msgs:
            cid = m["conversation_id"]
            bucket = msgs_by_conv.setdefault(cid, [])
            if len(bucket) < 20:
                bucket.append(m)

        conv_texts = []
        for c in convs:
            msgs = msgs_by_conv.get(c["id"], [])
            if msgs:
                title = c.get("title") or c["id"][:8]
                lines = [f"### {title}"]
                for m in msgs:
                    content = (m["content"] or "")[:500]
                    lines.append(f"{m['role']}: {content}")
                conv_texts.append("\n".join(lines))

        if not conv_texts:
            return

        current_profile = (
            f"Communication style: {profile.get('communication_style') or '(unknown)'}\n"
            f"Expertise: {profile.get('expertise_areas') or '(unknown)'}\n"
            f"Preferences: {profile.get('preferences') or '(unknown)'}\n"
            f"Recurring topics: {profile.get('recurring_topics') or '(unknown)'}\n"
            f"Correction patterns: {profile.get('correction_patterns') or '(unknown)'}\n"
            f"Summary: {profile.get('summary') or '(none yet)'}"
        )

        parsed = await run_prompt(
            hb.provider,
            "user_profile.md",
            {
                "current_profile": current_profile,
                "conversations": "\n\n".join(conv_texts[:10]),
            },
            _PROFILE_PROMPT_FALLBACK,
            model=hb._background_model or None,
            max_tokens=800,
            temperature=0.3,
        )
        if parsed is None:
            return

        now = datetime.now(timezone.utc).isoformat()
        try:
            await hb.db.execute(
                "UPDATE user_profile SET "
                "communication_style = ?, expertise_areas = ?, preferences = ?, "
                "recurring_topics = ?, correction_patterns = ?, summary = ?, "
                "activity_pattern = ?, engagement_trend = ?, unmet_needs = ?, "
                "relationship_stage = ?, "
                "last_analyzed_at = ?, conversation_count = ? "
                "WHERE id = 'owner'",
                (
                    parsed.get("communication_style", ""),
                    parsed.get("expertise_areas", ""),
                    parsed.get("preferences", ""),
                    parsed.get("recurring_topics", ""),
                    parsed.get("correction_patterns", ""),
                    parsed.get("summary", ""),
                    parsed.get("activity_pattern", ""),
                    parsed.get("engagement_trend", ""),
                    parsed.get("unmet_needs", ""),
                    parsed.get("relationship_stage", "new"),
                    now,
                    conv_count,
                ),
            )
        except Exception:
            await hb.db.execute(
                "UPDATE user_profile SET "
                "communication_style = ?, expertise_areas = ?, preferences = ?, "
                "recurring_topics = ?, correction_patterns = ?, summary = ?, "
                "last_analyzed_at = ?, conversation_count = ? "
                "WHERE id = 'owner'",
                (
                    parsed.get("communication_style", ""),
                    parsed.get("expertise_areas", ""),
                    parsed.get("preferences", ""),
                    parsed.get("recurring_topics", ""),
                    parsed.get("correction_patterns", ""),
                    parsed.get("summary", ""),
                    now,
                    conv_count,
                ),
            )
        logger.info("User profile updated (analyzed %d conversations)", len(conv_texts))

        facts = parsed.get("facts", [])
        if facts and isinstance(facts, list):
            inserted = 0
            for item in facts:
                if not isinstance(item, dict) or not item.get("fact"):
                    continue
                fact_text = item["fact"].strip()
                category = item.get("category", "general")
                if category not in (
                    "personal", "professional", "preference",
                    "technical", "location", "general",
                ):
                    category = "general"
                existing = await hb.db.fetch_one(
                    "SELECT id FROM user_facts WHERE fact = ?", (fact_text,)
                )
                if existing:
                    continue
                fact_id = uuid.uuid4().hex
                await hb.db.execute(
                    "INSERT INTO user_facts (id, fact, category, source, confidence, created_at, updated_at) "
                    "VALUES (?, ?, ?, 'extracted', 0.8, ?, ?)",
                    (fact_id, fact_text, category, now, now),
                )
                inserted += 1
            if inserted:
                logger.info("Extracted %d new user facts from dreaming", inserted)
    except Exception:
        logger.debug("Dream user profile analysis failed", exc_info=True)


async def extract_experiences(hb: "Heartbeat") -> None:
    """Analyze recent tool interactions and extract tactical lessons."""
    try:
        error_rows = await hb.db.fetch_all(
            "SELECT tool_name, error_type, COUNT(*) as count, "
            "GROUP_CONCAT(error_message, ' | ') as messages "
            "FROM tool_errors WHERE created_at > datetime('now', '-1 day') "
            "GROUP BY tool_name, error_type ORDER BY count DESC LIMIT 10"
        )
        errors_text = "None" if not error_rows else "\n".join(
            f"- {r['tool_name']} ({r['error_type']}): {r['count']}x -- {(r['messages'] or '')[:200]}"
            for r in error_rows
        )

        success_rows = await hb.db.fetch_all(
            "SELECT tools_used, classification, AVG(evaluation_score) as avg_score, "
            "COUNT(*) as count "
            "FROM query_log WHERE evaluation_score > 0.7 "
            "AND created_at > datetime('now', '-1 day') "
            "AND tools_used IS NOT NULL "
            "GROUP BY tools_used ORDER BY avg_score DESC LIMIT 10"
        )
        successes_text = "None" if not success_rows else "\n".join(
            f"- {r['tools_used']} for {r['classification']}: {r['count']}x, avg score {(r['avg_score'] or 0):.1f}"
            for r in success_rows
        )

        if errors_text == "None" and successes_text == "None":
            return

        existing_rows = await hb.db.fetch_all(
            "SELECT tool_name, lesson FROM agent_experiences "
            "ORDER BY updated_at DESC LIMIT 20"
        )
        existing_text = "None" if not existing_rows else "\n".join(
            f"- {r['tool_name']}: {r['lesson']}" for r in existing_rows
        )

        experiences = await run_prompt(
            hb.provider,
            "experience_extraction.md",
            {
                "errors": errors_text,
                "successes": successes_text,
                "existing": existing_text,
            },
            _EXPERIENCE_FALLBACK,
            model=hb._background_model or None,
            max_tokens=600,
            temperature=0.3,
        )
        if not experiences or not isinstance(experiences, list):
            return

        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        for exp in experiences:
            if not isinstance(exp, dict) or not exp.get("lesson"):
                continue
            tool_name = exp.get("tool_name", "unknown")
            situation = exp.get("situation", "")
            outcome = exp.get("outcome", "")
            lesson = exp.get("lesson", "")
            success = 1 if exp.get("success", True) else 0

            existing = await hb.db.fetch_one(
                "SELECT id FROM agent_experiences WHERE lesson = ?",
                (lesson,),
            )
            if existing:
                continue

            confidence = exp.get("confidence", 0.8)
            if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
                confidence = 0.8
            applicability = exp.get("applicability", "sometimes")
            if applicability not in ("always", "sometimes", "rare"):
                applicability = "sometimes"

            exp_id = uuid.uuid4().hex
            try:
                await hb.db.execute(
                    "INSERT INTO agent_experiences "
                    "(id, tool_name, situation, outcome, lesson, success, times_applied, "
                    "confidence, applicability, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
                    (exp_id, tool_name, situation, outcome, lesson, success,
                     confidence, applicability, now, now),
                )
            except Exception:
                await hb.db.execute(
                    "INSERT INTO agent_experiences "
                    "(id, tool_name, situation, outcome, lesson, success, times_applied, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
                    (exp_id, tool_name, situation, outcome, lesson, success, now, now),
                )
            inserted += 1

        if inserted:
            logger.info("Extracted %d new tactical experiences", inserted)

    except Exception:
        logger.debug("Experience extraction failed", exc_info=True)


async def evaluate_plan_outcomes(hb: "Heartbeat") -> None:
    """Evaluate completed plans to determine if they achieved their goals."""
    try:
        pending = await hb.db.fetch_all(
            "SELECT po.plan_id, po.conversation_id "
            "FROM plan_outcomes po "
            "WHERE po.status = 'pending' "
            "LIMIT 3"
        )
        if not pending:
            return

        for row in pending:
            plan_id = row["plan_id"]
            conversation_id = row["conversation_id"]

            plan_row = await hb.db.fetch_one(
                "SELECT steps FROM task_plans WHERE id = ?", (plan_id,)
            )
            if not plan_row:
                await hb.db.execute(
                    "UPDATE plan_outcomes SET status = 'skipped', evaluated_at = datetime('now') "
                    "WHERE plan_id = ?",
                    (plan_id,),
                )
                continue

            import json
            steps = json.loads(plan_row["steps"])
            steps_text = "\n".join(
                f"- Step {s['step']}: {s['task']} [{s.get('status', 'pending')}]"
                + (f" -- {s['result']}" if s.get("result") else "")
                for s in steps
            )

            msgs = await hb.db.fetch_all(
                "SELECT role, content FROM messages "
                "WHERE conversation_id = ? ORDER BY timestamp DESC LIMIT 10",
                (conversation_id,),
            )
            conversation_text = "\n".join(
                f"{m['role']}: {(m['content'] or '')[:300]}" for m in reversed(msgs)
            ) if msgs else "(no conversation history)"

            result = await run_prompt(
                hb.provider,
                "outcome_evaluation.md",
                {"steps": steps_text, "conversation": conversation_text},
                (
                    "Evaluate whether this task plan achieved its intended goal.\n\n"
                    "Plan steps:\n{steps}\n\nConversation excerpt:\n{conversation}\n\n"
                    'Respond ONLY with valid JSON: {{"score": 0.0-1.0, "achieved": true/false, "summary": "one sentence"}}'
                ),
                model=hb._background_model or None,
                max_tokens=200,
                temperature=0.2,
            )

            now = datetime.now(timezone.utc).isoformat()
            if result:
                await hb.db.execute(
                    "UPDATE plan_outcomes SET status = 'evaluated', outcome_score = ?, "
                    "outcome_summary = ?, evaluated_at = ? WHERE plan_id = ?",
                    (result.get("score", 0.0), result.get("summary", ""), now, plan_id),
                )
                logger.info(
                    "Plan %s outcome: score=%.1f, %s",
                    plan_id[:8],
                    result.get("score", 0.0),
                    result.get("summary", "")[:80],
                )
            else:
                await hb.db.execute(
                    "UPDATE plan_outcomes SET status = 'failed', evaluated_at = ? WHERE plan_id = ?",
                    (now, plan_id),
                )
    except Exception:
        logger.debug("Plan outcome evaluation failed", exc_info=True)
