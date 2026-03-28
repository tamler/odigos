"""Tests for context relevance scoring and pruning."""
from odigos.core.relevance import (
    score_section_relevance,
    prune_sections,
    ALWAYS_INCLUDE,
)


def test_score_empty_query():
    assert score_section_relevance("", "test", "content") == 0.0


def test_score_empty_content():
    assert score_section_relevance("hello", "test", "") == 0.0


def test_score_matching_content():
    score = score_section_relevance(
        "python programming tutorial",
        "memory_context",
        "This is a python programming tutorial for beginners",
    )
    assert score > 0.3


def test_score_no_overlap():
    score = score_section_relevance(
        "quantum physics research",
        "error_hints",
        "The weather today is sunny and warm",
    )
    assert score < 0.3


def test_always_include():
    assert "personality" in ALWAYS_INCLUDE
    assert "user_profile" in ALWAYS_INCLUDE


def test_prune_keeps_critical():
    sections = {
        "user_facts": "User likes tea",
        "active_plan": "Step 1 research",
        "page_context": "On notebook page",
    }
    result = prune_sections("anything", sections)
    assert "user_facts" in result
    assert "active_plan" in result


def test_prune_empty():
    assert prune_sections("hello", {}) == {}


def test_score_returns_float():
    s = score_section_relevance("test", "test", "test content")
    assert isinstance(s, float)
    assert 0.0 <= s <= 1.0
