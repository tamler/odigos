"""Settings GET/POST API endpoints for reading and writing configuration."""
from __future__ import annotations


import asyncio
import imaplib
import smtplib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError

from odigos import aio
from odigos.api.deps import get_config_path, get_settings, require_auth

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_auth)],
)


class SettingsUpdate(BaseModel):
    api_key: str | None = None
    current_api_key: str | None = None  # Required when changing api_key
    telegram_bot_token: str | None = None  # Legacy — prefer services.telegram
    services: dict[str, str] | None = None
    providers: dict[str, dict] | None = None  # {name: {base_url, api_key}}
    models: dict[str, dict] | None = None     # {alias: {provider, id, cost_*, vision, context_window, notes}}
    llm: dict | None = None                   # {fast, smart, background, fallback, max_tokens, temperature, auto_route, ...}
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
    email_data = settings.email.model_dump()
    if email_data.get("password"):
        email_data["password"] = "****"
    calendar_data = settings.calendar.model_dump()
    if calendar_data.get("password"):
        calendar_data["password"] = "****"

    providers_masked = {}
    for name, p in settings.providers.items():
        providers_masked[name] = {
            "base_url": p.base_url,
            "api_key": _mask_key(p.api_key),
        }

    return {
        "api_key": _mask_key(settings.api_key),
        "services": {name: _mask_key(key) for name, key in settings.services.items()},
        "telegram_configured": bool(settings.service_key("telegram")),
        "providers": providers_masked,
        "models": {alias: m.model_dump() for alias, m in settings.models.items()},
        "llm": settings.llm.model_dump(),
        "agent": settings.agent.model_dump(),
        "budget": settings.budget.model_dump(),
        "heartbeat": settings.heartbeat.model_dump(),
        "sandbox": settings.sandbox.model_dump(),
        "mesh": settings.mesh.model_dump(),
        "templates": settings.templates.model_dump(),
        "feed": settings.feed.model_dump(),
        "telegram": settings.telegram.model_dump(),
        "email": email_data,
        "voice": settings.voice.model_dump(),
        "calendar": calendar_data,
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
        return str(exc)[:200]


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
        return str(exc)[:200]


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
):
    """Update settings, writing to config.yaml and hot-reloading in-memory.

    API keys live in config.yaml's `providers` block — either as literal values
    or as `${ENV_VAR}` interpolations resolved at load time.
    """
    config_path = Path(config_path_str)

    # Load existing config.yaml
    yaml_config: dict = {}
    if config_path.exists():
        yaml_config = await aio.read_yaml(config_path)

    # Merge updated sections into yaml config
    for section in ("llm", "agent", "budget", "heartbeat", "sandbox", "mesh", "templates", "feed", "telegram", "email", "voice", "calendar", "assistant"):
        section_data = getattr(update, section, None)
        if section_data is not None:
            if section not in yaml_config:
                yaml_config[section] = {}
            yaml_config[section].update(section_data)

    # Update services (external API keys)
    if update.services is not None:
        if "services" not in yaml_config:
            yaml_config["services"] = {}
        for name, key in update.services.items():
            if key == "****":
                continue  # Skip masked values (no change)
            if key == "":
                # Empty string = remove service
                yaml_config["services"].pop(name, None)
                settings.services.pop(name, None)
            else:
                yaml_config["services"][name] = key
                settings.services[name] = key

    # Legacy: telegram_bot_token → services.telegram
    if update.telegram_bot_token is not None and update.telegram_bot_token != "****":
        if "services" not in yaml_config:
            yaml_config["services"] = {}
        yaml_config["services"]["telegram"] = update.telegram_bot_token
        settings.services["telegram"] = update.telegram_bot_token

    # Update providers (BYOK: dashboard-editable). REPLACE semantics — the
    # incoming dict is authoritative, so deleting a provider in the UI actually
    # removes it. For each incoming provider, a masked api_key ("****") or a
    # missing/None api_key preserves whatever is currently stored; a new
    # non-empty value overwrites; an explicit empty string clears it.
    if update.providers is not None:
        previous = dict(yaml_config.get("providers") or {})
        new_providers: dict = {}
        for name, patch in update.providers.items():
            if patch is None:
                continue  # Explicit null also deletes
            existing = previous.get(name) or {}
            merged: dict = {}
            # Copy forward every incoming field except api_key, which has
            # masked-value handling.
            for k, v in patch.items():
                if k == "api_key":
                    continue
                if v is not None:
                    merged[k] = v
            incoming_key = patch.get("api_key")
            if incoming_key is None or incoming_key == "****":
                # Preserve stored key (installer-written or prior value)
                if existing.get("api_key"):
                    merged["api_key"] = existing["api_key"]
            elif incoming_key == "":
                # Explicit clear
                pass
            else:
                merged["api_key"] = incoming_key
            new_providers[name] = merged
        yaml_config["providers"] = new_providers

    # Update models dict — REPLACE semantics, same reasoning. Models carry no
    # secrets so there's no masked-value wrinkle.
    if update.models is not None:
        new_models: dict = {}
        for alias, patch in update.models.items():
            if patch is None:
                continue
            new_models[alias] = {k: v for k, v in patch.items() if v is not None}
        yaml_config["models"] = new_models

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

    # Validate providers / models dicts (live-updated above) into their typed shapes
    validated_providers = None
    validated_models = None
    if update.providers is not None:
        from odigos.config import ProviderConfig
        try:
            validated_providers = {
                name: ProviderConfig(**cfg)
                for name, cfg in yaml_config.get("providers", {}).items()
            }
        except ValidationError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid provider config: {exc.errors()}",
            )
    if update.models is not None:
        from odigos.config import ModelConfig
        try:
            validated_models = {
                alias: ModelConfig(**cfg)
                for alias, cfg in yaml_config.get("models", {}).items()
            }
        except ValidationError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid model config: {exc.errors()}",
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
    await aio.write_yaml(config_path, yaml_config)

    # Hot-reload in-memory settings from validated objects
    for section, new_obj in validated_sections.items():
        object.__setattr__(settings, section, new_obj)
    if validated_providers is not None:
        object.__setattr__(settings, "providers", validated_providers)
    if validated_models is not None:
        object.__setattr__(settings, "models", validated_models)

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
        yaml_config = await aio.read_yaml(config_path)

    # Merge profile config into yaml
    for section, values in profile["config"].items():
        if isinstance(values, dict):
            if section not in yaml_config:
                yaml_config[section] = {}
            yaml_config[section].update(values)
        else:
            yaml_config[section] = values

    await aio.write_yaml(config_path, yaml_config)

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


async def _update_env_file(env_path: Path, key: str, value: str) -> None:
    """Update or add a key=value pair in an .env file.

    Still used by the plugin configurator for per-plugin secrets.
    """
    value = value.replace("\n", "").replace("\r", "")
    lines: list[str] = []
    found = False

    if env_path.exists():
        content = await aio.read_text(env_path)
        lines = content.splitlines(keepends=True)

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

    await aio.write_text(env_path, "".join(new_lines))
