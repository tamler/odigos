"""Charter 01-cleanup.md §1: evolution must be off unless explicitly enabled.

Trial promotion writes LLM-generated text into data/agent/*.md, including
identity.md and guardrails.md. Those trials are scored against a treatment that
is never applied -- checkpoint_manager.get_working_sections() is reached only
from the unreachable ContextAssembler.build() (charter §3) -- so the engine
promotes on noise. It ran by default.
"""
from types import SimpleNamespace

import pytest

from odigos.config import EvolutionConfig
from odigos.core.heartbeat import maintenance


def test_evolution_is_disabled_by_default():
    assert EvolutionConfig().enabled is False


def _heartbeat(enabled: bool):
    """Minimal heartbeat double recording which engine calls were made."""
    calls = []

    class _Engine:
        async def score_past_actions(self, limit=3):
            calls.append("score_past_actions")
            return 0

        async def check_active_trial(self):
            calls.append("check_active_trial")
            return None

        async def rollup_domain_performance(self):
            calls.append("rollup_domain_performance")

    class _Strategist:
        async def should_run(self):
            calls.append("strategist.should_run")
            return False

    hb = SimpleNamespace(
        evolution_engine=_Engine(),
        strategist=_Strategist(),
        settings=SimpleNamespace(evolution=EvolutionConfig(enabled=enabled)),
    )
    return hb, calls


async def test_disabled_heartbeat_does_not_touch_the_evolution_engine():
    hb, calls = _heartbeat(enabled=False)
    await maintenance.run_evolution(hb)
    assert calls == [], f"evolution ran while disabled: {calls}"


async def test_enabled_heartbeat_still_runs_the_cycle():
    hb, calls = _heartbeat(enabled=True)
    await maintenance.run_evolution(hb)
    assert "check_active_trial" in calls, "enabling evolution must restore the cycle"
    assert "score_past_actions" in calls
    assert "strategist.should_run" in calls


def _with_consolidator(hb, calls):
    class _Consolidator:
        async def consolidate(self):
            calls.append("consolidate")
            return {"corrections_processed": 0}

    hb.consolidator = _Consolidator()
    return hb


async def test_consolidation_is_gated_too():
    """PromptConsolidator writes LLM text into data/agent/.

    An earlier version of this test asserted the opposite, on the reasoning that
    consolidation is "user-driven". Adversarial review showed that is false:
    consolidation.py:44 takes sections_dir="data/agent" and generates the text
    with self._llm.complete(), writing operational_rules.md and
    behavioral_principles.md. It is grounded in user corrections, but the text
    written is LLM-generated, into the directory evolution.enabled protects.
    """
    hb, calls = _heartbeat(enabled=False)
    await maintenance.run_evolution(_with_consolidator(hb, calls))
    assert "consolidate" not in calls, (
        "consolidation writes LLM-generated text into data/agent/ and must obey "
        "evolution.enabled"
    )


async def test_consolidation_runs_when_evolution_is_enabled():
    hb, calls = _heartbeat(enabled=True)
    await maintenance.run_evolution(_with_consolidator(hb, calls))
    assert "consolidate" in calls


@pytest.mark.parametrize("settings", [None, SimpleNamespace(evolution=None)])
async def test_missing_settings_fails_closed(settings):
    hb, calls = _heartbeat(enabled=True)
    hb.settings = settings
    await maintenance.run_evolution(hb)
    assert calls == [], "absent config must mean disabled, not enabled"


async def test_skill_reverification_is_gated_too(monkeypatch):
    """LLM-scored and can demote a skill, so it obeys evolution.enabled."""
    called = []

    async def _fake(hb):
        called.append("reverify")

    monkeypatch.setattr(maintenance, "_reverify_one_skill", _fake)

    hb, _ = _heartbeat(enabled=False)
    hb.skill_verifier = object()
    hb.skill_registry = object()
    await maintenance.run_evolution(hb)
    assert called == [], "skill re-verification ran while evolution was disabled"

    hb, _ = _heartbeat(enabled=True)
    hb.skill_verifier = object()
    hb.skill_registry = object()
    await maintenance.run_evolution(hb)
    assert called == ["reverify"]
