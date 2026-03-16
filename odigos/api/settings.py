"""Settings GET/POST API endpoints for reading and writing configuration."""

from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from odigos.api.deps import get_config_path, get_env_path, get_settings, require_api_key

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


class SettingsUpdate(BaseModel):
    llm_api_key: str | None = None
    api_key: str | None = None
    current_api_key: str | None = None  # Required when changing api_key
    llm: dict | None = None
    agent: dict | None = None
    budget: dict | None = None
    heartbeat: dict | None = None
    sandbox: dict | None = None
    mesh: dict | None = None
    templates: dict | None = None
    feed: dict | None = None


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
        "llm": settings.llm.model_dump(),
        "agent": settings.agent.model_dump(),
        "budget": settings.budget.model_dump(),
        "heartbeat": settings.heartbeat.model_dump(),
        "sandbox": settings.sandbox.model_dump(),
        "mesh": settings.mesh.model_dump(),
        "templates": settings.templates.model_dump(),
        "feed": settings.feed.model_dump(),
        "stt": settings.stt.model_dump() if hasattr(settings, 'stt') else {},
        "tts": settings.tts.model_dump() if hasattr(settings, 'tts') else {},
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
    for section in ("llm", "agent", "budget", "heartbeat", "sandbox", "mesh", "templates", "feed"):
        section_data = getattr(update, section)
        if section_data is not None:
            if section not in yaml_config:
                yaml_config[section] = {}
            yaml_config[section].update(section_data)

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

    # Write config.yaml once with all updates
    with open(config_path, "w") as f:
        yaml.dump(yaml_config, f, default_flow_style=False)

    # Hot-reload in-memory settings from merged sections
    for section in ("llm", "agent", "budget", "heartbeat", "sandbox", "templates", "feed"):
        section_data = getattr(update, section)
        if section_data is not None:
            current = getattr(settings, section)
            merged = current.model_dump()
            merged.update(section_data)
            new_obj = type(current)(**merged)
            object.__setattr__(settings, section, new_obj)

    return {"status": "ok"}


def _update_env_file(env_path: Path, key: str, value: str) -> None:
    """Update or add a key=value pair in an .env file."""
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
