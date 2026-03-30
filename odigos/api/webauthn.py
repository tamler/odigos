"""WebAuthn API: passkey registration and authentication."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, HTTPException, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webauthn", tags=["webauthn"])

# In-memory challenge store with TTL (5 minutes)
_challenges: dict[str, tuple[bytes, float]] = {}
_CHALLENGE_TTL = 300


def _store_challenge(key: str, challenge: bytes) -> None:
    _prune_challenges()
    _challenges[key] = (challenge, time.time())


def _pop_challenge(key: str) -> bytes | None:
    _prune_challenges()
    entry = _challenges.pop(key, None)
    if entry is None:
        return None
    challenge, ts = entry
    if time.time() - ts > _CHALLENGE_TTL:
        return None
    return challenge


def _prune_challenges() -> None:
    now = time.time()
    expired = [
        k for k, (_, ts) in _challenges.items()
        if now - ts > _CHALLENGE_TTL
    ]
    for k in expired:
        _challenges.pop(k, None)


def _get_rp_id(request: Request) -> str:
    forwarded_host = request.headers.get("x-forwarded-host", request.url.hostname or "localhost")
    return forwarded_host.split(":")[0] if ":" in forwarded_host else forwarded_host


def _get_rp_origin(request: Request) -> str:
    # Trust X-Forwarded headers from reverse proxy (Caddy)
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    forwarded_host = request.headers.get("x-forwarded-host", request.url.hostname or "localhost")
    # Strip port from forwarded host if present
    hostname = forwarded_host.split(":")[0] if ":" in forwarded_host else forwarded_host
    port = request.url.port
    if forwarded_proto == "https" or (port and port in (80, 443)):
        return f"{forwarded_proto}://{hostname}"
    if port and port not in (80, 443):
        return f"{forwarded_proto}://{hostname}:{port}"
    return f"{forwarded_proto}://{hostname}"


def _get_session(request: Request) -> dict | None:
    from odigos.api.auth import SESSION_COOKIE, _validate_session
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        return None
    secret = request.app.state.settings.session_secret
    return _validate_session(secret, cookie)


try:
    from webauthn import (
        generate_registration_options,
        verify_registration_response,
        generate_authentication_options,
        verify_authentication_response,
        options_to_json,
    )
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria,
        ResidentKeyRequirement,
        UserVerificationRequirement,
        PublicKeyCredentialDescriptor,
    )
    from webauthn.helpers import (
        bytes_to_base64url,
        base64url_to_bytes,
    )
    _WEBAUTHN_AVAILABLE = True
except ImportError:
    _WEBAUTHN_AVAILABLE = False


def _require_webauthn():
    if not _WEBAUTHN_AVAILABLE:
        raise HTTPException(
            status_code=404,
            detail="WebAuthn not available",
        )


# ------------------------------------------------------------------
# Registration (requires auth)
# ------------------------------------------------------------------

@router.post("/register/begin")
async def register_begin(request: Request):
    """Generate registration options. Requires session."""
    _require_webauthn()
    session = _get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = session["user_id"]
    username = session["username"]
    rp_id = _get_rp_id(request)

    db = request.app.state.db
    existing = await db.fetch_all(
        "SELECT credential_id FROM webauthn_credentials",
    )
    exclude_creds = [
        PublicKeyCredentialDescriptor(id=row["credential_id"])
        for row in existing
    ]

    options = generate_registration_options(
        rp_id=rp_id,
        rp_name="Odigos",
        user_id=user_id.encode(),
        user_name=username,
        user_display_name=username,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=(
                UserVerificationRequirement.PREFERRED
            ),
        ),
        exclude_credentials=exclude_creds,
    )

    _store_challenge(
        f"reg:{user_id}",
        options.challenge,
    )

    import json
    return json.loads(options_to_json(options))


@router.post("/register/complete")
async def register_complete(request: Request):
    """Verify registration and store credential. Requires session."""
    _require_webauthn()
    session = _get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = session["user_id"]
    rp_id = _get_rp_id(request)
    rp_origin = _get_rp_origin(request)

    challenge = _pop_challenge(f"reg:{user_id}")
    if not challenge:
        raise HTTPException(
            status_code=400,
            detail="No pending registration challenge",
        )

    body = await request.json()
    credential_data = body.get("credential", body)

    from webauthn.helpers.structs import (
        RegistrationCredential,
    )

    try:
        credential = RegistrationCredential.parse_raw(
            __import__("json").dumps(credential_data)
        )
    except Exception:
        # Try model_validate for newer pydantic
        try:
            credential = RegistrationCredential.model_validate(
                credential_data
            )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid credential format: {e}",
            )

    try:
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=rp_origin,
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Registration verification failed: {e}",
        )

    cred_id = verification.credential_id
    public_key = verification.credential_public_key
    sign_count = verification.sign_count

    db = request.app.state.db
    row_id = uuid.uuid4().hex
    await db.execute(
        "INSERT INTO webauthn_credentials "
        "(id, credential_id, public_key, sign_count) "
        "VALUES (?, ?, ?, ?)",
        (row_id, cred_id, public_key, sign_count),
    )

    return {"status": "ok", "credential_id": row_id}


# ------------------------------------------------------------------
# Authentication (no auth required)
# ------------------------------------------------------------------

@router.post("/login/begin")
async def login_begin(request: Request):
    """Generate authentication options."""
    _require_webauthn()

    db = request.app.state.db
    creds = await db.fetch_all(
        "SELECT credential_id FROM webauthn_credentials",
    )
    if not creds:
        raise HTTPException(
            status_code=404,
            detail="No passkeys registered",
        )

    rp_id = _get_rp_id(request)
    allow_creds = [
        PublicKeyCredentialDescriptor(id=row["credential_id"])
        for row in creds
    ]

    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=allow_creds,
        user_verification=(
            UserVerificationRequirement.PREFERRED
        ),
    )

    _store_challenge("login", options.challenge)

    import json
    return json.loads(options_to_json(options))


@router.post("/login/complete")
async def login_complete(request: Request, response: Response):
    """Verify authentication and issue session."""
    _require_webauthn()

    challenge = _pop_challenge("login")
    if not challenge:
        raise HTTPException(
            status_code=400,
            detail="No pending login challenge",
        )

    rp_id = _get_rp_id(request)
    rp_origin = _get_rp_origin(request)

    body = await request.json()
    credential_data = body.get("credential", body)

    from webauthn.helpers.structs import (
        AuthenticationCredential,
    )

    try:
        credential = AuthenticationCredential.parse_raw(
            __import__("json").dumps(credential_data)
        )
    except Exception:
        try:
            credential = AuthenticationCredential.model_validate(
                credential_data
            )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid credential: {e}",
            )

    raw_id = credential.raw_id

    db = request.app.state.db
    stored = await db.fetch_one(
        "SELECT id, credential_id, public_key, sign_count "
        "FROM webauthn_credentials WHERE credential_id = ?",
        (raw_id,),
    )
    if not stored:
        raise HTTPException(
            status_code=400,
            detail="Unknown credential",
        )

    try:
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=rp_origin,
            credential_public_key=stored["public_key"],
            credential_current_sign_count=stored["sign_count"],
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Authentication failed: {e}",
        )

    await db.execute(
        "UPDATE webauthn_credentials "
        "SET sign_count = ? WHERE id = ?",
        (verification.new_sign_count, stored["id"]),
    )

    # Issue session for the first user (single-user system)
    user = await db.fetch_one(
        "SELECT id, username FROM users LIMIT 1",
    )
    if not user:
        raise HTTPException(
            status_code=500,
            detail="No user account found",
        )

    from odigos.api.auth import (
        _create_session,
        _set_session_cookie,
    )
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "UPDATE users SET last_login_at = ? WHERE id = ?",
        (now, user["id"]),
    )

    secret = request.app.state.settings.session_secret
    token = _create_session(secret, {
        "user_id": user["id"],
        "username": user["username"],
        "must_change_password": False,
    })
    _set_session_cookie(response, request, token)

    return {"status": "ok"}
