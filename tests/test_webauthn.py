"""Tests for WebAuthn passkey endpoints."""

import pytest

pytest.importorskip("webauthn")

from httpx import ASGITransport, AsyncClient


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def app():
    """Create a minimal app instance with a test database."""
    import tempfile
    import os
    from pathlib import Path

    from odigos.config import load_settings
    from odigos.db import Database

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        migrations_dir = str(
            Path(__file__).parent.parent / "migrations"
        )
        db = Database(db_path, migrations_dir)
        await db.initialize()

        settings = load_settings(
            config_path=os.path.join(tmpdir, "missing.yaml")
        )
        settings.session_secret = "test-secret-key-for-webauthn"
        settings.api_key = "test-api-key"

        from fastapi import FastAPI
        test_app = FastAPI()
        test_app.state.db = db
        test_app.state.settings = settings

        try:
            from odigos.api.webauthn import router
            test_app.include_router(router)
        except ImportError:
            pytest.skip("py-webauthn not installed")

        from odigos.api.auth import router as auth_router
        test_app.include_router(auth_router)

        yield test_app

        await db.close()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://localhost",
    ) as c:
        yield c


@pytest.mark.anyio
async def test_register_begin_requires_auth(client):
    """Registration begin must return 401 without session."""
    resp = await client.post("/api/webauthn/register/begin")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_login_begin_no_credentials(client):
    """Login begin returns 404 when no passkeys registered."""
    resp = await client.post("/api/webauthn/login/begin")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_migration_creates_table(app):
    """Verify webauthn_credentials table exists after migration."""
    db = app.state.db
    row = await db.fetch_one(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='webauthn_credentials'"
    )
    assert row is not None
    assert row["name"] == "webauthn_credentials"


@pytest.mark.anyio
async def test_register_complete_requires_auth(client):
    """Registration complete must return 401 without session."""
    resp = await client.post(
        "/api/webauthn/register/complete",
        json={"credential": {}},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_login_complete_no_challenge(client):
    """Login complete returns 400 when no challenge pending."""
    resp = await client.post(
        "/api/webauthn/login/complete",
        json={"credential": {}},
    )
    assert resp.status_code == 400
