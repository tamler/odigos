"""Skill maturity lifecycle: progenitor -> committed -> mature."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Thresholds for maturity transitions
COMMIT_MIN_USES = 5
COMMIT_MIN_SCORE = 0.6
MATURE_MIN_USES = 20
MATURE_MIN_SCORE = 0.75
APOPTOSIS_MIN_USES = 5
APOPTOSIS_MAX_SCORE = 0.3
APOPTOSIS_FAIL_RATIO = 0.7


def evaluate_maturity(skill) -> str | None:
    """Evaluate if a skill should transition maturity levels.

    Returns new maturity level or None if no change.
    Returns "apoptosis" if the skill should be removed.
    """
    # Built-in skills are immune to demotion and apoptosis
    if skill.builtin:
        return None

    current = skill.maturity
    uses = skill.usage_count
    score = skill.avg_score
    fail_ratio = (
        skill.failure_count / max(skill.usage_count, 1)
    )

    # Check for apoptosis first (persistent failure)
    if uses >= APOPTOSIS_MIN_USES:
        if score < APOPTOSIS_MAX_SCORE:
            logger.info(
                "Skill '%s' marked for apoptosis "
                "(score=%.2f < %.2f after %d uses)",
                skill.name, score,
                APOPTOSIS_MAX_SCORE, uses,
            )
            return "apoptosis"
        if fail_ratio > APOPTOSIS_FAIL_RATIO:
            logger.info(
                "Skill '%s' marked for apoptosis "
                "(fail_ratio=%.2f > %.2f)",
                skill.name, fail_ratio,
                APOPTOSIS_FAIL_RATIO,
            )
            return "apoptosis"

    # Promotion: progenitor -> committed
    if current == "progenitor":
        if uses >= COMMIT_MIN_USES and score >= COMMIT_MIN_SCORE:
            logger.info(
                "Skill '%s' promoted: progenitor -> committed "
                "(uses=%d, score=%.2f)",
                skill.name, uses, score,
            )
            return "committed"

    # Promotion: committed -> mature
    if current == "committed":
        if uses >= MATURE_MIN_USES and score >= MATURE_MIN_SCORE:
            logger.info(
                "Skill '%s' promoted: committed -> mature "
                "(uses=%d, score=%.2f)",
                skill.name, uses, score,
            )
            return "mature"

    # Demotion: mature -> committed (if score drops)
    if current == "mature":
        if uses >= MATURE_MIN_USES and score < COMMIT_MIN_SCORE:
            logger.info(
                "Skill '%s' demoted: mature -> committed "
                "(score dropped to %.2f)",
                skill.name, score,
            )
            return "committed"

    return None


def update_skill_stats(
    skill, success: bool, score: float,
) -> None:
    """Update skill usage statistics after execution."""
    skill.usage_count += 1
    if success:
        skill.success_count += 1
    else:
        skill.failure_count += 1

    # Running average
    old_avg = skill.avg_score
    n = skill.usage_count
    skill.avg_score = old_avg + (score - old_avg) / n
    skill.last_used_at = (
        datetime.now(timezone.utc).isoformat()
    )
