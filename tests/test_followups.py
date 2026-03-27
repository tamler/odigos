"""Tests for follow-up detection module."""
from odigos.core.followups import (
    COMMITMENT_PATTERNS,
    format_followup_notification,
)


def test_format_followup_empty():
    """Returns empty string for no commitments."""
    assert format_followup_notification([]) == ""


def test_format_followup_items():
    """Formats correctly with items."""
    commitments = [
        {
            "message_id": "m1",
            "content": "I need to finish the report",
            "pattern": "i need to",
            "created_at": "2026-03-27T10:00:00",
        },
        {
            "message_id": "m2",
            "content": "I will call the dentist by tomorrow",
            "pattern": "i will",
            "created_at": "2026-03-27T11:00:00",
        },
    ]
    result = format_followup_notification(commitments)
    assert "You mentioned these recently" in result
    assert "I need to finish the report" in result
    assert "I will call the dentist by tomorrow" in result
    # Each item should be on its own line with a dash
    lines = result.strip().split("\n")
    assert len(lines) == 3  # header + 2 items
    assert lines[1].startswith("- ")
    assert lines[2].startswith("- ")


def test_commitment_patterns():
    """Verify the patterns list is reasonable."""
    assert len(COMMITMENT_PATTERNS) > 0
    for pattern in COMMITMENT_PATTERNS:
        assert pattern == pattern.lower(), (
            f"Pattern should be lowercase: {pattern}"
        )
        assert len(pattern) > 0
