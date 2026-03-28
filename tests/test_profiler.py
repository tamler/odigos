"""Tests for the structured user profiler."""
from __future__ import annotations

import math

import pytest

from odigos.core.profiler import (
    EMA_ALPHA,
    UserProfile,
    analyze_message_signals,
    format_profile_for_context,
    update_dimension,
)


def test_ema_update():
    """EMA moves current toward observation by alpha fraction."""
    result = update_dimension(0.5, 1.0, alpha=0.3)
    expected = 0.5 + 0.3 * (1.0 - 0.5)
    assert math.isclose(result, expected, rel_tol=1e-9)

    # Repeated updates converge toward observation
    val = 0.0
    for _ in range(50):
        val = update_dimension(val, 1.0, alpha=0.3)
    assert val > 0.99


def test_ema_stays_when_equal():
    """EMA does not change when observation equals current."""
    result = update_dimension(0.7, 0.7, alpha=0.3)
    assert math.isclose(result, 0.7, rel_tol=1e-9)


def test_analyze_short_message():
    """Short message produces low verbosity signal."""
    signals = analyze_message_signals("hi there")
    assert "verbosity_preference" in signals
    assert signals["verbosity_preference"] <= 0.2


def test_analyze_long_message():
    """Long message produces high verbosity signal."""
    msg = " ".join(["word"] * 60)
    signals = analyze_message_signals(msg)
    assert signals["verbosity_preference"] >= 0.8


def test_analyze_technical_message():
    """Technical keywords are detected."""
    msg = "deploy the api server with docker and debug the sql query"
    signals = analyze_message_signals(msg)
    assert "technical_depth" in signals
    assert signals["technical_depth"] > 0.3
    assert "coding_expertise" in signals
    assert signals["coding_expertise"] > 0.3


def test_analyze_correction():
    """Correction patterns are detected."""
    for start in ["no", "wrong", "actually"]:
        msg = f"{start}, that is not what I meant"
        signals = analyze_message_signals(msg)
        assert signals.get("correction_frequency", 0) >= 0.8, (
            f"Failed for: {start}"
        )


def test_analyze_imperative():
    """Imperative commands signal delegation comfort."""
    msg = "deploy the application to production"
    signals = analyze_message_signals(msg)
    assert signals.get("delegation_comfort", 0) >= 0.7
    assert signals.get("prefers_actions", 0) >= 0.7


def test_analyze_question():
    """Questions signal preference for explanations."""
    msg = "why does the database lock up under load?"
    signals = analyze_message_signals(msg)
    assert signals.get("prefers_explanations", 0) >= 0.7


def test_analyze_code_preference():
    """Code-related messages signal code preference."""
    msg = "write me a script to parse the logs"
    signals = analyze_message_signals(msg)
    assert signals.get("prefers_code", 0) >= 0.7


def test_analyze_non_user_role():
    """Non-user roles produce no signals."""
    signals = analyze_message_signals("hello world", role="assistant")
    assert signals == {}


def test_profile_serialization():
    """Round-trip through JSON preserves all fields."""
    p = UserProfile(
        verbosity_preference=0.8,
        coding_expertise=0.9,
        relationship_stage="deep",
        interaction_count=42,
    )
    json_str = p.to_json()
    restored = UserProfile.from_json(json_str)
    assert restored.verbosity_preference == 0.8
    assert restored.coding_expertise == 0.9
    assert restored.relationship_stage == "deep"
    assert restored.interaction_count == 42


def test_profile_from_dict_ignores_unknown():
    """Unknown keys in dict are silently ignored."""
    data = {"verbosity_preference": 0.7, "unknown_field": 999}
    p = UserProfile.from_dict(data)
    assert p.verbosity_preference == 0.7
    assert not hasattr(p, "unknown_field")


def test_default_profile():
    """New profile has reasonable defaults."""
    p = UserProfile()
    assert p.verbosity_preference == 0.5
    assert p.emoji_tolerance == 0.0
    assert p.coding_expertise == 0.3
    assert p.relationship_stage == "new"
    assert p.primary_use_case == "general"
    assert p.interaction_count == 0


def test_format_for_context_basic():
    """Format produces readable output with header."""
    p = UserProfile()
    text = format_profile_for_context(p)
    assert "## User Profile (Structured)" in text
    assert "Relationship: new" in text
    assert "Primary use: general" in text


def test_format_for_context_high_coding():
    """High coding expertise appears in output."""
    p = UserProfile(coding_expertise=0.8)
    text = format_profile_for_context(p)
    assert "coding" in text.lower()


def test_format_for_context_high_delegation():
    """High delegation comfort appears in output."""
    p = UserProfile(delegation_comfort=0.8)
    text = format_profile_for_context(p)
    assert "autonomous" in text.lower()


def test_format_for_context_correction_warning():
    """High correction frequency triggers precision note."""
    p = UserProfile(correction_frequency=0.8)
    text = format_profile_for_context(p)
    assert "precise" in text.lower()


def test_format_verbose_detailed():
    """High verbosity shows 'detailed'."""
    p = UserProfile(verbosity_preference=0.8)
    text = format_profile_for_context(p)
    assert "detailed" in text


def test_format_verbose_concise():
    """Low verbosity shows 'concise'."""
    p = UserProfile(verbosity_preference=0.2)
    text = format_profile_for_context(p)
    assert "concise" in text
