"""Default-deny route-inventory gate.

Walks the real FastAPI app and fails if any state-changing route
(POST/PUT/PATCH/DELETE) is neither protected by an auth dependency nor in the
reviewed PUBLIC allowlist below. This guards against future drift where a new
mutating endpoint ships without authentication.

A route counts as "protected" when any of its (recursively flattened)
dependency callables has a name containing "require" -- this covers the
per-route and router-level patterns:
  - Depends(require_auth) / require_api_key / require_card_or_api_key
  - APIRouter(dependencies=[Depends(require_auth)])

Some endpoints authenticate INLINE instead (they read the session cookie and
call _validate_session / _validate_session_with_epoch + _check_csrf directly,
or check the API key by hand). FastAPI cannot see that as a dependency, so each
such route is listed in PUBLIC with a one-line justification. Genuinely public
endpoints (first-run setup, login, logout, external webhooks) are listed too.
"""

from __future__ import annotations

from odigos.main import app

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# (METHOD, path) tuples that are intentionally public OR self-validate inline.
# Every entry is justified; do NOT blanket-allowlist new routes.
PUBLIC: set[tuple[str, str]] = {
    # -- Public by design: auth bootstrap / credential exchange --
    ("POST", "/api/auth/setup"),  # first-run bootstrap, no user exists yet
    ("POST", "/api/auth/login"),  # password login, issues session cookie
    ("POST", "/api/auth/logout"),  # clears the session cookie
    # -- Self-validating inline (cookie + _validate_session_with_epoch + _check_csrf) --
    ("POST", "/api/auth/change-password"),  # self-validates inline (session + CSRF)
    ("DELETE", "/api/auth/facts/{fact_id}"),  # self-validates inline (session + CSRF)
    ("PUT", "/api/auth/profile"),  # self-validates inline (session + CSRF)
    # -- Self-validating inline (API key + _check_csrf, admin only) --
    ("POST", "/api/auth/reset-password"),  # self-validates inline (Bearer API key + CSRF)
    # -- External webhook: authenticated by unguessable task UUID in the path --
    ("POST", "/api/callbacks/{task_id}"),  # external callback, secret UUID path, no session
    # -- WebAuthn: registration self-validates session inline --
    ("POST", "/api/webauthn/register/begin"),  # self-validates inline (_get_session required)
    ("POST", "/api/webauthn/register/complete"),  # self-validates inline (_get_session required)
    # -- WebAuthn: passwordless login is a public auth endpoint --
    ("POST", "/api/webauthn/login/begin"),  # passwordless auth start, issues challenge
    ("POST", "/api/webauthn/login/complete"),  # passwordless auth, verifies + issues session
}


def _collect_dependency_names(dependant) -> list[str]:
    """Recursively collect callable names from a route's dependant tree.

    FastAPI flattens router-level dependencies into each route's dependant, so
    walking .dependencies recursively captures both per-route and router-level
    auth dependencies.
    """
    names: list[str] = []
    call = getattr(dependant, "call", None)
    if call is not None:
        names.append(getattr(call, "__name__", str(call)))
    for sub in getattr(dependant, "dependencies", []) or []:
        names.extend(_collect_dependency_names(sub))
    return names


def _is_protected(dependant) -> bool:
    if dependant is None:
        return False
    return any("require" in name for name in _collect_dependency_names(dependant))


def test_all_mutating_routes_protected_or_allowlisted():
    unclassified: list[tuple[str, str]] = []

    for route in app.routes:
        methods = getattr(route, "methods", None)
        if not methods:
            continue
        mutating = methods & MUTATING_METHODS
        if not mutating:
            continue
        dependant = getattr(route, "dependant", None)
        protected = _is_protected(dependant)
        for method in mutating:
            key = (method, route.path)
            if protected or key in PUBLIC:
                continue
            unclassified.append(key)

    unclassified.sort()
    assert not unclassified, (
        "Unprotected mutating routes detected (no auth dependency and not in "
        "the reviewed PUBLIC allowlist). Protect each route with "
        "Depends(require_auth)/require_card_or_api_key, or add it to PUBLIC "
        "with a justification:\n  "
        + "\n  ".join(f"{m} {p}" for m, p in unclassified)
    )
