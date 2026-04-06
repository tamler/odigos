"""Tests for XSkill experience store: retrieval, feedback, pruning."""
import json
import pytest


class TestGetLikelyTools:
    """Dynamic tool mapping from query_log."""

    @pytest.mark.asyncio
    async def test_returns_tools_from_query_log(self, fake_db):
        from odigos.core.context import _get_likely_tools
        await fake_db.execute(
            "INSERT INTO query_log (id, conversation_id, classification, tools_used, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("q1", "c1", "document_query", "search_documents,read_file", "2026-04-04T00:00:00"),
        )
        await fake_db.execute(
            "INSERT INTO query_log (id, conversation_id, classification, tools_used, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("q2", "c1", "document_query", "search_documents", "2026-04-04T00:00:00"),
        )
        tools = await _get_likely_tools(fake_db, "document_query")
        assert "search_documents" in tools
        assert "read_file" in tools

    @pytest.mark.asyncio
    async def test_returns_empty_for_unknown_classification(self, fake_db):
        from odigos.core.context import _get_likely_tools
        tools = await _get_likely_tools(fake_db, "nonexistent_type")
        assert tools == []

    @pytest.mark.asyncio
    async def test_handles_json_format_tools_used(self, fake_db):
        from odigos.core.context import _get_likely_tools
        await fake_db.execute(
            "INSERT INTO query_log (id, conversation_id, classification, tools_used, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("q1", "c1", "complex", json.dumps(["search_web", "run_code"]), "2026-04-04T00:00:00"),
        )
        tools = await _get_likely_tools(fake_db, "complex")
        assert "search_web" in tools
        assert "run_code" in tools

    @pytest.mark.asyncio
    async def test_skips_null_and_empty_tools_used(self, fake_db):
        from odigos.core.context import _get_likely_tools
        await fake_db.execute(
            "INSERT INTO query_log (id, conversation_id, classification, tools_used, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("q1", "c1", "simple", "", "2026-04-04T00:00:00"),
        )
        tools = await _get_likely_tools(fake_db, "simple")
        assert tools == []


class TestFallbackTools:
    def test_standard_has_search_tools(self):
        from odigos.core.context import _FALLBACK_TOOLS
        assert "search_web" in _FALLBACK_TOOLS["standard"]
        assert "search_documents" in _FALLBACK_TOOLS["standard"]

    def test_simple_has_core_tools(self):
        from odigos.core.context import _FALLBACK_TOOLS
        # Simple gets core tools for experience retrieval (not for injection)
        assert "simple" in _FALLBACK_TOOLS

    def test_creative_has_gen_tools(self):
        from odigos.core.context import _FALLBACK_TOOLS
        assert "generate_image" in _FALLBACK_TOOLS["creative"]
        assert "generate_music" in _FALLBACK_TOOLS["creative"]


