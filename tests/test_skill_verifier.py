"""Tests for SkillVerifier — isolated quality validation."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from odigos.providers.base import LLMResponse
from odigos.skills.registry import Skill
from odigos.skills.verifier import (
    PASS_THRESHOLDS,
    ScenarioResult,
    SkillVerifier,
    VerificationResult,
)


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="test-model",
        tokens_in=10,
        tokens_out=20,
        cost_usd=0.0,
    )


def _make_skill(
    name: str = "test-skill",
    description: str = "A test skill that does something useful.",
    system_prompt: str = "You are a helpful test skill.",
) -> Skill:
    return Skill(
        name=name,
        description=description,
        tools=[],
        complexity="standard",
        system_prompt=system_prompt,
    )


def _make_verifier(llm_client, skill_registry=None, db=None) -> SkillVerifier:
    return SkillVerifier(
        llm_client=llm_client,
        prompts_dir="data/prompts",
        skill_registry=skill_registry,
        db=db,
    )


# ---------------------------------------------------------------------------
# TestVerify
# ---------------------------------------------------------------------------


class TestVerify:
    @pytest.mark.asyncio
    async def test_verify_passing_artifacts(self):
        """Mock LLM returns high scores — verify passes."""
        high_score_response = json.dumps(
            {
                "assertions": [
                    {"text": "Response addresses request", "passed": True},
                    {"text": "Output is well-structured", "passed": True},
                ],
                "scores": {
                    "relevance": 0.9,
                    "completeness": 0.85,
                    "quality": 0.9,
                    "no_hallucination": 1.0,
                },
                "overall_score": 0.91,
                "diagnostics": None,
            }
        )
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_make_llm_response(high_score_response))

        verifier = _make_verifier(llm)
        result = await verifier.verify(
            task_description="Summarize text clearly.",
            output_artifacts=[("Summarize this paragraph.", "Here is a clear summary.")],
        )

        assert result.passed is True
        assert result.overall_score >= PASS_THRESHOLDS[0]
        assert len(result.scenario_results) == 1

    @pytest.mark.asyncio
    async def test_verify_failing_artifacts(self):
        """Mock LLM returns low scores — verify fails with diagnostics."""
        low_score_response = json.dumps(
            {
                "assertions": [
                    {"text": "Response addresses request", "passed": False},
                    {"text": "Output is well-structured", "passed": False},
                ],
                "scores": {
                    "relevance": 0.2,
                    "completeness": 0.1,
                    "quality": 0.3,
                    "no_hallucination": 0.5,
                },
                "overall_score": 0.28,
                "diagnostics": "Response is off-topic and incomplete.",
            }
        )
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_make_llm_response(low_score_response))

        verifier = _make_verifier(llm)
        result = await verifier.verify(
            task_description="Summarize text clearly.",
            output_artifacts=[("Summarize this paragraph.", "I don't know what to say.")],
        )

        assert result.passed is False
        assert result.overall_score < PASS_THRESHOLDS[0]
        assert result.diagnostics is not None
        assert len(result.diagnostics) > 0

    @pytest.mark.asyncio
    async def test_verify_averages_multiple_artifacts(self):
        """Two artifacts with different scores — verify averages them."""
        high_response = json.dumps(
            {
                "assertions": [{"text": "Good", "passed": True}],
                "scores": {
                    "relevance": 1.0,
                    "completeness": 1.0,
                    "quality": 1.0,
                    "no_hallucination": 1.0,
                },
                "overall_score": 0.8,
                "diagnostics": None,
            }
        )
        low_response = json.dumps(
            {
                "assertions": [{"text": "Bad", "passed": False}],
                "scores": {
                    "relevance": 0.2,
                    "completeness": 0.2,
                    "quality": 0.2,
                    "no_hallucination": 0.2,
                },
                "overall_score": 0.4,
                "diagnostics": "Poor output.",
            }
        )
        llm = AsyncMock()
        llm.complete = AsyncMock(
            side_effect=[
                _make_llm_response(high_response),
                _make_llm_response(low_response),
            ]
        )

        verifier = _make_verifier(llm)
        result = await verifier.verify(
            task_description="Do something.",
            output_artifacts=[
                ("Scenario A", "Good answer."),
                ("Scenario B", "Bad answer."),
            ],
        )

        assert len(result.scenario_results) == 2
        # Average of 0.8 and 0.4 = 0.6 — exactly at threshold, should pass at level 0
        assert abs(result.overall_score - 0.6) < 0.01


# ---------------------------------------------------------------------------
# TestVerifySkill
# ---------------------------------------------------------------------------


class TestVerifySkill:
    @pytest.mark.asyncio
    async def test_verify_skill_generates_scenarios_and_evaluates(self):
        """All three phases happen: scenario gen, skill exec, evaluation."""
        scenarios_response = json.dumps(
            {"scenarios": ["Do task A.", "Do task B.", "Do edge case C."]}
        )
        skill_response_1 = "Completed task A successfully."
        skill_response_2 = "Completed task B successfully."
        skill_response_3 = "Handled edge case C."

        eval_response = json.dumps(
            {
                "assertions": [{"text": "Response is relevant", "passed": True}],
                "scores": {
                    "relevance": 0.9,
                    "completeness": 0.85,
                    "quality": 0.88,
                    "no_hallucination": 0.95,
                },
                "overall_score": 0.89,
                "diagnostics": None,
            }
        )

        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            messages = kwargs.get("messages", [])
            # Call 1: scenario generation
            if call_count == 1:
                return _make_llm_response(scenarios_response)
            # Calls 2-4: skill execution (one per scenario)
            elif call_count in (2, 3, 4):
                idx = call_count - 2
                responses = [skill_response_1, skill_response_2, skill_response_3]
                return _make_llm_response(responses[idx])
            # Calls 5-7: evaluation (one per scenario)
            else:
                return _make_llm_response(eval_response)

        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=side_effect)

        skill = _make_skill()
        registry = MagicMock()
        registry.get = MagicMock(return_value=skill)

        verifier = _make_verifier(llm, skill_registry=registry)
        result = await verifier.verify_skill("test-skill")

        # All three phases must have happened: 1 scenario gen + 3 skill + 3 eval = 7 calls
        assert llm.complete.call_count == 7
        assert result.passed is True
        assert len(result.scenario_results) == 3

    @pytest.mark.asyncio
    async def test_verify_skill_returns_diagnostics_on_failure(self):
        """Skill produces bad output — verify fails with diagnostics."""
        scenarios_response = json.dumps({"scenarios": ["Do something hard."]})
        skill_response = "I cannot do that."

        eval_response = json.dumps(
            {
                "assertions": [{"text": "Response fails", "passed": False}],
                "scores": {
                    "relevance": 0.1,
                    "completeness": 0.1,
                    "quality": 0.1,
                    "no_hallucination": 0.5,
                },
                "overall_score": 0.2,
                "diagnostics": "Skill refused to perform the task.",
            }
        )

        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_llm_response(scenarios_response)
            elif call_count == 2:
                return _make_llm_response(skill_response)
            else:
                return _make_llm_response(eval_response)

        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=side_effect)

        skill = _make_skill()
        registry = MagicMock()
        registry.get = MagicMock(return_value=skill)

        verifier = _make_verifier(llm, skill_registry=registry)
        result = await verifier.verify_skill("test-skill")

        assert result.passed is False
        assert result.diagnostics is not None
        assert len(result.diagnostics) > 0


# ---------------------------------------------------------------------------
# TestEscalation
# ---------------------------------------------------------------------------


class TestEscalation:
    @pytest.mark.asyncio
    async def test_escalation_raises_threshold(self):
        """Score 0.7 passes levels 0-1, fails level 2."""

        def _make_eval_response(score: float, diag: str | None = None) -> str:
            payload = {
                "assertions": [{"text": "Test assertion", "passed": score >= 0.6}],
                "scores": {
                    "relevance": score,
                    "completeness": score,
                    "quality": score,
                    "no_hallucination": score,
                },
                "overall_score": score,
                "diagnostics": diag,
            }
            return json.dumps(payload)

        target_score = 0.7

        # Level 0 — threshold 0.6, score 0.7 → should pass
        llm0 = AsyncMock()
        llm0.complete = AsyncMock(
            return_value=_make_llm_response(_make_eval_response(target_score))
        )
        verifier0 = _make_verifier(llm0)
        result0 = await verifier0.verify(
            task_description="Do something.",
            output_artifacts=[("Scenario", "Response.")],
            escalation_level=0,
        )
        assert result0.passed is True, f"Level 0 should pass at score {target_score}"

        # Level 1 — threshold 0.7, score 0.7 → should pass (at threshold)
        llm1 = AsyncMock()
        llm1.complete = AsyncMock(
            return_value=_make_llm_response(_make_eval_response(target_score))
        )
        verifier1 = _make_verifier(llm1)
        result1 = await verifier1.verify(
            task_description="Do something.",
            output_artifacts=[("Scenario", "Response.")],
            escalation_level=1,
        )
        assert result1.passed is True, f"Level 1 should pass at score {target_score}"

        # Level 2 — threshold 0.8, score 0.7 → should fail
        llm2 = AsyncMock()
        llm2.complete = AsyncMock(
            return_value=_make_llm_response(
                _make_eval_response(target_score, "Score below escalated threshold.")
            )
        )
        verifier2 = _make_verifier(llm2)
        result2 = await verifier2.verify(
            task_description="Do something.",
            output_artifacts=[("Scenario", "Response.")],
            escalation_level=2,
        )
        assert result2.passed is False, f"Level 2 should fail at score {target_score}"


# ---------------------------------------------------------------------------
# TestIntegrationWithDB
# ---------------------------------------------------------------------------


class TestIntegrationWithDB:
    @pytest.mark.asyncio
    async def test_verify_skill_stores_verification_record(self, tmp_db_path):
        """Full flow: verify_skill stores a record in skill_verifications table."""
        from odigos.db import Database

        db = Database(tmp_db_path, migrations_dir="migrations")
        await db.initialize()

        try:
            scenarios_response = json.dumps({
                "scenarios": ["Write a haiku about coding"]
            })
            eval_response = json.dumps({
                "assertions": [{"text": "Is a haiku", "passed": True}],
                "scores": {"relevance": 0.9, "completeness": 0.9,
                           "quality": 0.9, "no_hallucination": 1.0},
                "overall_score": 0.93,
                "diagnostics": None,
            })

            async def mock_complete(**kwargs):
                msgs = kwargs.get("messages", [])
                content = msgs[0]["content"] if msgs else ""
                if "quality assurance" in content.lower():
                    return _make_llm_response(scenarios_response)
                elif "independent quality evaluator" in content.lower():
                    return _make_llm_response(eval_response)
                else:
                    return _make_llm_response("Code flows like streams\nBugs hide in the deepest lines\nTests reveal the truth")

            mock_llm = AsyncMock()
            mock_llm.complete = mock_complete
            mock_llm.default_model = "test/model"

            from odigos.skills.registry import SkillRegistry
            registry = SkillRegistry()
            registry._skills["haiku"] = Skill(
                name="haiku",
                description="Write haiku poems on any topic",
                tools=[],
                complexity="light",
                system_prompt="You are a haiku master. Write haikus.",
            )

            verifier = SkillVerifier(
                llm_client=mock_llm,
                prompts_dir="data/prompts",
                skill_registry=registry,
                db=db,
            )

            result = await verifier.verify_skill("haiku")

            assert result.passed is True
            assert result.overall_score > 0.6

            # Check DB record
            row = await db.fetch_one(
                "SELECT * FROM skill_verifications WHERE skill_name = 'haiku'"
            )
            assert row is not None
            assert row["overall_score"] > 0.6
            assert row["model_used"] == "test/model"
        finally:
            await db.close()
