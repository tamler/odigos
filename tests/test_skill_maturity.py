"""Tests for the skill maturity lifecycle."""
from __future__ import annotations

from odigos.skills.maturity import (
    APOPTOSIS_FAIL_RATIO,
    APOPTOSIS_MAX_SCORE,
    APOPTOSIS_MIN_USES,
    COMMIT_MIN_SCORE,
    COMMIT_MIN_USES,
    MATURE_MIN_SCORE,
    MATURE_MIN_USES,
    evaluate_maturity,
    update_skill_stats,
)
from odigos.skills.registry import Skill


def _make_skill(
    name: str = "test-skill",
    maturity: str = "progenitor",
    usage_count: int = 0,
    success_count: int = 0,
    failure_count: int = 0,
    avg_score: float = 0.0,
    builtin: bool = False,
) -> Skill:
    return Skill(
        name=name,
        description="A test skill",
        tools=[],
        complexity="standard",
        system_prompt="Do the thing.",
        builtin=builtin,
        maturity=maturity,
        usage_count=usage_count,
        success_count=success_count,
        failure_count=failure_count,
        avg_score=avg_score,
    )


def test_progenitor_to_committed():
    skill = _make_skill(
        maturity="progenitor",
        usage_count=COMMIT_MIN_USES,
        avg_score=COMMIT_MIN_SCORE,
    )
    result = evaluate_maturity(skill)
    assert result == "committed"


def test_committed_to_mature():
    skill = _make_skill(
        maturity="committed",
        usage_count=MATURE_MIN_USES,
        avg_score=MATURE_MIN_SCORE,
    )
    result = evaluate_maturity(skill)
    assert result == "mature"


def test_apoptosis_low_score():
    skill = _make_skill(
        maturity="progenitor",
        usage_count=APOPTOSIS_MIN_USES,
        avg_score=APOPTOSIS_MAX_SCORE - 0.01,
    )
    result = evaluate_maturity(skill)
    assert result == "apoptosis"


def test_apoptosis_high_failure():
    total = APOPTOSIS_MIN_USES + 5
    failures = int(total * (APOPTOSIS_FAIL_RATIO + 0.1)) + 1
    skill = _make_skill(
        maturity="committed",
        usage_count=total,
        failure_count=failures,
        success_count=total - failures,
        avg_score=0.5,
    )
    assert failures / total > APOPTOSIS_FAIL_RATIO
    result = evaluate_maturity(skill)
    assert result == "apoptosis"


def test_no_change_insufficient_uses():
    skill = _make_skill(
        maturity="progenitor",
        usage_count=COMMIT_MIN_USES - 1,
        avg_score=0.9,
    )
    result = evaluate_maturity(skill)
    assert result is None


def test_demotion_mature_to_committed():
    skill = _make_skill(
        maturity="mature",
        usage_count=MATURE_MIN_USES,
        avg_score=COMMIT_MIN_SCORE - 0.01,
    )
    result = evaluate_maturity(skill)
    assert result == "committed"


def test_update_stats():
    skill = _make_skill()
    update_skill_stats(skill, success=True, score=0.8)
    assert skill.usage_count == 1
    assert skill.success_count == 1
    assert skill.failure_count == 0
    assert skill.avg_score == 0.8
    assert skill.last_used_at != ""

    update_skill_stats(skill, success=False, score=0.4)
    assert skill.usage_count == 2
    assert skill.success_count == 1
    assert skill.failure_count == 1
    assert abs(skill.avg_score - 0.6) < 1e-9

    update_skill_stats(skill, success=True, score=0.9)
    assert skill.usage_count == 3
    expected = 0.6 + (0.9 - 0.6) / 3
    assert abs(skill.avg_score - expected) < 1e-9


def test_builtin_immune():
    skill = _make_skill(
        builtin=True,
        maturity="mature",
        usage_count=MATURE_MIN_USES,
        avg_score=0.1,
    )
    result = evaluate_maturity(skill)
    assert result is None

    skill2 = _make_skill(
        builtin=True,
        maturity="progenitor",
        usage_count=APOPTOSIS_MIN_USES + 10,
        avg_score=0.1,
        failure_count=APOPTOSIS_MIN_USES + 10,
    )
    result2 = evaluate_maturity(skill2)
    assert result2 is None
