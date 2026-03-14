"""Tests for cards REST API endpoints."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app():
    from odigos.api.cards import router

    app = FastAPI()
    settings = MagicMock()
    settings.api_key = "test-key"

    card_manager = AsyncMock()
    db = AsyncMock()

    app.state.settings = settings
    app.state.card_manager = card_manager
    app.state.db = db
    app.include_router(router)
    return app, card_manager, db


class TestCardsAPI:
    def test_list_issued(self):
        app, card_manager, _ = _make_app()
        card_manager.list_issued = AsyncMock(return_value=[
            {"id": "1", "card_type": "connect", "status": "active", "created_at": "2026-03-14"},
        ])
        client = TestClient(app)
        resp = client.get("/api/cards/issued", headers={"Authorization": "Bearer test-key"})
        assert resp.status_code == 200
        assert len(resp.json()["cards"]) == 1

    def test_list_accepted(self):
        app, card_manager, _ = _make_app()
        card_manager.list_accepted = AsyncMock(return_value=[
            {"id": "1", "agent_name": "Archie", "card_type": "connect", "status": "active"},
        ])
        client = TestClient(app)
        resp = client.get("/api/cards/accepted", headers={"Authorization": "Bearer test-key"})
        assert resp.status_code == 200
        assert len(resp.json()["cards"]) == 1

    def test_generate_card(self):
        app, card_manager, _ = _make_app()
        card_manager.generate_card = AsyncMock(return_value={
            "version": 1, "type": "connect", "agent_name": "Odigos",
            "host": "100.64.0.1", "ws_port": 8001, "card_key": "card-sk-abc",
            "capabilities": [], "feed_url": None, "issued_at": "2026-03-14",
            "expires_at": None, "issuer": "Odigos", "fingerprint": "sha256:abc",
        })
        card_manager.card_to_yaml = MagicMock(return_value="yaml content")
        card_manager.card_to_compact = MagicMock(return_value="odigos-card:abc")

        client = TestClient(app)
        resp = client.post(
            "/api/cards/generate",
            json={"type": "connect"},
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "card" in data
        assert "yaml" in data
        assert "compact" in data

    def test_revoke_issued(self):
        app, card_manager, _ = _make_app()
        card_manager.revoke_issued = AsyncMock(return_value=True)

        client = TestClient(app)
        resp = client.post(
            "/api/cards/issued/card-sk-abc/revoke",
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200

    def test_revoke_accepted(self):
        app, card_manager, _ = _make_app()
        card_manager.revoke_accepted = AsyncMock(return_value=True)

        client = TestClient(app)
        resp = client.post(
            "/api/cards/accepted/card-id-123/revoke",
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200

    def test_mute_accepted(self):
        app, card_manager, _ = _make_app()
        card_manager.mute_accepted = AsyncMock(return_value=True)

        client = TestClient(app)
        resp = client.post(
            "/api/cards/accepted/card-id-123/mute",
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200

    def test_unmute_accepted(self):
        app, card_manager, _ = _make_app()
        card_manager.unmute_accepted = AsyncMock(return_value=True)

        client = TestClient(app)
        resp = client.post(
            "/api/cards/accepted/card-id-123/unmute",
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200

    def test_list_feed_entries(self):
        app, _, db = _make_app()
        db.fetch_all = AsyncMock(return_value=[
            {"id": "1", "title": "Alert", "content": "Server down", "category": "alert", "created_at": "2026-03-14"},
        ])

        client = TestClient(app)
        resp = client.get("/api/feed/entries", headers={"Authorization": "Bearer test-key"})
        assert resp.status_code == 200
        assert len(resp.json()["entries"]) == 1

    def test_delete_feed_entry(self):
        app, _, db = _make_app()
        db.execute = AsyncMock()

        client = TestClient(app)
        resp = client.delete("/api/feed/entries/entry-1", headers={"Authorization": "Bearer test-key"})
        assert resp.status_code == 200
