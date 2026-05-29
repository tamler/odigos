"""Tests for WebSocket-upgrade rate limiting in RateLimitMiddleware."""
from __future__ import annotations

from fastapi import FastAPI
from starlette.testclient import TestClient

from odigos.api.rate_limit import RateLimitMiddleware


def _build_app(*, rate: float, burst: int, ws_rate: float, ws_burst: int) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        rate=rate,
        burst=burst,
        ws_rate=ws_rate,
        ws_burst=ws_burst,
    )

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return app


def test_ws_upgrade_requests_are_throttled():
    """A flood of WS-upgrade requests from one IP eventually gets a 429."""
    app = _build_app(rate=1000.0, burst=1000, ws_rate=0.001, ws_burst=3)
    client = TestClient(app)
    headers = {"upgrade": "websocket", "x-forwarded-for": "1.2.3.4"}

    # First `ws_burst` upgrade requests pass through to the route (404, since
    # there is no real WS handler) without being throttled.
    statuses = [client.get("/ping", headers=headers).status_code for _ in range(3)]
    assert all(s != 429 for s in statuses), statuses

    # The next upgrade request from the same IP exceeds the WS bucket -> 429.
    throttled = client.get("/ping", headers=headers)
    assert throttled.status_code == 429
    assert throttled.json() == {"detail": "Too many requests"}


def test_ws_bucket_is_separate_from_http_bucket():
    """Exhausting the WS bucket must not throttle normal HTTP requests."""
    app = _build_app(rate=1000.0, burst=1000, ws_rate=0.001, ws_burst=2)
    client = TestClient(app)
    ip = "5.6.7.8"
    ws_headers = {"upgrade": "websocket", "x-forwarded-for": ip}

    # Drain the WS bucket.
    for _ in range(2):
        client.get("/ping", headers=ws_headers)
    assert client.get("/ping", headers=ws_headers).status_code == 429

    # Plain HTTP request from the same IP is unaffected by the WS bucket.
    resp = client.get("/ping", headers={"x-forwarded-for": ip})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_http_flood_does_not_throttle_ws_bucket():
    """Exhausting the HTTP bucket must not throttle WS upgrades."""
    app = _build_app(rate=0.001, burst=2, ws_rate=1000.0, ws_burst=1000)
    client = TestClient(app)
    ip = "9.9.9.9"

    # Drain the HTTP bucket.
    for _ in range(2):
        client.get("/ping", headers={"x-forwarded-for": ip})
    assert client.get("/ping", headers={"x-forwarded-for": ip}).status_code == 429

    # WS upgrade from the same IP is unaffected by the HTTP bucket.
    resp = client.get("/ping", headers={"upgrade": "websocket", "x-forwarded-for": ip})
    assert resp.status_code != 429
