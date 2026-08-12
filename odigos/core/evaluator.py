"""Evaluator: implicit feedback inference + C.1/C.2 LLM-based scoring.

Uses the fallback model for all evaluation calls to minimize cost.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING

from odigos.core.capabilities import TextBlob

from odigos.core.llm_prompt import run_prompt

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.providers.base import LLMProvider
    from odigos.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

# Keywords suggesting user is correcting the agent
_CORRECTION_MARKERS = [
    "no,", "no ", "actually", "i meant", "that's wrong", "not what i",
    "incorrect", "you misunderstood", "try again", "that's not",
]

# Keywords suggesting user is acknowledging/thanking
_POSITIVE_MARKERS = [
    "thanks", "thank you", "perfect", "great", "awesome", "that works",
    "makes sense", "got it", "exactly", "nice", "good job", "helpful",
]

# Feedback score constants for infer_implicit_feedback
FEEDBACK_NO_FOLLOWUP = -0.2
FEEDBACK_CORRECTION = -0.7
FEEDBACK_POSITIVE = 0.5
FEEDBACK_NEUTRAL = 0.2

def _analyze_user_sentiment(message: str) -> dict:
    """Analyze sentiment of a user message via TextBlob."""
    if TextBlob is not None:
        try:
            blob = TextBlob(message)
            return {
                "polarity": blob.sentiment.polarity,
                "subjectivity": blob.sentiment.subjectivity,
                "label": (
                    "positive"
                    if blob.sentiment.polarity > 0.1
                    else "negative"
                    if blob.sentiment.polarity < -0.1
                    else "neutral"
                ),
            }
        except Exception:
            pass
    return {
        "polarity": 0.0,
        "subjectivity": 0.0,
        "label": "neutral",
    }


_RUBRIC_FALLBACK = (
    "You are evaluating an AI assistant's response. "
    "Generate a scoring rubric for this type of interaction.\n\n"
    "User message: {user_content}\n"
    "Assistant response: {assistant_content}\n"
    "User reaction signal: {feedback} (-1=negative, +1=positive)\n\n"
    "Return ONLY a JSON object:\n"
    '{{"task_type": "category", "criteria": [{{"name": "...", "weight": 0.0-1.0, '
    '"description": "what good looks like"}}], "notes": "..."}}'
)

_SCORING_FALLBACK = (
    "Score this AI assistant interaction against the rubric.\n\n"
    "Rubric: {rubric}\n\n"
    "User message: {user_content}\n"
    "Assistant response: {assistant_content}\n"
    "User reaction signal: {feedback}\n\n"
    "Return ONLY a JSON object:\n"
    '{{"scores": [{{"criterion": "name", "score": 0-10, "observation": "..."}}], '
    '"overall": 0-10, "improvement_signal": "what would have been better" or null}}'
)


async def infer_implicit_feedback(
    db: Database, assistant_message_id: str, conversation_id: str
) -> float:
    """Infer user satisfaction from behavior after a response.

    Returns -1.0 to 1.0. Negative = dissatisfied, positive = satisfied.
    """
    asst_msg = await db.fetch_one(
        "SELECT created_at FROM messages WHERE id = ?", (assistant_message_id,)
    )
    if not asst_msg:
        return 0.0

    next_user = await db.fetch_one(
        "SELECT content, created_at FROM messages "
        "WHERE conversation_id = ? AND role = 'user' AND created_at > ? "
        "ORDER BY created_at ASC LIMIT 1",
        (conversation_id, asst_msg["created_at"]),
    )

    if next_user is None:
        return FEEDBACK_NO_FOLLOWUP

    content_lower = next_user["content"].lower().strip()

    for marker in _CORRECTION_MARKERS:
        if content_lower.startswith(marker) or marker in content_lower[:50]:
            return FEEDBACK_CORRECTION

    for marker in _POSITIVE_MARKERS:
        if marker in content_lower:
            return FEEDBACK_POSITIVE

    return FEEDBACK_NEUTRAL


# -- AREW-inspired critique signals (arxiv.org/abs/2603.12109) --
# Action Selection: did the agent use appropriate tools?
# Belief Tracking: did the agent use the information it retrieved?

_DOCUMENT_TOOLS = {"process_document", "run_code", "activate_skill"}
_SEARCH_TOOLS = {"web_search", "read_page", "read_feed"}
_MEMORY_TOOLS = {"remember_fact"}

# Tool categories that indicate active information gathering
_ACTIVE_TOOLS = _DOCUMENT_TOOLS | _SEARCH_TOOLS | {"run_code", "read_page", "scrape_page"}


async def compute_as_critique(
    db: Database, conversation_id: str, classification: str, tools_used: list[str],
) -> int:
    """Action Selection critique: did the agent use appropriate tools?

    Returns +1 (good tool use), -1 (should have used tools but didn't), or 0 (neutral).
    """
    has_active_tools = bool(set(tools_used) & _ACTIVE_TOOLS)

    # Document queries should use document-related tools
    if classification == "document_query" and not has_active_tools:
        return -1

    # Complex queries should use tools to gather information
    if classification == "complex" and not tools_used:
        return -1

    # If active tools were used, that's good regardless of classification
    if has_active_tools:
        return 1

    # Standard queries without tools -- neutral (might be fine for simple chat)
    return 0


async def compute_bt_critique(
    db: Database, conversation_id: str, assistant_content: str, tools_used: list[str],
) -> int:
    """Belief Tracking critique: did the agent use the information it retrieved?

    Returns +1 (integrated tool results), -1 (ignored tool results), or 0 (no tools used).
    """
    if not tools_used:
        return 0

    # Check if any tool results exist in this conversation's recent messages
    tool_results = await db.fetch_all(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'tool' "
        "ORDER BY created_at DESC LIMIT 5",
        (conversation_id,),
    )

    if not tool_results:
        return 0

    # Check if the assistant response references content from tool results
    # Simple heuristic: do any significant words from tool results appear in the response?
    response_lower = assistant_content.lower()
    tool_content = " ".join(r["content"][:500] for r in tool_results).lower()

    # Extract significant words from tool results (>5 chars, not common words)
    _COMMON = {"that", "this", "with", "from", "have", "been", "will", "would", "could",
               "should", "about", "their", "there", "which", "other", "error", "result",
               "units", "think", "answer", "please", "something", "anything", "everything",
               "information", "question", "response", "message"}
    tool_words = {w for w in tool_content.split() if len(w) > 5 and w not in _COMMON}

    if not tool_words:
        return 0

    # Count how many significant tool words appear in the response
    overlap = sum(1 for w in tool_words if w in response_lower)
    overlap_ratio = overlap / len(tool_words) if tool_words else 0

    if overlap_ratio > 0.1:
        return 1  # Agent used the information
    elif overlap_ratio < 0.02 and len(tools_used) > 0:
        return -1  # Agent had tool results but didn't reference them

    return 0


class Evaluator:
    """Scores past agent actions via rubric generation (C.1) and scoring (C.2)."""

    def __init__(
        self,
        db: Database,
        provider: LLMProvider,
        qualified_evaluator_min_score: float = 7.0,
        entity_graph=None,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self.db = db
        self.provider = provider
        self._qualified_evaluator_min_score = qualified_evaluator_min_score
        self.entity_graph = entity_graph
        self.skill_registry = skill_registry

    async def get_unscored_messages(self, limit: int = 5) -> list[dict]:
        """Find assistant messages that haven't been evaluated yet."""
        rows = await self.db.fetch_all(
            "SELECT m.id, m.conversation_id, m.content, m.created_at "
            "FROM messages m "
            "LEFT JOIN evaluations e ON m.id = e.message_id "
            "WHERE m.role = 'assistant' AND e.id IS NULL "
            "ORDER BY m.created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    async def evaluate_action(
        self,
        message_id: str,
        conversation_id: str,
        trial_id: str | None = None,
    ) -> dict | None:
        """Run C.1 (rubric) + C.2 (score) on a past action. Returns evaluation dict."""
        asst_msg = await self.db.fetch_one(
            "SELECT content, created_at FROM messages WHERE id = ?", (message_id,)
        )
        if not asst_msg:
            return None

        user_msg = await self.db.fetch_one(
            "SELECT content FROM messages "
            "WHERE conversation_id = ? AND role = 'user' AND created_at < ? "
            "ORDER BY created_at DESC LIMIT 1",
            (conversation_id, asst_msg["created_at"]),
        )
        user_content = user_msg["content"] if user_msg else "(no user message)"

        feedback = await infer_implicit_feedback(
            self.db, message_id, conversation_id,
        )

        # Sentiment analysis on user message
        sentiment = _analyze_user_sentiment(user_content)

        rubric = await self._get_or_generate_rubric(user_content, asst_msg["content"], feedback)
        if rubric is None:
            return None

        scores = await self._score_against_rubric(rubric, user_content, asst_msg["content"], feedback)
        if scores is None:
            return None

        eval_id = str(uuid.uuid4())
        task_type = rubric.get("task_type", "unknown")
        overall = scores.get("overall", 0.0)

        # AREW critique: compute AS and BT signals from tool usage
        as_score = 0
        bt_score = 0
        try:
            query_row = await self.db.fetch_one(
                "SELECT classification, tools_used FROM query_log "
                "WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 1",
                (conversation_id,),
            )
            if query_row:
                classification = query_row["classification"] or "standard"
                tools_used = json.loads(query_row["tools_used"]) if query_row["tools_used"] else []
                as_score = await compute_as_critique(
                    self.db, conversation_id, classification, tools_used,
                )
                bt_score = await compute_bt_critique(
                    self.db, conversation_id, asst_msg["content"], tools_used,
                )
                scores["as_critique"] = as_score
                scores["bt_critique"] = bt_score
                if as_score == -1:
                    logger.info("AS critique: agent should have used tools for %s query", classification)
                if bt_score == -1:
                    logger.info("BT critique: agent ignored tool results in conversation %s", conversation_id[:8])
        except Exception:
            logger.debug("Could not compute AREW critiques", exc_info=True)

        await self.db.execute(
            "INSERT INTO evaluations (id, message_id, conversation_id, task_type, "
            "rubric, scores, overall_score, improvement_signal, implicit_feedback, trial_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                eval_id,
                message_id,
                conversation_id,
                task_type,
                json.dumps(rubric),
                json.dumps(scores),
                overall,
                scores.get("improvement_signal"),
                feedback,
                trial_id,
            ),
        )

        await self._cache_rubric(task_type, rubric)

        # Entity extraction handled by post_response.py background call

        # Log improvement suggestion for strategist visibility
        suggested_improvement = scores.get("suggested_improvement")
        if suggested_improvement:
            logger.info("Eval improvement hint: %s", suggested_improvement[:200])

        # Link evaluation score to query_log
        try:
            await self.db.execute(
                "UPDATE query_log SET evaluation_score = ?, message_id = ? "
                "WHERE rowid = (SELECT rowid FROM query_log WHERE conversation_id = ? "
                "AND message_id IS NULL ORDER BY created_at DESC LIMIT 1)",
                (overall, message_id, conversation_id),
            )
        except Exception:
            pass  # query_log may not exist yet

        # Link evaluation score to skill usage
        try:
            await self.db.execute(
                "UPDATE skill_usage SET evaluation_score = ?, message_id = ? "
                "WHERE conversation_id = ? AND message_id IS NULL",
                (overall, message_id, conversation_id),
            )
        except Exception:
            pass

        # Update skill maturity stats
        await self._update_skill_maturity(
            conversation_id, overall,
        )

        return {
            "eval_id": eval_id,
            "task_type": task_type,
            "overall_score": overall,
            "implicit_feedback": feedback,
            "improvement_signal": scores.get("improvement_signal"),
            "suggested_improvement": scores.get(
                "suggested_improvement"
            ),
            "user_satisfaction_signal": scores.get(
                "user_satisfaction_signal"
            ),
            "as_critique": as_score,
            "bt_critique": bt_score,
            "user_sentiment": sentiment,
        }

    async def _update_skill_maturity(
        self, conversation_id: str, score: float,
    ) -> None:
        """Update maturity stats for skills used in this conversation."""
        if not self.skill_registry:
            return
        try:
            rows = await self.db.fetch_all(
                "SELECT skill_name FROM skill_usage "
                "WHERE conversation_id = ?",
                (conversation_id,),
            )
            if not rows:
                return

            from odigos.skills.maturity import (
                evaluate_maturity,
                update_skill_stats,
            )

            success = score >= 0.5
            for row in rows:
                skill_name = row["skill_name"]
                skill = self.skill_registry.get(skill_name)
                if not skill:
                    continue
                update_skill_stats(skill, success, score)
                new_level = evaluate_maturity(skill)
                if new_level == "apoptosis":
                    try:
                        self.skill_registry.delete(
                            skill_name,
                        )
                        logger.info(
                            "Apoptosis: removed skill '%s'",
                            skill_name,
                        )
                    except ValueError:
                        pass  # builtin or missing
                elif new_level is not None:
                    skill.maturity = new_level
                    self.skill_registry.save(skill_name)
                else:
                    self.skill_registry.save(skill_name)
        except Exception:
            logger.debug(
                "Failed to update skill maturity",
                exc_info=True,
            )

    async def _get_or_generate_rubric(
        self, user_content: str, assistant_content: str, feedback: float
    ) -> dict | None:
        return await run_prompt(
            self.provider,
            "evaluator_rubric.md",
            {
                "user_content": user_content[:500],
                "assistant_content": assistant_content[:500],
                "feedback": f"{feedback:.1f}",
            },
            _RUBRIC_FALLBACK,
            intelligence="background",
            max_tokens=300,
            temperature=0.2,
        )

    async def _score_against_rubric(
        self, rubric: dict, user_content: str, assistant_content: str, feedback: float
    ) -> dict | None:
        return await run_prompt(
            self.provider,
            "evaluator_scoring.md",
            {
                "rubric": json.dumps(rubric),
                "user_content": user_content[:500],
                "assistant_content": assistant_content[:500],
                "feedback": f"{feedback:.1f}",
            },
            _SCORING_FALLBACK,
            intelligence="background",
            max_tokens=300,
            temperature=0.2,
        )

    async def find_qualified_evaluator(self, task_type: str) -> dict | None:
        """Find a qualified peer to evaluate actions of this task type.

        Requirements:
        - Peer specialty matches task_type
        - Peer is online
        - Peer has allow_external_evaluation = 1
        - Peer has evolution_score > qualified_evaluator_min_score
        """
        row = await self.db.fetch_one(
            "SELECT * FROM agent_registry "
            "WHERE specialty = ? AND status = 'online' "
            "AND allow_external_evaluation = 1 AND evolution_score > ? "
            "ORDER BY evolution_score DESC LIMIT 1",
            (task_type, self._qualified_evaluator_min_score),
        )
        return dict(row) if row else None

    # -- Active tool output testing --

    async def evaluate_tool_output(
        self,
        tool_name: str,
        tool_params: dict,
        tool_result: str,
        user_query: str,
    ) -> dict:
        """Evaluate whether a tool output is relevant and useful.

        Returns dict with quality (0-10), relevant, complete,
        and issues fields.  Uses keyword overlap heuristics
        (no LLM call) for speed.
        """
        quality = 5
        relevant = True
        complete = True
        issues: str | None = None

        result_lower = (tool_result or "").lower()
        query_lower = (user_query or "").lower()
        result_len = len(result_lower.strip())

        # Empty / trivial result
        if result_len < 5:
            quality = 1
            complete = False
            issues = "empty or trivial result"
            relevant = False
        else:
            # Error / traceback detection
            _ERR_MARKERS = [
                "traceback", "error:", "exception:",
                "failed", "errno", "stack trace",
            ]
            has_error = any(
                m in result_lower for m in _ERR_MARKERS
            )
            if has_error:
                quality = max(quality - 4, 1)
                issues = "result contains error/traceback"
                complete = False

            # Keyword overlap for relevance
            query_words = {
                w for w in query_lower.split()
                if len(w) > 3
            }
            if query_words:
                hits = sum(
                    1 for w in query_words
                    if w in result_lower
                )
                ratio = hits / len(query_words)
                if ratio >= 0.3:
                    quality = min(quality + 3, 10)
                elif ratio == 0.0:
                    quality = max(quality - 2, 1)
                    relevant = False
                    if issues is None:
                        issues = "no keyword overlap with query"

            # Search tool specifics
            if "search" in tool_name.lower():
                if "no results" in result_lower:
                    quality = 2
                    complete = False
                    issues = "search returned no results"

            # Code execution specifics
            if tool_name in ("run_code", "execute_code"):
                if has_error:
                    quality = 2

            # File creation check
            if "create" in tool_name.lower():
                if "created" in result_lower or "saved" in result_lower:
                    quality = min(quality + 2, 10)
                elif "error" not in result_lower:
                    quality = min(quality + 1, 10)

        evaluation = {
            "quality": quality,
            "relevant": relevant,
            "complete": complete,
            "issues": issues,
        }

        # Persist to tool_evaluations table
        try:
            await self.db.execute(
                "INSERT INTO tool_evaluations "
                "(id, tool_name, quality_score, relevant, "
                "complete, issues, query_context, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (
                    str(uuid.uuid4()),
                    tool_name,
                    float(quality),
                    1 if relevant else 0,
                    1 if complete else 0,
                    issues,
                    user_query[:200] if user_query else None,
                ),
            )
        except Exception:
            logger.debug(
                "Could not persist tool evaluation",
                exc_info=True,
            )

        return evaluation

    # -- Sprint contracts for multi-step plans --

    _SPRINT_CONTRACT_FALLBACK = (
        "Given this plan:\n"
        "Goal: {goal}\n\n"
        "Steps:\n{steps}\n\n"
        "Generate testable success criteria for each step."
        " Each criterion should be:\n"
        "1. Specific and measurable\n"
        "2. Verifiable without asking the user\n"
        "3. Based on observable outcomes\n\n"
        "Respond with JSON:\n"
        '{{"criteria": [{{"step": 1, "test": "how to verify",'
        ' "metric": "measurable outcome"}}],'
        ' "overall_success": "what does done look like"}}'
    )

    async def generate_sprint_contract(
        self,
        goal: str,
        steps: list[dict],
    ) -> dict:
        """Generate testable success criteria for a plan.

        Returns dict with criteria list and overall_success.
        Uses an LLM call via run_prompt.
        """
        steps_text = "\n".join(
            f"{s.get('step', '?')}. {s.get('task', '')}"
            for s in steps
        )
        result = await run_prompt(
            self.provider,
            "sprint_contract.md",
            {"goal": goal, "steps": steps_text},
            self._SPRINT_CONTRACT_FALLBACK,
            intelligence="background",
            max_tokens=500,
            temperature=0.2,
        )
        if result and "criteria" in result:
            return result
        return {
            "criteria": [],
            "overall_success": "unknown",
        }

    async def _cache_rubric(self, task_type: str, rubric: dict) -> None:
        try:
            existing = await self.db.fetch_one(
                "SELECT task_type FROM rubric_cache WHERE task_type = ?", (task_type,)
            )
            if existing:
                await self.db.execute(
                    "UPDATE rubric_cache SET usage_count = usage_count + 1, "
                    "last_used_at = datetime('now') WHERE task_type = ?",
                    (task_type,),
                )
            else:
                await self.db.execute(
                    "INSERT INTO rubric_cache (task_type, rubric) VALUES (?, ?)",
                    (task_type, json.dumps(rubric)),
                )
        except Exception:
            pass


