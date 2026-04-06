"""Tests for the enhanced query planner output."""
import pytest
from odigos.core.classifier import QueryPlan, Needs


class TestNeeds:
    def test_defaults_all_false(self):
        n = Needs()
        assert n.rag is False
        assert n.user_profile is False
        assert n.user_facts is False
        assert n.history is False
        assert n.experiences is False

    def test_from_dict(self):
        n = Needs.from_dict({"rag": True, "history": True})
        assert n.rag is True
        assert n.history is True
        assert n.user_profile is False

    def test_from_empty_dict(self):
        n = Needs.from_dict({})
        assert n.rag is False


class TestQueryPlan:
    def test_basic_fields(self):
        plan = QueryPlan(
            classification="creative",
            confidence=0.9,
            intent="generate_music",
            tool_hint="generate_music",
            needs=Needs(experiences=True),
            response_style="brief",
            complexity="single_tool",
        )
        assert plan.tool_hint == "generate_music"
        assert plan.needs.experiences is True
        assert plan.needs.rag is False

    def test_default_plan(self):
        plan = QueryPlan.default()
        assert plan.classification == "standard"
        assert plan.tool_hint is None
        assert plan.needs.rag is False
        assert plan.response_style == "brief"

    def test_from_dict_full(self):
        raw = {
            "classification": "creative",
            "confidence": 0.9,
            "intent": "generate_music",
            "tool_hint": "generate_music",
            "needs": {"rag": False, "experiences": True},
            "search_queries": [],
            "response_style": "brief",
            "complexity": "single_tool",
        }
        plan = QueryPlan.from_dict(raw)
        assert plan.classification == "creative"
        assert plan.tool_hint == "generate_music"
        assert plan.needs.experiences is True
        assert plan.needs.rag is False

    def test_from_dict_missing_fields(self):
        raw = {"classification": "simple", "confidence": 0.8}
        plan = QueryPlan.from_dict(raw)
        assert plan.classification == "simple"
        assert plan.tool_hint is None
        assert plan.needs.rag is False
        assert plan.response_style == "brief"

    def test_from_dict_invalid_needs(self):
        raw = {"classification": "standard", "confidence": 0.5, "needs": "invalid"}
        plan = QueryPlan.from_dict(raw)
        assert plan.needs.rag is False  # falls back to default Needs
