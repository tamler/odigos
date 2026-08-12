"""Tests that WebAuthn login resolves the user by the credential's user_id.

Regression test for the `SELECT ... FROM users LIMIT 1` bug, which authenticated
as the first-created user regardless of which passkey was presented.

Seam: we monkeypatch ONLY the crypto signature-verification call
(`verify_authentication_response`) so the test does not need a real authenticator
signature. The user-resolution logic (credential.user_id -> users row) is exercised
unchanged and is what we assert on.
"""

import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("webauthn")

from httpx import ASGITransport, AsyncClient


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def ctx():
    """App + db + settings with two seeded users."""
    from fastapi import FastAPI

    from odigos.config import load_settings
    from odigos.container import Container
    from odigos.db import Database

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        migrations_dir = str(Path(__file__).parent.parent / "migrations")
        db = Database(db_path, migrations_dir)
        await db.initialize()

        settings = load_settings(config_path=os.path.join(tmpdir, "missing.yaml"))
        settings.session_secret = "test-secret-key-for-webauthn-user"
        settings.api_key = "test-api-key"

        now = datetime.now(timezone.utc).isoformat()
        first_id = uuid.uuid4().hex
        second_id = uuid.uuid4().hex
        await db.execute(
            "INSERT INTO users "
            "(id, username, email, password_hash, display_name, "
            "must_change_password, created_at, last_login_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (first_id, "alice", "", "x", "", 0, now, now),
        )
        await db.execute(
            "INSERT INTO users "
            "(id, username, email, password_hash, display_name, "
            "must_change_password, created_at, last_login_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (second_id, "bob", "", "x", "", 0, now, now),
        )

        app = FastAPI()
        app.state.container = Container(settings=settings, db=db)
        from odigos.api.webauthn import router

        app.include_router(router)

        yield {
            "app": app,
            "db": db,
            "settings": settings,
            "first_id": first_id,
            "second_id": second_id,
        }

        await db.close()


@pytest.fixture
async def client(ctx):
    transport = ASGITransport(app=ctx["app"])
    async with AsyncClient(transport=transport, base_url="http://localhost") as c:
        yield c


@pytest.mark.anyio
async def test_login_resolves_user_by_credential_user_id(ctx, client, monkeypatch):
    """A passkey owned by the SECOND user must authenticate AS the second user."""
    db = ctx["db"]
    settings = ctx["settings"]
    second_id = ctx["second_id"]
    first_id = ctx["first_id"]

    cred_raw_id = b"test-credential-raw-id"

    # Seed a credential row associated with the SECOND user.
    await db.execute(
        "INSERT INTO webauthn_credentials "
        "(id, credential_id, public_key, sign_count, user_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, cred_raw_id, b"pubkey", 0, second_id),
    )

    # Begin login to seed a challenge in the in-memory store.
    begin = await client.post("/api/webauthn/login/begin")
    assert begin.status_code == 200

    # Monkeypatch ONLY the crypto verification seam.
    import odigos.api.webauthn as wa

    class _FakeVerification:
        new_sign_count = 1

    monkeypatch.setattr(
        wa,
        "verify_authentication_response",
        lambda **kwargs: _FakeVerification(),
    )

    # The installed py-webauthn (2.7.1) exposes credential parsing via
    # parse_authentication_credential_json, not the pydantic parse_raw/
    # model_validate the handler tries. Patch the class's model_validate to the
    # supported parser so the request reaches the user-resolution logic under
    # test. This is a parsing-layer shim, NOT the user-resolution logic.
    from webauthn.helpers import bytes_to_base64url, parse_authentication_credential_json
    from webauthn.helpers.structs import AuthenticationCredential as _AuthCred

    monkeypatch.setattr(
        _AuthCred,
        "model_validate",
        classmethod(
            lambda cls, data: parse_authentication_credential_json(__import__("json").dumps(data))
        ),
        raising=False,
    )

    # Minimal AuthenticationCredential payload; raw_id must match the stored credential.
    raw_id_b64 = bytes_to_base64url(cred_raw_id)
    credential_payload = {
        "id": raw_id_b64,
        "rawId": raw_id_b64,
        "type": "public-key",
        "response": {
            "clientDataJSON": bytes_to_base64url(b"{}"),
            "authenticatorData": bytes_to_base64url(b"\x00" * 37),
            "signature": bytes_to_base64url(b"sig"),
        },
        "clientExtensionResults": {},
    }

    resp = await client.post(
        "/api/webauthn/login/complete",
        json={"credential": credential_payload},
    )
    assert resp.status_code == 200, resp.text

    # Decode the issued session cookie and verify it belongs to the SECOND user.
    from odigos.api.auth import SESSION_COOKIE, _validate_session

    cookie = client.cookies.get(SESSION_COOKIE)
    assert cookie
    session = _validate_session(settings.session_secret, cookie)
    assert session is not None
    assert session["user_id"] == second_id
    assert session["user_id"] != first_id
    assert session["username"] == "bob"


async def test_login_with_orphaned_credential_fails_closed(ctx, client, monkeypatch):
    """A credential with no user_id must NOT mint a session.

    Migration 015 used to backfill orphaned credentials with
    `(SELECT id FROM users LIMIT 1)`. That statement was dead (the ALTER before
    it always raised duplicate-column and aborted the file) and was deleted
    2026-08-12 rather than allowed to become live, because it would have bound a
    passkey to an arbitrary account on any install with more than one user --
    and login trusts credential.user_id to mint the session. Orphans fail closed
    instead; this pins that behaviour.
    """
    db = ctx["db"]

    cred_raw_id = b"orphaned-credential-raw-id"
    await db.execute(
        "INSERT INTO webauthn_credentials "
        "(id, credential_id, public_key, sign_count, user_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, cred_raw_id, b"pubkey", 0, None),
    )

    begin = await client.post("/api/webauthn/login/begin")
    assert begin.status_code == 200

    import odigos.api.webauthn as wa

    class _FakeVerification:
        new_sign_count = 1

    monkeypatch.setattr(
        wa, "verify_authentication_response", lambda **kwargs: _FakeVerification()
    )

    from webauthn.helpers import bytes_to_base64url, parse_authentication_credential_json
    from webauthn.helpers.structs import AuthenticationCredential as _AuthCred

    monkeypatch.setattr(
        _AuthCred,
        "model_validate",
        classmethod(
            lambda cls, data: parse_authentication_credential_json(__import__("json").dumps(data))
        ),
        raising=False,
    )

    raw_id_b64 = bytes_to_base64url(cred_raw_id)
    resp = await client.post(
        "/api/webauthn/login/complete",
        json={"credential": {
            "id": raw_id_b64,
            "rawId": raw_id_b64,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(b"{}"),
                "authenticatorData": bytes_to_base64url(b"\x00" * 37),
                "signature": bytes_to_base64url(b"sig"),
            },
            "clientExtensionResults": {},
        }},
    )

    assert resp.status_code == 400, resp.text
    assert "not associated with a user" in resp.text

    from odigos.api.auth import SESSION_COOKIE

    assert client.cookies.get(SESSION_COOKIE) is None, "a session was minted for an orphan"
