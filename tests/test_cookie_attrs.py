from unittest.mock import MagicMock
from fastapi import Response
from odigos.api import auth


def _req(scheme="http", xfp=None):
    r = MagicMock()
    r.url.scheme = scheme
    r.headers = {"x-forwarded-proto": xfp} if xfp else {}
    return r


def test_secure_from_forwarded_proto():
    resp = Response()
    auth._set_session_cookie(resp, _req(scheme="http", xfp="https"), "tok")
    cookie = resp.headers.get("set-cookie", "")
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()


def test_not_secure_plain_http():
    resp = Response()
    auth._set_session_cookie(resp, _req(scheme="http", xfp=None), "tok")
    cookie = resp.headers.get("set-cookie", "")
    assert "Secure" not in cookie


def test_secure_direct_https():
    resp = Response()
    auth._set_session_cookie(resp, _req(scheme="https", xfp=None), "tok")
    assert "Secure" in resp.headers.get("set-cookie", "")
