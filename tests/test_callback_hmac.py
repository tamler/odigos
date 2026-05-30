"""Tests for HMAC-signed task callback URLs.

The /api/callbacks/{task_id} endpoint is intentionally public (external APIs
can't carry our session/api-key), but it must verify an HMAC signature over the
task_id so a leaked task_id alone is not enough to POST completion data.
"""
from __future__ import annotations

import hashlib
import hmac

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from odigos.api.callbacks import _callback_sig, router as callbacks_router
from odigos.container import Container

_TEST_SECRET = "test-session-secret-for-callbacks"


class FakeDB:
    """Minimal async DB substitute backed by a dict, handling callback queries."""

    class _Row(dict):
        pass

    def __init__(self):
        self._tasks: dict[str, dict] = {}

    def seed_task(self, task_id: str, **fields):
        row = {
            "id": task_id,
            "type": "background_poll",
            "status": "pending",
            "tool_name": "generate_image",
            "external_task_id": "ext-123",
            "conversation_id": "",
            "result_json": None,
            "error": None,
        }
        row.update(fields)
        self._tasks[task_id] = row

    async def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        sql_lower = sql.lower()
        if "from tasks where id" in sql_lower:
            tid = params[0]
            row = self._tasks.get(tid)
            return self._Row(row) if row else None
        return None

    async def execute(self, sql: str, params: tuple = ()) -> None:
        sql_lower = sql.lower()
        if "update tasks set" in sql_lower:
            tid = params[-1]
            if tid in self._tasks:
                if "status = 'callback_received'" in sql_lower:
                    self._tasks[tid]["status"] = "callback_received"
                if "result_json = ?" in sql_lower:
                    self._tasks[tid]["result_json"] = params[0]
        return None


def _make_app(db: FakeDB) -> FastAPI:
    app = FastAPI()
    app.include_router(callbacks_router)

    class _FakeSettings:
        session_secret = _TEST_SECRET

    app.state.container = Container(settings=_FakeSettings(), db=db)
    # No tool_registry attribute used in these paths beyond .get; provide None.
    app.state.container.tool_registry = None
    return app


def _sig(task_id: str) -> str:
    return hmac.new(_TEST_SECRET.encode(), task_id.encode(), hashlib.sha256).hexdigest()


def test_callback_sig_helper_matches_manual_hmac():
    task_id = "abc-task-id"
    assert _callback_sig(_TEST_SECRET, task_id) == _sig(task_id)


@pytest.mark.asyncio
async def test_callback_accepted_with_valid_sig():
    db = FakeDB()
    task_id = "task-valid"
    db.seed_task(task_id)
    app = _make_app(db)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/callbacks/{task_id}?sig={_sig(task_id)}",
            json={"data": {"callbackType": "complete"}},
        )

    assert resp.status_code == 200, resp.text
    # tool_registry is None, so it stays callback_received (poller path).
    assert db._tasks[task_id]["status"] == "callback_received"


@pytest.mark.asyncio
async def test_callback_rejected_without_sig():
    db = FakeDB()
    task_id = "task-no-sig"
    db.seed_task(task_id)
    app = _make_app(db)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/callbacks/{task_id}",
            json={"data": {"callbackType": "complete"}},
        )

    assert resp.status_code == 403, resp.text
    # Task must NOT have been processed.
    assert db._tasks[task_id]["status"] == "pending"


@pytest.mark.asyncio
async def test_callback_rejected_with_wrong_sig():
    db = FakeDB()
    task_id = "task-bad-sig"
    db.seed_task(task_id)
    app = _make_app(db)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/callbacks/{task_id}?sig=deadbeef",
            json={"data": {"callbackType": "complete"}},
        )

    assert resp.status_code == 403, resp.text
    assert db._tasks[task_id]["status"] == "pending"


@pytest.mark.asyncio
async def test_callback_size_limit_still_enforced():
    db = FakeDB()
    task_id = "task-too-big"
    db.seed_task(task_id)
    app = _make_app(db)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/callbacks/{task_id}?sig={_sig(task_id)}",
            content=b"x" * 600_000,
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 413, resp.text
    assert db._tasks[task_id]["status"] == "pending"
