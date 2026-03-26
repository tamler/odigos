"""Tests for message report endpoint."""
from types import SimpleNamespace

from fastapi import FastAPI
from starlette.testclient import TestClient


def _make_app():
    from odigos.api.report import router
    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(
        api_key="test-key",
        session_secret="",
    )

    class MockDB:
        def __init__(self):
            self.inserts = []

        async def execute(self, sql, params=None):
            self.inserts.append((sql, params))

    app.state.db = MockDB()
    return app


class TestReportEndpoint:
    def test_report_creates_evaluation(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.post(
            "/api/conversations/conv-123/report",
            json={"message_index": 2, "reason": "wrong", "message_content": "bad answer"},
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "reported"
        assert len(app.state.db.inserts) == 1
        sql, params = app.state.db.inserts[0]
        assert "evaluations" in sql
        assert params[2] == "conv-123"

    def test_report_requires_auth(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.post(
            "/api/conversations/conv-123/report",
            json={"message_index": 0, "reason": "unhelpful", "message_content": "x"},
        )
        assert resp.status_code == 401

    def test_report_validates_reason(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.post(
            "/api/conversations/conv-123/report",
            json={"message_index": 0, "reason": "invalid-reason", "message_content": "x"},
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 422
