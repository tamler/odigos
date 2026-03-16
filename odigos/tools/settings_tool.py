from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.config import Settings

ALLOWED_KEYS = [
    "browser.enabled",
    "browser.timeout",
    "gws.enabled",
    "gws.timeout",
    "stt.enabled",
    "stt.model",
    "tts.enabled",
    "tts.voice",
    "searxng_url",
    "approval.enabled",
    "approval.tools",
    "heartbeat.interval_seconds",
    "heartbeat.idle_think_interval",
]

BLOCKED_PREFIXES = ["api_key", "llm_api_key", "budget", "llm"]


class ManageSettingsTool(BaseTool):
    name = "manage_settings"
    description = (
        "Read and update the agent's own configuration. "
        "Actions: list (show allowed keys), read (get a value), write (set a value and persist)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "read", "write"],
                "description": "The action to perform.",
            },
            "key": {
                "type": "string",
                "description": "Dotted setting key, e.g. 'browser.enabled'. Required for read/write.",
            },
            "value": {
                "description": "New value to set. Required for write.",
            },
        },
        "required": ["action"],
    }

    def __init__(self, settings: Settings, config_path: str) -> None:
        self.settings = settings
        self.config_path = config_path

    def _is_blocked(self, key: str) -> bool:
        for prefix in BLOCKED_PREFIXES:
            if key == prefix or key.startswith(prefix + "."):
                return True
        return False

    def _resolve(self, key: str):
        """Traverse dotted key on the settings object and return the value."""
        parts = key.split(".")
        obj = self.settings
        for part in parts:
            obj = getattr(obj, part)
        return obj

    async def execute(self, params: dict) -> ToolResult:
        action = params.get("action")

        if action == "list":
            return ToolResult(success=True, data="\n".join(ALLOWED_KEYS))

        key = params.get("key", "")

        if not key:
            return ToolResult(success=False, data="", error="key is required for read/write")

        if self._is_blocked(key):
            return ToolResult(success=False, data="", error=f"Access denied: '{key}' is a protected setting")

        if key not in ALLOWED_KEYS:
            return ToolResult(success=False, data="", error=f"Unknown setting: '{key}'. Use action=list to see allowed keys.")

        if action == "read":
            try:
                value = self._resolve(key)
                return ToolResult(success=True, data=f"{key} = {value!r}")
            except AttributeError:
                return ToolResult(success=False, data="", error=f"Setting not found: '{key}'")

        if action == "write":
            if "value" not in params:
                return ToolResult(success=False, data="", error="value is required for write")

            value = params["value"]

            # Update in-memory settings via dotted key
            parts = key.split(".")
            if len(parts) == 1:
                object.__setattr__(self.settings, parts[0], value)
            else:
                parent = self.settings
                for part in parts[:-1]:
                    parent = getattr(parent, part)
                object.__setattr__(parent, parts[-1], value)

            # Persist to config.yaml
            config_file = Path(self.config_path)
            data: dict = {}
            if config_file.exists():
                with open(config_file) as f:
                    data = yaml.safe_load(f) or {}

            # Build nested dict for dotted key
            target = data
            for part in parts[:-1]:
                if part not in target or not isinstance(target[part], dict):
                    target[part] = {}
                target = target[part]
            target[parts[-1]] = value

            with open(config_file, "w") as f:
                yaml.dump(data, f, default_flow_style=False)

            return ToolResult(success=True, data=f"{key} updated to {value!r}")

        return ToolResult(success=False, data="", error=f"Unknown action: '{action}'")
