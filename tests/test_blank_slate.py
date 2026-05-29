"""Blank-slate smoke test (brittleness audit Phase B.1).

Boots a genuinely fresh agent database (no seeded data) and exercises the
common multi-step tool flows that were broken in the 2026-05-28 brittleness
incidents. The point is to catch the class of bug where a tool family can't
be used from an empty slate — missing create tools, FK explosions on
not-yet-created parents, truncated IDs the model can't reuse, etc.

Each flow calls the real tool classes the same way the executor does:
construct with the real DB, call execute({...}), assert on ToolResult.

These tests intentionally avoid the LLM — they exercise the deterministic
tool layer. LLM-in-the-loop behavior (find_tools loops, identity drift) is
covered separately; here we guarantee the tools themselves are sound from
a blank slate.

See docs/superpowers/specs/2026-05-28-brittleness-audit-and-robustness.md §3.5.
"""
from __future__ import annotations

import re

import pytest
import pytest_asyncio

from odigos.db import Database


# UUIDs look like 8-4-4-4-12 hex. The kanban brittleness bug was emitting
# 8-char prefixes that the model then tried to reuse as full IDs. Any ID a
# tool returns for the model to reuse must be a full UUID, never a prefix.
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# Also accept 32-char hex (uuid4().hex) since several stores use that form.
_HEX32_RE = re.compile(r"\b[0-9a-f]{32}\b")


def _extract_id(text: str, label: str) -> str:
    """Pull an ID that follows a 'label: <id>' marker in tool output.

    Tools must label IDs with the parameter name the model should reuse them
    as (board_id:, column_id:, card_id:, todo_id:, etc.) — never a bare 'id:'.
    """
    m = re.search(rf"{label}:\s*([0-9a-f-]{{16,}})", text)
    assert m, f"expected '{label}: <id>' in tool output, got:\n{text}"
    return m.group(1)


def _assert_full_id(value: str) -> None:
    assert _UUID_RE.fullmatch(value) or _HEX32_RE.fullmatch(value), (
        f"ID '{value}' is not a full UUID/hex32 — looks truncated. "
        "Tools must emit full IDs the model can reuse."
    )


@pytest_asyncio.fixture
async def fresh_db():
    """A real Database on a fresh in-memory SQLite with the full schema applied."""
    db = Database(":memory:")
    await db.initialize()
    yield db
    conn = getattr(db, "_conn", None)
    if conn is not None:
        await conn.close()


@pytest.mark.asyncio
async def test_kanban_from_blank_slate(fresh_db):
    """Create a board, then add cards to it — the exact flow that exploded
    on 2026-05-28 (no create_board tool, FK error, truncated IDs)."""
    from odigos.tools.kanban import KanbanCreateBoardTool, KanbanCreateCardTool, KanbanGetBoardTool

    create_board = KanbanCreateBoardTool(db=fresh_db)
    create_card = KanbanCreateCardTool(db=fresh_db)
    get_board = KanbanGetBoardTool(db=fresh_db)

    # 1. Create a board from nothing.
    res = await create_board.execute({"title": "Procurement Pilot"})
    assert res.success, f"create_board failed: {res.error}"
    board_id = _extract_id(res.data, "board_id")
    _assert_full_id(board_id)

    # The board response must give the model a usable column_id too.
    col_id = _extract_id(res.data, "column_id")
    _assert_full_id(col_id)

    # 2. Add a card using the IDs the board response handed back.
    res = await create_card.execute({
        "board_id": board_id,
        "column_id": col_id,
        "title": "vendor RFQ",
    })
    assert res.success, f"create_card failed: {res.error}"

    # 3. The board now reflects the card.
    res = await get_board.execute({"board_id": board_id})
    assert res.success, f"get_board failed: {res.error}"
    assert "vendor RFQ" in res.data


@pytest.mark.asyncio
async def test_kanban_create_card_without_board_gives_actionable_error(fresh_db):
    """Creating a card against a non-existent board must return a clear,
    recoverable error — not a raw 'FOREIGN KEY constraint failed'."""
    from odigos.tools.kanban import KanbanCreateCardTool

    create_card = KanbanCreateCardTool(db=fresh_db)
    res = await create_card.execute({
        "board_id": "does-not-exist",
        "column_id": "nope",
        "title": "orphan card",
    })
    assert not res.success
    assert "FOREIGN KEY" not in (res.error or ""), (
        "raw FK error leaked to the model; should be an actionable message"
    )
    assert "create_board" in (res.error or "").lower() or "no board" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_notebook_from_blank_slate(fresh_db, tmp_path, monkeypatch):
    """Create a notebook, append an entry, read it back — from an empty DB.

    Uses the real ManageNotebookTool API (verified against the source):
    action create|append|read|list, title for create, notebook_id+content
    for append. The side_effect carries the notebook_id the model reuses.

    append() triggers _backup() which writes to data/notebooks/ relative to
    CWD; chdir into tmp_path so the test doesn't pollute the repo working tree.
    """
    monkeypatch.chdir(tmp_path)
    from odigos.tools.notebook import ManageNotebookTool

    nb = ManageNotebookTool(db=fresh_db)

    # 1. Create a notebook (title-only create does not touch disk).
    res = await nb.execute({"action": "create", "title": "Field Notes"})
    assert res.success, f"create failed: {res.error}"
    nb_id = (res.side_effect or {}).get("notebook_id")
    assert nb_id, f"create did not return a notebook_id: {res.side_effect}"
    _assert_full_id(nb_id)

    # 2. It shows up in the list.
    res = await nb.execute({"action": "list"})
    assert res.success, f"list failed: {res.error}"
    assert "Field Notes" in res.data, f"created notebook not listed:\n{res.data}"

    # 3. Append an entry using the id the create handed back, then read it.
    res = await nb.execute({
        "action": "append", "notebook_id": nb_id, "content": "first observation",
    })
    assert res.success, f"append failed: {res.error}"

    res = await nb.execute({"action": "read", "notebook_id": nb_id})
    assert res.success, f"read failed: {res.error}"
    assert "first observation" in res.data


@pytest.mark.asyncio
async def test_goals_emit_full_ids(fresh_db):
    """create_todo / create_reminder / create_goal must return full IDs the
    model can reuse (the [:8] truncation bug)."""
    from odigos.core.goal_store import GoalStore
    from odigos.tools.goals import CreateGoalTool, CreateReminderTool, CreateTodoTool

    store = GoalStore(fresh_db)

    todo = CreateTodoTool(goal_store=store)
    res = await todo.execute({"description": "revise cardholder agreement"})
    assert res.success, f"create_todo failed: {res.error}"
    _assert_full_id(_extract_id(res.data, "todo_id"))

    goal = CreateGoalTool(goal_store=store)
    res = await goal.execute({"description": "launch hosted tier"})
    assert res.success, f"create_goal failed: {res.error}"
    _assert_full_id(_extract_id(res.data, "goal_id"))

    reminder = CreateReminderTool(goal_store=store)
    res = await reminder.execute({"description": "call vendor", "delay_seconds": 3600})
    assert res.success, f"create_reminder failed: {res.error}"
    _assert_full_id(_extract_id(res.data, "reminder_id"))
