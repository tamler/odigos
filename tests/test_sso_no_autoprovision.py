"""SSO must not auto-provision unknown emails when sso_auto_provision is False (the default)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from odigos.api.auth import router as auth_router
from odigos.container import Container
from tests.conftest import make_test_settings

_JWT_SECRET = "testsecret"
_AUDIENCE = "https://test.odigos.one"


class FakeDB:
    """Minimal async DB substitute backed by a plain dict.

    Handles the SQL patterns used by the SSO endpoint without mocks.
    """

    class _Row(dict):
        pass

    def __init__(self):
        self._users: dict[str, dict] = {}  # keyed by id

    async def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        sql_lower = sql.lower().strip()

        if "count(*)" in sql_lower and "from users" in sql_lower:
            return self._Row({"count": len(self._users)})

        if "from users where lower(email)" in sql_lower:
            email = params[0]
            for u in self._users.values():
                if (u.get("email") or "").lower() == email:
                    return self._Row(u)
            return None

        if "from users where username" in sql_lower:
            username = params[0]
            for u in self._users.values():
                if u["username"] == username:
                    return self._Row(u)
            return None

        if "from users where id" in sql_lower:
            user_id = params[0]
            return self._Row(self._users[user_id]) if user_id in self._users else None

        return None

    async def execute(self, sql: str, params: tuple = ()) -> None:
        sql_lower = sql.lower().strip()

        if sql_lower.startswith("insert into users"):
            uid = params[0]
            self._users[uid] = {
                "id": uid,
                "username": params[1],
                "email": params[2] if len(params) > 2 else "",
                "password_hash": params[3] if len(params) > 3 else "",
                "display_name": params[4] if len(params) > 4 else "",
                "must_change_password": params[5] if len(params) > 5 else 0,
                "created_at": params[6] if len(params) > 6 else "",
                "last_login_at": params[7] if len(params) > 7 else None,
            }
            return

        if "update users set last_login_at" in sql_lower:
            uid = params[1]
            if uid in self._users:
                self._users[uid]["last_login_at"] = params[0]
            return


def _make_app(db: FakeDB) -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router)
    settings = make_test_settings(
        platform_jwt_secret=_JWT_SECRET,
        platform_audience=_AUDIENCE,
    )
    app.state.container = Container(settings=settings, db=db)
    return app


def _mint_jwt(email: str) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": email,
        "aud": _AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    return jwt.encode(claims, _JWT_SECRET, algorithm="HS256")


@pytest.mark.asyncio
async def test_sso_does_not_autoprovision_unknown_email_by_default():
    # Confirm the secure default is in effect — we never set this in the test.
    assert make_test_settings().sso_auto_provision is False

    db = FakeDB()
    app = _make_app(db)

    unknown_email = "stranger@example.com"
    token = _mint_jwt(unknown_email)

    users_before = len(db._users)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # No follow_redirects: a successful SSO would 302-redirect; we expect a refusal.
        resp = await c.get("/api/auth/sso", params={"token": token})

    # Unknown email with auto-provision off must be refused, not redirected.
    assert resp.status_code == 403, resp.text
    assert unknown_email in resp.json()["detail"]

    # And no user row was created for that email.
    assert len(db._users) == users_before
    assert all((u.get("email") or "").lower() != unknown_email for u in db._users.values())
