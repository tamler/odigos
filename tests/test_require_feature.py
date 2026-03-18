import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from odigos.api.deps import require_feature
from odigos.config import Settings, NotebooksConfig


def _make_app(notebooks_enabled: bool) -> FastAPI:
    """Create a minimal FastAPI app with a gated endpoint."""
    app = FastAPI()
    settings = Settings(notebooks=NotebooksConfig(enabled=notebooks_enabled))
    app.state.settings = settings

    @app.get("/api/notebooks", dependencies=[Depends(require_feature("notebooks"))])
    async def list_notebooks():
        return {"notebooks": []}

    return app


class TestRequireFeature:
    def test_enabled_allows_access(self):
        app = _make_app(notebooks_enabled=True)
        client = TestClient(app)
        resp = client.get("/api/notebooks")
        assert resp.status_code == 200

    def test_disabled_returns_404(self):
        app = _make_app(notebooks_enabled=False)
        client = TestClient(app)
        resp = client.get("/api/notebooks")
        assert resp.status_code == 404

    def test_missing_config_allows_access(self):
        """If the feature config doesn't exist on Settings, allow access (safe default)."""
        app = FastAPI()
        app.state.settings = Settings()

        @app.get("/api/unknown", dependencies=[Depends(require_feature("nonexistent_feature"))])
        async def endpoint():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/api/unknown")
        assert resp.status_code == 200
