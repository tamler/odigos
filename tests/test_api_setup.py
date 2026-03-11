# tests/test_api_setup.py
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

from odigos.api.setup import router


def _make_app(llm_api_key: str = "", api_key: str = "test-key") -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    settings = MagicMock()
    settings.llm_api_key = llm_api_key
    settings.api_key = api_key
    settings.llm.base_url = "https://openrouter.ai/api/v1"
    app.state.settings = settings
    return app


def test_setup_status_unconfigured():
    app = _make_app(llm_api_key="")
    client = TestClient(app)
    resp = client.get("/api/setup-status")
    assert resp.status_code == 200
    assert resp.json() == {"configured": False}


def test_setup_status_configured():
    app = _make_app(llm_api_key="sk-real-key")
    client = TestClient(app)
    resp = client.get("/api/setup-status")
    assert resp.status_code == 200
    assert resp.json() == {"configured": True}
