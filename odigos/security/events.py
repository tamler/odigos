"""Structured, redacting, rate-limited security event logging."""
from __future__ import annotations

import logging
import re
import time

logger = logging.getLogger("odigos.security")

_BEARER_RE = re.compile(r"Bearer\s+\S+")
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]+")

# Per-kind token bucket: kind -> [tokens, last_refill]
_BUCKETS: dict[str, list[float]] = {}
_RATE = 0.2          # refills per second (~12/min)
_BURST = 5.0         # allow a small burst, then throttle


def _redact(text: str) -> str:
    if not text:
        return text
    s = str(text)
    # Drop query strings (may carry tokens/sig); keep scheme+host+path.
    s = re.sub(r"\?[^\s]*", "", s)
    s = _BEARER_RE.sub("Bearer [redacted]", s)
    s = _SK_RE.sub("[redacted]", s)
    return s


def _allow(kind: str) -> bool:
    now = time.monotonic()
    tokens, last = _BUCKETS.get(kind, [_BURST, now])
    tokens = min(_BURST, tokens + (now - last) * _RATE)
    if tokens < 1.0:
        _BUCKETS[kind] = [tokens, now]
        return False
    _BUCKETS[kind] = [tokens - 1.0, now]
    return True


def _emit(kind: str, msg: str) -> None:
    logger.warning("security_event kind=%s %s", kind, msg)


def log_security_event(kind: str, detail: str = "", **ids) -> None:
    """Best-effort: never raises. Redacts detail, rate-limits per kind."""
    try:
        if not _allow(kind):
            return
        parts = [f"detail={_redact(detail)}"]
        for k, v in ids.items():
            parts.append(f"{k}={_redact(str(v))}")
        _emit(kind, " ".join(parts))
    except Exception:
        pass
