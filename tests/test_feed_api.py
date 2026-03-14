"""Tests for RSS feed publisher endpoint."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app(feed_enabled=True, feed_public=False):
    from odigos.api.feed import router

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        api_key="test-key",
        feed=SimpleNamespace(enabled=feed_enabled, public=feed_public, max_entries=200),
        agent=SimpleNamespace(name="Odigos"),
    )
    db = AsyncMock()
    app.state.db = db
    card_manager = AsyncMock()
    app.state.card_manager = card_manager
    app.include_router(router)
    return app, db, card_manager


def test_feed_xml_returns_rss():
    app, db, _ = _make_app(feed_public=True)
    db.fetch_all = AsyncMock(return_value=[
        {"id": "1", "title": "Test Entry", "content": "Hello world", "category": "status", "created_at": "2026-03-14T12:00:00"},
    ])

    client = TestClient(app)
    resp = client.get("/feed.xml")
    assert resp.status_code == 200
    assert "application/rss+xml" in resp.headers["content-type"]
    assert "<title>Test Entry</title>" in resp.text
    assert "<rss" in resp.text


def test_feed_disabled_returns_404():
    app, _, _ = _make_app(feed_enabled=False)
    client = TestClient(app)
    resp = client.get("/feed.xml")
    assert resp.status_code == 404


def test_feed_private_requires_auth():
    app, db, card_manager = _make_app(feed_public=False)
    card_manager.validate_card_key = AsyncMock(return_value=None)

    client = TestClient(app)
    resp = client.get("/feed.xml")
    assert resp.status_code == 401


def test_feed_private_accepts_card_key():
    app, db, card_manager = _make_app(feed_public=False)
    card_manager.validate_card_key = AsyncMock(return_value={"card_type": "subscribe", "status": "active"})
    db.fetch_all = AsyncMock(return_value=[])

    client = TestClient(app)
    resp = client.get("/feed.xml", headers={"Authorization": "Bearer card-sk-abc"})
    assert resp.status_code == 200
