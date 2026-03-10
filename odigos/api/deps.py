"""FastAPI dependencies for API authentication and state access."""

from fastapi import HTTPException, Request


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
    if token != configured_key:
        raise HTTPException(status_code=403, detail="Invalid API key")


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
