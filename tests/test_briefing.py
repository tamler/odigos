"""Tests for morning briefing system."""
import pytest
from odigos.db import Database
from odigos.core.briefing import (
    gather_briefing_data,
    should_send_briefing,
    mark_briefing_sent,
)


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    await d.initialize()
    return d


class TestBriefingData:
    @pytest.mark.asyncio
    async def test_empty_briefing(self, db):
        """When there's nothing to report, returns all-clear message."""
        data = await gather_briefing_data(db)
        assert "No items" in data or "All clear" in data

    @pytest.mark.asyncio
    async def test_briefing_includes_todos(self, db):
        """Briefing should include pending todos."""
        await db.execute(
            "INSERT INTO todos (id, description, status, created_at) VALUES (?, ?, ?, datetime('now'))",
            ("t1", "Fix the landing page", "pending"),
        )
        data = await gather_briefing_data(db)
        assert "Fix the landing page" in data
        assert "Todos" in data

    @pytest.mark.asyncio
    async def test_briefing_includes_due_cards(self, db):
        """Briefing should include kanban cards due today."""
        await db.execute(
            "INSERT INTO kanban_boards (id, title, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("b1", "Project Alpha"),
        )
        await db.execute(
            "INSERT INTO kanban_columns (id, board_id, title, position, created_at, updated_at) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("c1", "b1", "To Do", 0),
        )
        await db.execute(
            "INSERT INTO kanban_cards (id, board_id, column_id, title, position, due_at, priority, created_at, updated_at) VALUES (?, ?, ?, ?, ?, datetime('now'), ?, datetime('now'), datetime('now'))",
            ("k1", "b1", "c1", "Ship v2", 0, "medium"),
        )
        data = await gather_briefing_data(db)
        assert "Ship v2" in data

    @pytest.mark.asyncio
    async def test_briefing_includes_goals(self, db):
        """Briefing should include active goals."""
        await db.execute(
            "INSERT INTO goals (id, description, status, created_at) VALUES (?, ?, ?, datetime('now'))",
            ("g1", "Launch by end of month", "active"),
        )
        data = await gather_briefing_data(db)
        assert "Launch by end of month" in data


class TestBriefingSchedule:
    @pytest.mark.asyncio
    async def test_should_send_first_time(self, db):
        """Should send briefing if never sent before."""
        assert await should_send_briefing(db) is True

    @pytest.mark.asyncio
    async def test_should_not_send_twice(self, db):
        """Should not send briefing twice on same day."""
        await mark_briefing_sent(db)
        assert await should_send_briefing(db) is False
