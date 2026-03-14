"""Plugins list and configure API endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from odigos.api.deps import get_config_path, get_env_path, get_plugin_manager, get_settings, require_api_key
from odigos.api.settings import _update_env_file

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


def _resolve_setting(settings: Any, key: str) -> Any:
    """Resolve a possibly dotted config key from a Settings object.

    For example, "gws.enabled" resolves to settings.gws.enabled.
    Returns None if any segment is missing.
    """
    obj = settings
    for part in key.split("."):
        try:
            obj = getattr(obj, part)
        except AttributeError:
            return None
    return obj


def _merge_plugins(
    metadata: list[dict],
    loaded: list[dict],
    settings: Any,
) -> list[dict]:
    """Merge plugin metadata with load status and annotate config keys.

    Each returned plugin dict has all metadata fields plus:
      - status: "active", "error", or "available"
      - config_keys[].configured: bool indicating whether the setting has a value
    """
    loaded_by_name: dict[str, dict] = {}
    for p in loaded:
        loaded_by_name[p["name"]] = p

    result = []
    for meta in metadata:
        plugin_id = meta["id"]
        plugin_name = meta.get("name", "")
        loaded_info = loaded_by_name.get(plugin_id) or loaded_by_name.get(plugin_name)

        entry = {**meta}

        if loaded_info:
            entry["status"] = loaded_info.get("status", "active")
            if loaded_info.get("error_message"):
                entry["error_message"] = loaded_info["error_message"]
        else:
            entry["status"] = "available"

        # Annotate config keys with configured status
        annotated_keys = []
        for ck in meta.get("config_keys", []):
            ck_copy = {**ck}
            value = _resolve_setting(settings, ck["key"])
            ck_copy["configured"] = bool(value)
            annotated_keys.append(ck_copy)
        entry["config_keys"] = annotated_keys

        result.append(entry)

    return result


@router.get("/plugins")
async def list_plugins(
    plugin_manager=Depends(get_plugin_manager),
    settings=Depends(get_settings),
):
    """Return list of plugins with metadata, status, and config state."""
    metadata = plugin_manager.scan_metadata("plugins")
    plugins = _merge_plugins(metadata, plugin_manager.loaded_plugins, settings)
    return {"plugins": plugins}


class PluginConfigUpdate(BaseModel):
    settings: dict[str, Any] = {}
    secrets: dict[str, str] = {}


@router.post("/plugins/{plugin_id}/configure")
async def configure_plugin(
    plugin_id: str,
    update: PluginConfigUpdate,
    plugin_manager=Depends(get_plugin_manager),
    settings=Depends(get_settings),
    config_path_str: str = Depends(get_config_path),
    env_path_str: str = Depends(get_env_path),
):
    """Configure a plugin by writing secrets to .env and settings to config.yaml."""
    # Verify plugin exists in metadata
    metadata = plugin_manager.scan_metadata("plugins")
    plugin_meta = next((m for m in metadata if m["id"] == plugin_id), None)
    if not plugin_meta:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")

    config_path = Path(config_path_str)
    env_path = Path(env_path_str)

    # Write secrets to .env
    for key, value in update.secrets.items():
        _update_env_file(env_path, key.upper(), value)

    # Write settings to config.yaml
    if update.settings:
        yaml_config: dict = {}
        if config_path.exists():
            with open(config_path) as f:
                yaml_config = yaml.safe_load(f) or {}

        plugins_config = yaml_config.setdefault("plugins", {})
        plugin_config = plugins_config.setdefault(plugin_id, {})
        plugin_config.update(update.settings)

        with open(config_path, "w") as f:
            yaml.dump(yaml_config, f, default_flow_style=False)

    return {"status": "ok", "plugin_id": plugin_id}
