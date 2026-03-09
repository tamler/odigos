"""Tests for the approval gate and channel registry."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from odigos.channels.base import Channel, ChannelRegistry
from odigos.core.approval import ApprovalGate


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.fixture
def gate(mock_db):
    return ApprovalGate(
        db=mock_db,
        tools_requiring_approval=["run_gws", "run_browser"],
        timeout=2,
    )


def test_requires_approval(gate):
    assert gate.requires_approval("run_gws")
    assert gate.requires_approval("run_browser")
    assert not gate.requires_approval("web_search")
    assert not gate.requires_approval("create_todo")


def test_add_remove_tool(gate):
    gate.add_tool("web_search")
    assert gate.requires_approval("web_search")
    gate.remove_tool("web_search")
    assert not gate.requires_approval("web_search")
    gate.remove_tool("nonexistent")


@pytest.mark.asyncio
async def test_approved(gate):
    async def approve_soon():
        await asyncio.sleep(0.05)
        for aid in list(gate._pending.keys()):
            gate.resolve(aid, "approved")

    asyncio.create_task(approve_soon())
    decision = await gate.request("run_gws", {"command": "test"}, "telegram:123")
    assert decision == "approved"


@pytest.mark.asyncio
async def test_denied(gate):
    async def deny_soon():
        await asyncio.sleep(0.05)
        for aid in list(gate._pending.keys()):
            gate.resolve(aid, "denied")

    asyncio.create_task(deny_soon())
    decision = await gate.request("run_gws", {"command": "test"}, "telegram:123")
    assert decision == "denied"


@pytest.mark.asyncio
async def test_timeout(gate):
    gate._timeout = 0.1
    decision = await gate.request("run_gws", {"command": "test"}, "telegram:123")
    assert decision == "timeout"


@pytest.mark.asyncio
async def test_resolve_unknown_id(gate):
    assert not gate.resolve("nonexistent-id", "approved")


@pytest.mark.asyncio
async def test_resolve_already_done(gate):
    async def resolve_twice():
        await asyncio.sleep(0.05)
        for aid in list(gate._pending.keys()):
            assert gate.resolve(aid, "approved")
            assert not gate.resolve(aid, "approved")

    asyncio.create_task(resolve_twice())
    decision = await gate.request("run_gws", {"command": "test"})
    assert decision == "approved"


@pytest.mark.asyncio
async def test_channel_registry_routes_notification(mock_db):
    """Approval gate routes notification through channel registry."""
    mock_channel = AsyncMock(spec=Channel)
    mock_channel.channel_name = "telegram"
    registry = ChannelRegistry()
    registry.register("telegram", mock_channel)

    gate = ApprovalGate(
        db=mock_db,
        tools_requiring_approval=["run_gws"],
        channel_registry=registry,
        timeout=0.1,
    )
    await gate.request("run_gws", {"command": "test"}, "telegram:123")
    mock_channel.send_approval_request.assert_awaited_once()
    call_args = mock_channel.send_approval_request.call_args
    assert call_args[0][1] == "run_gws"
    assert call_args[0][2] == "telegram:123"
    assert call_args[0][3] == {"command": "test"}


@pytest.mark.asyncio
async def test_channel_failure_does_not_block(mock_db):
    """If channel notification raises, the gate still times out gracefully."""
    mock_channel = AsyncMock(spec=Channel)
    mock_channel.send_approval_request = AsyncMock(side_effect=RuntimeError("send failed"))
    registry = ChannelRegistry()
    registry.register("telegram", mock_channel)

    gate = ApprovalGate(
        db=mock_db,
        tools_requiring_approval=["run_gws"],
        channel_registry=registry,
        timeout=0.1,
    )
    decision = await gate.request("run_gws", {"command": "test"}, "telegram:123")
    assert decision == "timeout"


@pytest.mark.asyncio
async def test_no_channel_for_conversation(mock_db):
    """No matching channel -- gate still works, just no notification."""
    registry = ChannelRegistry()
    gate = ApprovalGate(
        db=mock_db,
        tools_requiring_approval=["run_gws"],
        channel_registry=registry,
        timeout=0.1,
    )
    decision = await gate.request("run_gws", {"command": "test"}, "web:session-abc")
    assert decision == "timeout"


@pytest.mark.asyncio
async def test_no_conversation_id(mock_db):
    """No conversation_id -- no notification, still works."""
    gate = ApprovalGate(
        db=mock_db,
        tools_requiring_approval=["run_gws"],
        timeout=0.1,
    )
    decision = await gate.request("run_gws", {"command": "test"})
    assert decision == "timeout"


@pytest.mark.asyncio
async def test_db_records_created(mock_db, gate):
    gate._timeout = 0.1
    await gate.request("run_gws", {"command": "test"}, "conv1")
    assert mock_db.execute.call_count == 2
    insert_call = mock_db.execute.call_args_list[0]
    assert "INSERT INTO approvals" in insert_call[0][0]
    update_call = mock_db.execute.call_args_list[1]
    assert "UPDATE approvals" in update_call[0][0]
    assert "timeout" in update_call[0][1]


def test_gated_tools_property(gate):
    assert gate.gated_tools == {"run_gws", "run_browser"}


# ── ChannelRegistry tests ──────────────────────────────────────────


def test_registry_register_and_get():
    registry = ChannelRegistry()
    channel = MagicMock(spec=Channel)
    registry.register("telegram", channel)
    assert registry.get("telegram") is channel
    assert registry.get("web") is None


def test_registry_for_conversation():
    registry = ChannelRegistry()
    tg = MagicMock(spec=Channel)
    web = MagicMock(spec=Channel)
    registry.register("telegram", tg)
    registry.register("web", web)

    assert registry.for_conversation("telegram:123") is tg
    assert registry.for_conversation("web:session-abc") is web
    assert registry.for_conversation("unknown:xyz") is None
    assert registry.for_conversation("no-prefix") is None


def test_registry_all():
    registry = ChannelRegistry()
    tg = MagicMock(spec=Channel)
    web = MagicMock(spec=Channel)
    registry.register("telegram", tg)
    registry.register("web", web)
    assert len(registry.all()) == 2
