from unittest.mock import AsyncMock, MagicMock

import pytest

from odigos.core.agent_service import AgentService


@pytest.fixture
def service():
    return AgentService(
        agent=AsyncMock(),
        goal_store=AsyncMock(),
        budget_tracker=AsyncMock(),
        approval_gate=MagicMock(),
    )


class TestAgentService:
    async def test_handle_message(self, service):
        service.agent.handle_message.return_value = "Hello!"
        result = await service.handle_message(MagicMock())
        assert result == "Hello!"
        service.agent.handle_message.assert_called_once()

    async def test_list_goals(self, service):
        service.goal_store.list_goals.return_value = [{"id": "g1"}]
        result = await service.list_goals()
        assert len(result) == 1

    async def test_list_todos(self, service):
        service.goal_store.list_todos.return_value = [{"id": "t1"}]
        result = await service.list_todos()
        assert len(result) == 1

    async def test_list_reminders(self, service):
        service.goal_store.list_reminders.return_value = [{"id": "r1"}]
        result = await service.list_reminders()
        assert len(result) == 1

    async def test_cancel_item(self, service):
        service.goal_store.cancel.return_value = True
        result = await service.cancel_item("g1")
        assert result is True

    async def test_check_budget(self, service):
        service.budget_tracker.check_budget.return_value = MagicMock(within_budget=True)
        result = await service.check_budget()
        assert result.within_budget

    async def test_resolve_approval(self, service):
        service.approval_gate.resolve.return_value = True
        result = service.resolve_approval("a1", "approved")
        assert result is True

    async def test_heartbeat_pause_resume(self, service):
        service.agent.heartbeat = MagicMock(paused=False)
        service.pause_heartbeat()
        assert service.agent.heartbeat.paused is True
        service.resume_heartbeat()
        assert service.agent.heartbeat.paused is False

    async def test_no_approval_gate(self):
        service = AgentService(
            agent=AsyncMock(),
            goal_store=AsyncMock(),
            budget_tracker=AsyncMock(),
            approval_gate=None,
        )
        result = service.resolve_approval("a1", "approved")
        assert result is False
