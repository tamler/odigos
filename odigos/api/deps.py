"""FastAPI dependencies for API authentication and state access."""

import hmac

from fastapi import HTTPException, Request


def _safe_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    return hmac.compare_digest(a.encode(), b.encode())


async def require_api_key(request: Request):
    """Validate Bearer token against the configured API key.

    If api_key is not configured, raises 403.
    Missing Authorization header raises 401.
    Wrong key raises 403.
    """
    settings = request.app.state.settings
    configured_key = settings.api_key

    if not configured_key:
        raise HTTPException(
            status_code=403,
            detail="API key not configured. Set 'api_key' in config.yaml.",
        )

    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    # Expect "Bearer <token>"
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0] != "Bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = parts[1]
    if not _safe_compare(token, configured_key):
        raise HTTPException(status_code=403, detail="Invalid API key")


async def require_card_or_api_key(request: Request):
    """Validate Bearer token against global API key OR a contact card key.

    Global API key: full access (dashboard + mesh).
    Card key (card-sk-*): scoped access per card permissions.
    """
    settings = request.app.state.settings
    configured_key = settings.api_key

    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0] != "Bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = parts[1]

    # Check global API key first
    if configured_key and _safe_compare(token, configured_key):
        return

    # Check card key
    card_manager = getattr(request.app.state, "card_manager", None)
    if card_manager and token.startswith("card-sk-"):
        card = await card_manager.validate_card_key(token)
        if card:
            request.state.card = card
            return

    raise HTTPException(status_code=403, detail="Invalid API key or card key")


# -- State accessor helpers --

def get_db(request: Request):
    """Get the Database instance from app state."""
    return request.app.state.db


def get_goal_store(request: Request):
    """Get the GoalStore instance from app state."""
    return request.app.state.goal_store


def get_agent(request: Request):
    """Get the Agent instance from app state."""
    return request.app.state.agent


def get_vector_memory(request: Request):
    """Get the VectorMemory instance from app state."""
    return request.app.state.vector_memory


def get_budget_tracker(request: Request):
    """Get the BudgetTracker instance from app state."""
    return request.app.state.budget_tracker


def get_settings(request: Request):
    """Get the Settings instance from app state."""
    return request.app.state.settings


def get_plugin_manager(request: Request):
    """Get the PluginManager instance from app state."""
    return request.app.state.plugin_manager


def get_channel_registry(request: Request):
    """Get the ChannelRegistry instance from app state."""
    return request.app.state.channel_registry


def get_checkpoint_manager(request: Request):
    """Get the CheckpointManager instance from app state."""
    return request.app.state.checkpoint_manager


def get_spawner(request: Request):
    """Get the Spawner instance from app state."""
    return request.app.state.spawner


def get_agent_service(request: Request):
    """Get the AgentService instance from app state."""
    return request.app.state.agent_service


def get_web_channel(request: Request):
    """Get the WebChannel instance from app state."""
    return request.app.state.web_channel


def get_agent_client(request: Request):
    """Get the AgentClient instance from app state."""
    return getattr(request.app.state, "agent_client", None)


def get_config_path(request: Request):
    """Get the config file path from app state."""
    return request.app.state.config_path


def get_env_path(request: Request):
    """Get the env file path from app state."""
    return request.app.state.env_path


def get_upload_dir(request: Request):
    """Get the upload directory path from app state."""
    return request.app.state.upload_dir


def get_skill_registry(request: Request):
    """Get the SkillRegistry instance from app state."""
    return request.app.state.skill_registry


def get_cron_manager(request: Request):
    """Get the CronManager instance from app state."""
    return request.app.state.cron_manager


def get_notifier(request: Request):
    """Get the Notifier instance from app state."""
    return request.app.state.notifier
