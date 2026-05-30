from odigos.security.events import log_security_event, _redact


def test_redacts_query_string_and_tokens():
    assert "token=" not in _redact("https://x/cb?token=abc123")
    assert _redact("Bearer sk-secret123") == "Bearer [redacted]"


def test_rate_limited(monkeypatch):
    seen = []
    monkeypatch.setattr("odigos.security.events._emit", lambda kind, msg: seen.append((kind, msg)))
    for _ in range(200):
        log_security_event("ssrf_blocked", "http://127.0.0.1/?token=x")
    assert 0 < len(seen) < 200  # emitted at least once, but rate-limited
