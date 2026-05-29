"""In-memory rate limiting middleware for FastAPI.

Provides per-IP request throttling to prevent brute force attacks
and resource exhaustion. No external dependencies (no Redis).
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket rate limiter keyed by client IP.

    Parameters
    ----------
    rate : float
        Requests per second allowed per IP.
    burst : int
        Maximum burst size (bucket capacity).
    ws_rate : float
        WebSocket upgrades per second allowed per IP. Looser than the HTTP
        rate by default (0.5/s == 30 upgrades/minute) so legitimate reconnects
        are not throttled while a connection flood still hits the limit.
    ws_burst : int
        Maximum burst size for the WebSocket-upgrade bucket.
    """

    def __init__(
        self,
        app,
        *,
        rate: float = 10.0,
        burst: int = 30,
        ws_rate: float = 0.5,
        ws_burst: int = 30,
    ):
        super().__init__(app)
        self.rate = rate
        self.burst = burst
        self.ws_rate = ws_rate
        self.ws_burst = ws_burst
        self._buckets: dict[str, list] = defaultdict(lambda: [float(burst), time.monotonic()])
        # Separate bucket store for WS upgrades so HTTP and WS limits are
        # decoupled. Keyed by IP; capacity/refill use ws_burst/ws_rate.
        self._ws_buckets: dict[str, list] = defaultdict(
            lambda: [float(ws_burst), time.monotonic()]
        )

    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _consume(self, ip: str) -> bool:
        bucket = self._buckets[ip]
        now = time.monotonic()
        elapsed = now - bucket[1]
        bucket[0] = min(self.burst, bucket[0] + elapsed * self.rate)
        bucket[1] = now
        if bucket[0] >= 1.0:
            bucket[0] -= 1.0
            return True
        return False

    def _consume_ws(self, ip: str) -> bool:
        bucket = self._ws_buckets[ip]
        now = time.monotonic()
        elapsed = now - bucket[1]
        bucket[0] = min(self.ws_burst, bucket[0] + elapsed * self.ws_rate)
        bucket[1] = now
        if bucket[0] >= 1.0:
            bucket[0] -= 1.0
            return True
        return False

    def _too_many(self) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests"},
            headers={"Retry-After": "1"},
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip rate limiting for health checks.
        if request.url.path == "/health":
            return await call_next(request)

        ip = self._get_client_ip(request)

        # WebSocket upgrades get their own looser per-IP bucket so a flood of
        # connection attempts is throttled without coupling to the HTTP limit.
        if request.headers.get("upgrade", "").lower() == "websocket":
            if not self._consume_ws(ip):
                return self._too_many()
            return await call_next(request)

        if not self._consume(ip):
            return self._too_many()

        # Periodic cleanup of stale buckets (every ~1000 requests)
        if len(self._buckets) > 1000:
            cutoff = time.monotonic() - 300  # 5 minutes
            stale = [k for k, v in self._buckets.items() if v[1] < cutoff]
            for k in stale:
                del self._buckets[k]

        return await call_next(request)
