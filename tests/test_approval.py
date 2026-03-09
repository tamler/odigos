"""Tests for the approval gate."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

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
    # removing non-existent tool is a no-op
    gate.remove_tool("nonexistent")


@pytest.mark.asyncio
async def test_approved(gate):
    """Resolve approval before timeout."""
    async def approve_soon():
        await asyncio.sleep(0.05)
        # Find the pending approval and resolve it
        for aid in list(gate._pending.keys()):
            gate.resolve(aid, "approved")

    asyncio.create_task(approve_soon())
    decision = await gate.request("run_gws", {"command": "test"}, "telegram:123", 123)
    assert decision == "approved"


@pytest.mark.asyncio
async def test_denied(gate):
    """Resolve as denied."""
    async def deny_soon():
        await asyncio.sleep(0.05)
        for aid in list(gate._pending.keys()):
            gate.resolve(aid, "denied")

    asyncio.create_task(deny_soon())
    decision = await gate.request("run_gws", {"command": "test"}, "telegram:123", 123)
    assert decision == "denied"


@pytest.mark.asyncio
async def test_timeout(gate):
    """No resolution within timeout."""
    gate._timeout = 0.1
    decision = await gate.request("run_gws", {"command": "test"}, "telegram:123", 123)
    assert decision == "timeout"


@pytest.mark.asyncio
async def test_resolve_unknown_id(gate):
    """Resolving a non-existent approval returns False."""
    assert not gate.resolve("nonexistent-id", "approved")


@pytest.mark.asyncio
async def test_resolve_already_done(gate):
    """Double-resolve returns False."""
    async def resolve_twice():
        await asyncio.sleep(0.05)
        for aid in list(gate._pending.keys()):
            assert gate.resolve(aid, "approved")
            assert not gate.resolve(aid, "approved")

    asyncio.create_task(resolve_twice())
    decision = await gate.request("run_gws", {"command": "test"})
    assert decision == "approved"


@pytest.mark.asyncio
async def test_notify_fn_called(mock_db):
    """notify_fn is called with correct args."""
    notify = AsyncMock()
    gate = ApprovalGate(
        db=mock_db,
        tools_requiring_approval=["run_gws"],
        notify_fn=notify,
        timeout=0.1,
    )
    await gate.request("run_gws", {"command": "test"}, "conv123", 456)
    notify.assert_awaited_once()
    call_args = notify.call_args
    assert call_args[0][1] == "run_gws"  # tool_name
    assert call_args[0][2] == "conv123"  # conversation_id
    assert call_args[0][3] == {"command": "test"}  # arguments


@pytest.mark.asyncio
async def test_notify_fn_failure_does_not_block(mock_db):
    """If notify_fn raises, the gate still waits and times out gracefully."""
    notify = AsyncMock(side_effect=RuntimeError("notify failed"))
    gate = ApprovalGate(
        db=mock_db,
        tools_requiring_approval=["run_gws"],
        notify_fn=notify,
        timeout=0.1,
    )
    decision = await gate.request("run_gws", {"command": "test"})
    assert decision == "timeout"


@pytest.mark.asyncio
async def test_db_records_created(mock_db, gate):
    """DB insert and update are called."""
    gate._timeout = 0.1
    await gate.request("run_gws", {"command": "test"}, "conv1", 123)
    # Should have INSERT (pending) and UPDATE (timeout)
    assert mock_db.execute.call_count == 2
    insert_call = mock_db.execute.call_args_list[0]
    assert "INSERT INTO approvals" in insert_call[0][0]
    update_call = mock_db.execute.call_args_list[1]
    assert "UPDATE approvals" in update_call[0][0]
    assert "timeout" in update_call[0][1]


def test_gated_tools_property(gate):
    assert gate.gated_tools == {"run_gws", "run_browser"}
