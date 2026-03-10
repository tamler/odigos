import os
import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from odigos.dashboard import mount_dashboard


class TestDashboardServing:
    async def test_index_served(self, tmp_path):
        """Root path serves index.html."""
        (tmp_path / "index.html").write_text("<html><body>Odigos Dashboard</body></html>")
        css_dir = tmp_path / "css"
        css_dir.mkdir()
        (css_dir / "style.css").write_text("body { color: red; }")

        app = FastAPI()

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        mount_dashboard(app, str(tmp_path))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/")
            assert resp.status_code == 200
            assert "Odigos Dashboard" in resp.text

            resp = await c.get("/dashboard/css/style.css")
            assert resp.status_code == 200

            # SPA fallback
            resp = await c.get("/chat/some-conversation")
            assert resp.status_code == 200
            assert "Odigos Dashboard" in resp.text

            # Health endpoint still works (registered before catch-all)
            resp = await c.get("/health")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}

    async def test_no_index_no_mount(self, tmp_path):
        """If index.html does not exist, mount_dashboard is a no-op."""
        app = FastAPI()
        mount_dashboard(app, str(tmp_path))
        # No catch-all route should be registered
        route_paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/{path:path}" not in route_paths
