"""FastAPI dependencies for API authentication and state access.

All state access goes through the Container. Route handlers use
Depends(get_db), Depends(get_settings), etc.
"""

from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request

from odigos.container import Container


def _safe_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    return hmac.compare_digest(a.encode(), b.encode())


def get_container(request: Request) -> Container:
    """Get the Container from app state."""
    return request.app.state.container


async def require_auth(request: Request):
    """Validate Bearer token or session cookie.

    Checks in order:
    1. Bearer token (API key)
    2. Session cookie

    Missing or invalid credentials raises 401.
    """
    from odigos.api.auth import SESSION_COOKIE, _validate_session

    container = get_container(request)
    settings = container.settings
    configured_key = settings.api_key

    # 1. Try Bearer token
    auth_header = request.headers.get("Authorization")
    if auth_header:
        parts = auth_header.split(" ", 1)
        if len(parts) != 2 or parts[0] != "Bearer":
            raise HTTPException(status_code=401, detail="Invalid authorization header format")
        token = parts[1]
        if configured_key and _safe_compare(token, configured_key):
            return
        raise HTTPException(status_code=403, detail="Invalid API key")

    # 2. Try session cookie
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        secret = settings.session_secret
        session = _validate_session(secret, cookie)
        if session:
            # CSRF check: state-changing requests via cookie must include X-Requested-With
            if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                if not request.headers.get("X-Requested-With"):
                    raise HTTPException(status_code=403, detail="Missing CSRF header")
            request.state.user = session
            return

    raise HTTPException(status_code=401, detail="Missing authorization header")


# Backward-compatible alias
require_api_key = require_auth


async def require_card_or_api_key(request: Request):
    """Validate Bearer token against global API key OR a contact card key OR session cookie.

    Global API key: full access (dashboard + mesh).
    Card key (card-sk-*): scoped access per card permissions.
    Session cookie: full access (dashboard user).
    """
    from odigos.api.auth import SESSION_COOKIE, _validate_session

    container = get_container(request)
    settings = container.settings
    configured_key = settings.api_key

    auth_header = request.headers.get("Authorization")
    if auth_header:
        parts = auth_header.split(" ", 1)
        if len(parts) != 2 or parts[0] != "Bearer":
            raise HTTPException(status_code=401, detail="Invalid authorization header format")

        token = parts[1]

        # Check global API key first
        if configured_key and _safe_compare(token, configured_key):
            return

        # Check card key
        card_manager = container.card_manager
        if card_manager and token.startswith("card-sk-"):
            card = await card_manager.validate_card_key(token)
            if card:
                request.state.card = card
                return

        raise HTTPException(status_code=403, detail="Invalid API key or card key")

    # Try session cookie
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        secret = settings.session_secret
        session = _validate_session(secret, cookie)
        if session:
            request.state.user = session
            return

    raise HTTPException(status_code=401, detail="Missing authorization header")


# -- State accessor helpers (all delegate to Container) --

def get_db(container: Container = Depends(get_container)):
    """Get the Database instance from the container."""
    return container.db


def get_goal_store(container: Container = Depends(get_container)):
    """Get the GoalStore instance from the container."""
    return container.goal_store


def get_agent(container: Container = Depends(get_container)):
    """Get the Agent instance from the container."""
    return container.agent


def get_vector_memory(container: Container = Depends(get_container)):
    """Get the VectorMemory instance from the container."""
    return container.vector_memory


def get_budget_tracker(container: Container = Depends(get_container)):
    """Get the BudgetTracker instance from the container."""
    return container.budget_tracker


def get_settings(container: Container = Depends(get_container)):
    """Get the Settings instance from the container."""
    return container.settings


def get_plugin_manager(container: Container = Depends(get_container)):
    """Get the PluginManager instance from the container."""
    return container.plugin_manager


def get_channel_registry(container: Container = Depends(get_container)):
    """Get the ChannelRegistry instance from the container."""
    return container.channel_registry


def get_checkpoint_manager(container: Container = Depends(get_container)):
    """Get the CheckpointManager instance from the container."""
    return container.checkpoint_manager


def get_spawner(container: Container = Depends(get_container)):
    """Get the Spawner instance from the container."""
    return container.spawner


def get_agent_service(container: Container = Depends(get_container)):
    """Get the AgentService instance from the container."""
    return container.agent_service


def get_web_channel(container: Container = Depends(get_container)):
    """Get the WebChannel instance from the container."""
    return container.web_channel


def get_agent_client(container: Container = Depends(get_container)):
    """Get the AgentClient instance from the container."""
    return container.agent_client


def get_config_path(container: Container = Depends(get_container)):
    """Get the config file path from the container."""
    return container.config_path


def get_env_path(container: Container = Depends(get_container)):
    """Get the env file path from the container."""
    return container.env_path


def get_upload_dir(container: Container = Depends(get_container)):
    """Get the upload directory path from the container."""
    return container.upload_dir


def get_skill_registry(container: Container = Depends(get_container)):
    """Get the SkillRegistry instance from the container."""
    return container.skill_registry


def get_cron_manager(container: Container = Depends(get_container)):
    """Get the CronManager instance from the container."""
    return container.cron_manager


def get_scheduler(container: Container = Depends(get_container)):
    """Get the Scheduler instance from the container."""
    return container.scheduler


def get_notifier(container: Container = Depends(get_container)):
    """Get the Notifier instance from the container."""
    return container.notifier


def get_card_manager(container: Container = Depends(get_container)):
    """Get the CardManager instance from the container."""
    return container.card_manager


def get_doc_ingester(container: Container = Depends(get_container)):
    """Get the DocumentIngester instance from the container."""
    return container.doc_ingester


def get_markitdown(container: Container = Depends(get_container)):
    """Get the MarkItDownProvider instance from the container."""
    return container.markitdown_provider


def get_stt_provider(container: Container = Depends(get_container)):
    """Get the STT provider instance from the container."""
    return container.stt_provider


def get_tts_provider(container: Container = Depends(get_container)):
    """Get the TTS provider instance from the container."""
    return container.tts_provider


def get_vapid_keys(container: Container = Depends(get_container)):
    """Get the VAPID keys from the container."""
    return container.vapid_keys


def require_feature(feature_name: str):
    """FastAPI dependency that gates endpoints behind a config flag.

    Checks settings.{feature_name}.enabled. If the feature config doesn't
    exist or has no 'enabled' attribute, access is allowed (safe default).

    Usage: router = APIRouter(dependencies=[Depends(require_feature("notebooks"))])
    """
    def check(settings=Depends(get_settings)):
        feature_config = getattr(settings, feature_name, None)
        if feature_config is not None and not getattr(feature_config, "enabled", True):
            raise HTTPException(status_code=404, detail=f"{feature_name} is not enabled")
    return check
