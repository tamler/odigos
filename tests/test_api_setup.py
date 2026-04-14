# tests/test_api_setup.py
from types import SimpleNamespace
from fastapi.testclient import TestClient
from fastapi import FastAPI

from odigos.api.setup import router
from odigos.container import Container


def _make_app(*, configured: bool) -> FastAPI:
    """Build a minimal app with a settings shim.

    When `configured=True`, the shim exposes at least one provider with an
    api_key, a model, and a routing `fast` alias — the three things
    setup_status checks for.
    """
    app = FastAPI()
    app.include_router(router)

    if configured:
        providers = {"openrouter": SimpleNamespace(api_key="sk-real-key", base_url="x")}
        models = {"scout": SimpleNamespace()}
        llm = SimpleNamespace(fast="scout")
    else:
        providers = {}
        models = {}
        llm = SimpleNamespace(fast="")

    settings = SimpleNamespace(
        providers=providers,
        models=models,
        llm=llm,
        api_key="test-key",
    )
    app.state.container = Container(settings=settings)
    return app


def test_setup_status_unconfigured():
    app = _make_app(configured=False)
    client = TestClient(app)
    resp = client.get("/api/setup-status")
    assert resp.status_code == 200
    assert resp.json() == {"configured": False}


def test_setup_status_configured():
    app = _make_app(configured=True)
    client = TestClient(app)
    resp = client.get("/api/setup-status")
    assert resp.status_code == 200
    assert resp.json() == {"configured": True}
