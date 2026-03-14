"""In-memory rate limiting middleware for FastAPI.

Provides per-IP request throttling to prevent brute force attacks
and resource exhaustion. No external dependencies (no Redis).
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import NamedTuple

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class _Bucket(NamedTuple):
    tokens: float
    last_refill: float


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket rate limiter keyed by client IP.

    Parameters
    ----------
    rate : float
        Requests per second allowed per IP.
    burst : int
        Maximum burst size (bucket capacity).
    """

    def __init__(self, app, *, rate: float = 10.0, burst: int = 30):
        super().__init__(app)
        self.rate = rate
        self.burst = burst
        self._buckets: dict[str, list] = defaultdict(lambda: [float(burst), time.monotonic()])

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

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip rate limiting for health checks
        if request.url.path == "/health":
            return await call_next(request)

        ip = self._get_client_ip(request)
        if not self._consume(ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={"Retry-After": "1"},
            )

        # Periodic cleanup of stale buckets (every ~1000 requests)
        if len(self._buckets) > 1000:
            cutoff = time.monotonic() - 300  # 5 minutes
            stale = [k for k, v in self._buckets.items() if v[1] < cutoff]
            for k in stale:
                del self._buckets[k]

        return await call_next(request)