class TestExperienceFeedback:
    """Executor updates experience confidence after tool execution."""

    @pytest.mark.asyncio
    async def test_success_boosts_confidence(self, fake_db):
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("e1", "search_web", "test", "test", "Try broader terms", 1, 0, 0.8, "sometimes",
             "2026-04-04T00:00:00", "2026-04-04T00:00:00"),
        )
        from odigos.core.executor import _update_experience_feedback
        await _update_experience_feedback(fake_db, "search_web", success=True, failure_category=None)
        row = await fake_db.fetch_one("SELECT times_applied, confidence FROM agent_experiences WHERE id = 'e1'")
        assert row["times_applied"] == 1
        assert row["confidence"] == pytest.approx(0.85, abs=0.01)

    @pytest.mark.asyncio
    async def test_failure_erodes_confidence(self, fake_db):
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("e1", "search_web", "test", "test", "Try broader terms", 1, 5, 0.8, "sometimes",
             "2026-04-04T00:00:00", "2026-04-04T00:00:00"),
        )
        from odigos.core.executor import _update_experience_feedback
        await _update_experience_feedback(fake_db, "search_web", success=False, failure_category="transient")
        row = await fake_db.fetch_one("SELECT confidence FROM agent_experiences WHERE id = 'e1'")
        assert row["confidence"] == pytest.approx(0.7, abs=0.01)

    @pytest.mark.asyncio
    async def test_input_error_does_not_erode(self, fake_db):
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("e1", "search_web", "test", "test", "Try broader terms", 1, 5, 0.8, "sometimes",
             "2026-04-04T00:00:00", "2026-04-04T00:00:00"),
        )
        from odigos.core.executor import _update_experience_feedback
        await _update_experience_feedback(fake_db, "search_web", success=False, failure_category="input")
        row = await fake_db.fetch_one("SELECT confidence FROM agent_experiences WHERE id = 'e1'")
        assert row["confidence"] == pytest.approx(0.8, abs=0.01)

    @pytest.mark.asyncio
    async def test_failure_does_not_erode_anti_patterns(self, fake_db):
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("e1", "search_web", "test", "test", "Avoid narrow queries", 0, 3, 0.9, "always",
             "2026-04-04T00:00:00", "2026-04-04T00:00:00"),
        )
        from odigos.core.executor import _update_experience_feedback
        await _update_experience_feedback(fake_db, "search_web", success=False, failure_category="transient")
        row = await fake_db.fetch_one("SELECT confidence FROM agent_experiences WHERE id = 'e1'")
        assert row["confidence"] == pytest.approx(0.9, abs=0.01)

    @pytest.mark.asyncio
    async def test_confidence_capped_at_1(self, fake_db):
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("e1", "search_web", "test", "test", "Tip", 1, 10, 0.98, "always",
             "2026-04-04T00:00:00", "2026-04-04T00:00:00"),
        )
        from odigos.core.executor import _update_experience_feedback
        await _update_experience_feedback(fake_db, "search_web", success=True, failure_category=None)
        row = await fake_db.fetch_one("SELECT confidence FROM agent_experiences WHERE id = 'e1'")
        assert row["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_confidence_floored_at_0(self, fake_db):
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("e1", "search_web", "test", "test", "Tip", 1, 0, 0.05, "rare",
             "2026-04-04T00:00:00", "2026-04-04T00:00:00"),
        )
        from odigos.core.executor import _update_experience_feedback
        await _update_experience_feedback(fake_db, "search_web", success=False, failure_category="transient")
        row = await fake_db.fetch_one("SELECT confidence FROM agent_experiences WHERE id = 'e1'")
        assert row["confidence"] >= 0.0


class TestExperiencePruning:
    @pytest.mark.asyncio
    async def test_prunes_stale_unused_experiences(self, fake_db):
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("old", "search_web", "test", "test", "Old tip", 1, 0, 0.5, "sometimes",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("fresh", "search_web", "test", "test", "Fresh tip", 1, 0, 0.8, "always",
             "2026-04-03T00:00:00", "2026-04-03T00:00:00"),
        )
        from odigos.core.heartbeat.profiling import prune_stale_experiences
        await prune_stale_experiences(fake_db)
        rows = await fake_db.fetch_all("SELECT id FROM agent_experiences")
        ids = [r["id"] for r in rows]
        assert "old" not in ids
        assert "fresh" in ids

    @pytest.mark.asyncio
    async def test_prunes_low_confidence_experiences(self, fake_db):
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("low", "search_web", "test", "test", "Bad tip", 1, 5, 0.1, "rare",
             "2026-04-03T00:00:00", "2026-04-03T00:00:00"),
        )
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("high", "search_web", "test", "test", "Good tip", 1, 10, 0.9, "always",
             "2026-04-03T00:00:00", "2026-04-03T00:00:00"),
        )
        from odigos.core.heartbeat.profiling import prune_stale_experiences
        await prune_stale_experiences(fake_db)
        rows = await fake_db.fetch_all("SELECT id FROM agent_experiences")
        ids = [r["id"] for r in rows]
        assert "low" not in ids
        assert "high" in ids
