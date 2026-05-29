import pytest
from odigos.tools import url_guard


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://localhost/", "http://10.0.0.1/",
    "http://172.16.0.1/", "http://192.168.1.1/", "http://169.254.169.254/",
    "http://0.0.0.0/", "http://[::1]/", "http://[fe80::1]/", "http://[fc00::1]/",
    "http://2130706433/",          # decimal 127.0.0.1
    "http://0x7f000001/",          # hex 127.0.0.1
    "http://user@127.0.0.1/",      # userinfo
    "http://127.0.0.1.:8002/",     # trailing dot
    "HTTP://127.0.0.1/",           # mixed-case scheme
    "file:///etc/passwd", "gopher://127.0.0.1/", "data:text/plain,hi",
    "ftp://127.0.0.1/",
    "http://localhost:5432/", "http://localhost:2019/config",
    "http://127.0.0.1:8002/",
])
def test_blocks_internal_and_bad_schemes(url):
    assert url_guard.is_blocked_url(url) is True


def test_allows_public_literal_ip():
    # 93.184.216.34 (example.com's historical IP) is a public literal — no DNS needed.
    assert url_guard.is_blocked_url("http://93.184.216.34/") is False


def test_fails_closed_on_dns_error(monkeypatch):
    import socket
    def _boom(*a, **k):
        raise socket.gaierror("nope")
    monkeypatch.setattr("socket.getaddrinfo", _boom)
    assert url_guard.is_blocked_url("http://does-not-resolve.invalid/") is True
