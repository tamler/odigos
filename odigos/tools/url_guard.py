"""SSRF guard shared by all URL-fetching tools.

Blocks private/loopback/link-local/reserved/multicast targets, bad schemes,
numeric-IP-literal encodings, userinfo tricks, trailing-dot hosts, and fails
CLOSED on resolution errors. Redirect re-validation and connect-to-resolved-IP
are applied by callers that control their fetcher.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = {"http", "https"}


def _ip_is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def _normalize_host(host: str) -> str:
    host = host.strip().rstrip(".").lower()
    try:
        host = host.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        pass
    return host


def is_blocked_url(url: str, policy: str | None = None) -> bool:
    """Return True if the URL must NOT be fetched. Fails closed on any error."""
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in _ALLOWED_SCHEMES:
            return True
        host = parts.hostname  # urlsplit strips userinfo; IPv6 brackets removed
        if not host:
            return True
        host = _normalize_host(host)
        # Numeric literal? Check before DNS (covers decimal/hex/octal/IPv6).
        try:
            ipaddress.ip_address(host)
            return _ip_is_blocked(host)
        except ValueError:
            pass
        infos = socket.getaddrinfo(host, parts.port or 0, proto=socket.IPPROTO_TCP)
        if not infos:
            return True
        for info in infos:
            if _ip_is_blocked(info[4][0]):
                return True
        return False
    except (socket.gaierror, ValueError, UnicodeError, OSError):
        return True  # fail closed
