import os
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

from odigos.api.upload import router


def _make_app(tmp_path) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    settings = MagicMock()
    settings.api_key = "test-key"
    app.state.settings = settings
    app.state.upload_dir = str(tmp_path)
    app.state.doc_ingester = None
    app.state.markitdown_provider = None
    return app


def test_upload_file(tmp_path):
    app = _make_app(tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/upload",
        files={"file": ("test.txt", b"hello world", "text/plain")},
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"] == "test.txt"
    assert data["size"] == 11
    assert "id" in data
    assert os.path.exists(os.path.join(tmp_path, data["id"] + "_test.txt"))


def test_upload_no_file(tmp_path):
    app = _make_app(tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/upload",
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 422


def test_upload_no_auth(tmp_path):
    app = _make_app(tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/upload",
        files={"file": ("test.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 401
