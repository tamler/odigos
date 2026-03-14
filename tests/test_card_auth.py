"""Tests for card-based auth dependency."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from odigos.api.deps import require_card_or_api_key


def _make_app():
    app = FastAPI()
    app.state.settings = SimpleNamespace(api_key="global-key")
    card_manager = AsyncMock()
    app.state.card_manager = card_manager
    return app, card_manager


def test_global_key_passes():
    app, _ = _make_app()

    @app.get("/guarded")
    async def guarded(_=Depends(require_card_or_api_key)):
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/guarded", headers={"Authorization": "Bearer global-key"})
    assert resp.status_code == 200


def test_card_key_passes():
    app, card_manager = _make_app()
    card_manager.validate_card_key = AsyncMock(return_value={
        "card_type": "connect", "permissions": "mesh", "status": "active",
    })

    @app.get("/guarded")
    async def guarded(_=Depends(require_card_or_api_key)):
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/guarded", headers={"Authorization": "Bearer card-sk-abc123"})
    assert resp.status_code == 200


def test_invalid_key_rejected():
    app, card_manager = _make_app()
    card_manager.validate_card_key = AsyncMock(return_value=None)

    @app.get("/guarded")
    async def guarded(_=Depends(require_card_or_api_key)):
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/guarded", headers={"Authorization": "Bearer wrong-key"})
    assert resp.status_code == 403


def test_no_header_rejected():
    app, _ = _make_app()

    @app.get("/guarded")
    async def guarded(_=Depends(require_card_or_api_key)):
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/guarded")
    assert resp.status_code == 401
