"""Tests for idle research module."""
from odigos.core.idle_research import format_research_prompt


def test_format_research_prompt_empty():
    """Returns empty string for no opportunities."""
    assert format_research_prompt([]) == ""


def test_format_research_prompt_plans():
    """Formats incomplete_plan type correctly."""
    opportunities = [
        {
            "type": "incomplete_plan",
            "id": "plan-123",
            "description": "Migrate database to new schema",
        },
    ]
    result = format_research_prompt(opportunities)
    assert "Plan in progress" in result
    assert "Migrate database to new schema" in result
    assert "idle time" in result.lower()


def test_format_research_prompt_questions():
    """Formats unanswered_question type correctly."""
    opportunities = [
        {
            "type": "unanswered_question",
            "description": "How do I configure nginx?",
            "conversation_id": "conv-abc",
        },
    ]
    result = format_research_prompt(opportunities)
    assert "Unanswered question" in result
    assert "How do I configure nginx?" in result


def test_format_research_prompt_mixed():
    """Formats a mix of opportunity types."""
    opportunities = [
        {
            "type": "incomplete_plan",
            "id": "p1",
            "description": "Build API endpoint",
        },
        {
            "type": "unanswered_question",
            "description": "What is the best ORM?",
            "conversation_id": "c1",
        },
    ]
    result = format_research_prompt(opportunities)
    lines = result.strip().split("\n")
    assert len(lines) == 3  # header + 2 items
    assert "Plan in progress" in lines[1]
    assert "Unanswered question" in lines[2]
