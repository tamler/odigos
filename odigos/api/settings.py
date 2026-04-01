"""Settings GET/POST API endpoints for reading and writing configuration."""
from __future__ import annotations


import asyncio
import imaplib
import smtplib
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
    voice: dict | None = None
    calendar: dict | None = None
    assistant: dict | None = None


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
        "calendar": settings.calendar.model_dump(),
        "assistant": settings.assistant.model_dump(),
    }


class EmailTestRequest(BaseModel):
    imap_host: str
    imap_port: int = 993
    smtp_host: str
    smtp_port: int = 587
    username: str
    password: str | None = None
    address: str | None = None
    enabled: bool | None = None
    check_interval_ticks: int | None = None


def _test_imap(host: str, port: int, username: str, password: str) -> str:
    """Test IMAP connection (blocking, run via to_thread)."""
    try:
        conn = imaplib.IMAP4_SSL(host, port, timeout=10)
        conn.login(username, password)
        conn.logout()
        return "ok"
    except Exception as exc:
        return str(exc)


def _test_smtp(host: str, port: int, username: str, password: str) -> str:
    """Test SMTP connection (blocking, run via to_thread)."""
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls()
        server.login(username, password)
        server.quit()
        return "ok"
    except Exception as exc:
        return str(exc)


@router.post("/email/test")
async def test_email_connection(
    req: EmailTestRequest,
    settings=Depends(get_settings),
    _=Depends(require_auth),
):
    """Test IMAP and SMTP connections with the provided credentials."""
    password = req.password
    if not password or password == "****":
        # Fall back to stored password
        email_cfg = settings.email
        password = getattr(email_cfg, "password", "")
    if not password:
        raise HTTPException(status_code=400, detail="No password provided and none stored")

    imap_result, smtp_result = await asyncio.gather(
        asyncio.to_thread(_test_imap, req.imap_host, req.imap_port, req.username, password),
        asyncio.to_thread(_test_smtp, req.smtp_host, req.smtp_port, req.username, password),
    )
    return {"imap": imap_result, "smtp": smtp_result}


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
    for section in ("llm", "agent", "budget", "heartbeat", "sandbox", "mesh", "templates", "feed", "telegram", "email", "voice", "calendar", "assistant"):
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
    for section in ("llm", "agent", "budget", "heartbeat", "sandbox", "templates", "feed", "telegram", "email", "voice", "calendar", "assistant"):
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

    # Backup config before writing (keep last 3 versions)
    if config_path.exists():
        import shutil
        for i in range(2, 0, -1):
            src = config_path.with_suffix(f".yaml.bak{i}")
            dst = config_path.with_suffix(f".yaml.bak{i + 1}")
            if src.exists():
                shutil.move(str(src), str(dst))
        shutil.copy2(str(config_path), str(config_path.with_suffix(".yaml.bak1")))

    # Write config.yaml once with all updates (only after validation succeeds)
    with open(config_path, "w") as f:
        yaml.dump(yaml_config, f, default_flow_style=False)

    # Hot-reload in-memory settings from validated objects
    for section, new_obj in validated_sections.items():
        object.__setattr__(settings, section, new_obj)

    return {"status": "ok"}


@router.post("/calendar/test")
async def test_calendar_connection(request: Request, _=Depends(require_auth)):
    """Test a CalDAV connection and return discovered calendars."""
    body = await request.json()
    url = body.get("url", "").strip()
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()

    if not url or not username:
        raise HTTPException(status_code=400, detail="url and username are required")

    def _test():
        import caldav

        client = caldav.DAVClient(url=url, username=username, password=password, timeout=10)
        principal = client.principal()
        calendars = principal.calendars()
        return [str(c.name) for c in calendars if c.name]

    try:
        calendars = await asyncio.wait_for(asyncio.to_thread(_test), timeout=15)
        return {"status": "ok", "calendars": calendars}
    except asyncio.TimeoutError:
        return {"status": "error", "detail": "Connection timed out after 10 seconds"}
    except Exception as exc:
        detail = str(exc)
        if len(detail) > 200:
            detail = detail[:200] + "..."
        return {"status": "error", "detail": detail}


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
