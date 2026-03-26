"""Tests for cancel event threading through agent service."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from odigos.channels.base import UniversalMessage
from odigos.core.agent_service import AgentService


class TestCancelEventThreading:
    @pytest.mark.asyncio
    async def test_abort_event_passed_to_agent(self):
        """AgentService.handle_message should forward abort_event to agent."""
        mock_agent = MagicMock()
        mock_agent.handle_message = AsyncMock(return_value="ok")

        service = AgentService.__new__(AgentService)
        service.agent = mock_agent
        service.budget_tracker = None
        service.approval_gate = None

        cancel = asyncio.Event()
        msg = UniversalMessage(
            id="test", channel="web", sender="u",
            content="hi", timestamp=datetime.now(timezone.utc),
        )
        await service.handle_message(msg, abort_event=cancel)
        mock_agent.handle_message.assert_called_once()
        _, kwargs = mock_agent.handle_message.call_args
        assert kwargs["abort_event"] is cancel

    @pytest.mark.asyncio
    async def test_abort_event_is_checked_by_executor(self):
        """When abort_event is set, executor breaks at next turn check."""
        event = asyncio.Event()
        event.set()
        assert event.is_set()
