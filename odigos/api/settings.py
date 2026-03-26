"""Settings GET/POST API endpoints for reading and writing configuration."""

from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError

from odigos.api.deps import get_config_path, get_env_path, get_settings, require_auth

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_auth)],
)


class SettingsUpdate(BaseModel):
    llm_api_key: str | None = None
    api_key: str | None = None
    current_api_key: str | None = None  # Required when changing api_key
    telegram_bot_token: str | None = None
    llm: dict | None = None
    agent: dict | None = None
    budget: dict | None = None
    heartbeat: dict | None = None
    sandbox: dict | None = None
    mesh: dict | None = None
    templates: dict | None = None
    feed: dict | None = None
    telegram: dict | None = None
    email: dict | None = None


def _mask_key(key: str) -> str:
    """Mask a secret key for display."""
    if not key:
        return ""
    return "****"


@router.get("/settings")
async def get_settings_endpoint(settings=Depends(get_settings)):
    """Return current settings with secrets masked."""
    return {
        "llm_api_key": _mask_key(settings.llm_api_key),
        "api_key": _mask_key(settings.api_key),
        "telegram_bot_token": _mask_key(settings.telegram_bot_token),
        "telegram_configured": bool(settings.telegram_bot_token),
        "llm": settings.llm.model_dump(),
        "agent": settings.agent.model_dump(),
        "budget": settings.budget.model_dump(),
        "heartbeat": settings.heartbeat.model_dump(),
        "sandbox": settings.sandbox.model_dump(),
        "mesh": settings.mesh.model_dump(),
        "templates": settings.templates.model_dump(),
        "feed": settings.feed.model_dump(),
        "telegram": settings.telegram.model_dump(),
        "email": settings.email.model_dump(),
        "voice": settings.voice.model_dump(),
    }


@router.post("/settings")
async def update_settings_endpoint(
    update: SettingsUpdate,
    settings=Depends(get_settings),
    config_path_str: str = Depends(get_config_path),
    env_path_str: str = Depends(get_env_path),
):
    """Update settings, writing to config.yaml and .env, then hot-reload in-memory."""
    config_path = Path(config_path_str)
    env_path = Path(env_path_str)

    # Load existing config.yaml
    yaml_config: dict = {}
    if config_path.exists():
        with open(config_path) as f:
            yaml_config = yaml.safe_load(f) or {}

    # Merge updated sections into yaml config
    for section in ("llm", "agent", "budget", "heartbeat", "sandbox", "mesh", "templates", "feed", "telegram", "email"):
        section_data = getattr(update, section, None)
        if section_data is not None:
            if section not in yaml_config:
                yaml_config[section] = {}
            yaml_config[section].update(section_data)

    # Update Telegram bot token in config.yaml (not .env -- accessible via settings UI)
    if update.telegram_bot_token is not None and update.telegram_bot_token != "****":
        yaml_config["telegram_bot_token"] = update.telegram_bot_token
        object.__setattr__(settings, "telegram_bot_token", update.telegram_bot_token)

    # Update LLM API key in .env (ignore masked placeholder)
    if update.llm_api_key is not None and update.llm_api_key != "****":
        _update_env_file(env_path, "LLM_API_KEY", update.llm_api_key)
        object.__setattr__(settings, "llm_api_key", update.llm_api_key)

    # Update dashboard API key (requires current key confirmation)
    if update.api_key is not None and update.api_key != "****":
        if not update.current_api_key or update.current_api_key != settings.api_key:
            raise HTTPException(
                status_code=403,
                detail="current_api_key must match the existing API key to change it",
            )
        yaml_config["api_key"] = update.api_key
        object.__setattr__(settings, "api_key", update.api_key)

    # Validate all merged sections with Pydantic BEFORE writing to disk
    validated_sections: dict[str, object] = {}
    for section in ("llm", "agent", "budget", "heartbeat", "sandbox", "templates", "feed", "telegram", "email"):
        section_data = getattr(update, section)
        if section_data is not None:
            current = getattr(settings, section)
            merged = current.model_dump()
            merged.update(section_data)
            try:
                validated_sections[section] = type(current)(**merged)
            except ValidationError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid settings for '{section}': {exc.errors()}",
                )

    # Write config.yaml once with all updates (only after validation succeeds)
    with open(config_path, "w") as f:
        yaml.dump(yaml_config, f, default_flow_style=False)

    # Hot-reload in-memory settings from validated objects
    for section, new_obj in validated_sections.items():
        object.__setattr__(settings, section, new_obj)

    return {"status": "ok"}


@router.get("/profiles")
async def get_profiles():
    """List available agent profiles."""
    from odigos.profiles import list_profiles
    return {"profiles": list_profiles()}


@router.post("/profiles/{profile_id}")
async def apply_profile(
    profile_id: str,
    settings=Depends(get_settings),
    config_path_str: str = Depends(get_config_path),
):
    """Apply an agent profile, updating config.yaml with the profile's settings."""
    from odigos.profiles import get_profile
    profile = get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile not found: {profile_id}")

    config_path = Path(config_path_str)
    yaml_config: dict = {}
    if config_path.exists():
        with open(config_path) as f:
            yaml_config = yaml.safe_load(f) or {}

    # Merge profile config into yaml
    for section, values in profile["config"].items():
        if isinstance(values, dict):
            if section not in yaml_config:
                yaml_config[section] = {}
            yaml_config[section].update(values)
        else:
            yaml_config[section] = values

    with open(config_path, "w") as f:
        yaml.dump(yaml_config, f, default_flow_style=False)

    # Hot-reload affected settings
    for section, values in profile["config"].items():
        if isinstance(values, dict) and hasattr(settings, section):
            current = getattr(settings, section)
            if hasattr(current, "model_dump"):
                merged = current.model_dump()
                merged.update(values)
                try:
                    new_obj = type(current)(**merged)
                    object.__setattr__(settings, section, new_obj)
                except Exception:
                    pass

    return {"status": "ok", "profile": profile_id, "name": profile["name"]}


def _update_env_file(env_path: Path, key: str, value: str) -> None:
    """Update or add a key=value pair in an .env file."""
    # Sanitize: strip newlines to prevent env injection
    value = value.replace("\n", "").replace("\r", "")
    lines: list[str] = []
    found = False

    if env_path.exists():
        with open(env_path) as f:
            lines = f.readlines()

    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}\n")

    with open(env_path, "w") as f:
        f.writelines(new_lines)
