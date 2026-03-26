"""Tests for fitness functions and trial pattern learning."""
import pytest
from odigos.db import Database
from odigos.core.fitness import (
    create_fitness_function,
    list_fitness_functions,
    update_fitness_score,
    get_fitness_summary,
    store_trial_pattern,
    get_trial_patterns_summary,
    get_evolution_mode,
    set_evolution_mode,
)


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    await d.initialize()
    return d


class TestFitnessFunctions:
    @pytest.mark.asyncio
    async def test_create_and_list(self, db):
        func_id = await create_fitness_function(
            db, name="Response Speed", description="Faster responses",
            metric="response_time", target_score=8.0,
        )
        functions = await list_fitness_functions(db)
        assert len(functions) == 1
        assert functions[0]["name"] == "Response Speed"
        assert functions[0]["target_score"] == 8.0

    @pytest.mark.asyncio
    async def test_update_score(self, db):
        func_id = await create_fitness_function(
            db, name="Accuracy", description="Better recall",
            metric="recall_accuracy", target_score=9.0,
        )
        await update_fitness_score(db, func_id, 7.5)
        functions = await list_fitness_functions(db)
        assert functions[0]["current_score"] == 7.5

    @pytest.mark.asyncio
    async def test_summary_format(self, db):
        await create_fitness_function(
            db, name="Speed", description="Be faster",
            metric="speed", target_score=8.0, weight=2.0,
        )
        summary = await get_fitness_summary(db)
        assert "Speed" in summary
        assert "speed" in summary
        assert "weight=2.0" in summary

    @pytest.mark.asyncio
    async def test_empty_summary(self, db):
        summary = await get_fitness_summary(db)
        assert "No fitness functions" in summary


class TestTrialPatterns:
    @pytest.mark.asyncio
    async def test_store_and_retrieve(self, db):
        await store_trial_pattern(
            db, trial_id="t1", pattern_type="success",
            target="prompt_section", target_name="voice",
            hypothesis="Made voice more friendly",
            score_delta=1.5,
        )
        summary = await get_trial_patterns_summary(db)
        assert "Successful" in summary
        assert "Made voice more friendly" in summary

    @pytest.mark.asyncio
    async def test_failure_pattern(self, db):
        await store_trial_pattern(
            db, trial_id="t2", pattern_type="failure",
            target="prompt_section", target_name="identity",
            hypothesis="Changed identity to be more formal",
            score_delta=-0.8,
        )
        summary = await get_trial_patterns_summary(db)
        assert "Failed" in summary


class TestEvolutionMode:
    @pytest.mark.asyncio
    async def test_default_mode(self, db):
        mode = await get_evolution_mode(db)
        assert mode == "continuous"

    @pytest.mark.asyncio
    async def test_set_mode(self, db):
        await set_evolution_mode(db, "supervised")
        mode = await get_evolution_mode(db)
        assert mode == "supervised"

    @pytest.mark.asyncio
    async def test_invalid_mode(self, db):
        with pytest.raises(ValueError):
            await set_evolution_mode(db, "invalid_mode")
