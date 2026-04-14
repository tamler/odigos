from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.config import Settings

ALLOWED_KEYS = [
    "browser.enabled",
    "browser.timeout",
    "gws.enabled",
    "gws.timeout",
    "voice.stt_provider",
    "voice.tts_provider",
    "voice.tts_voice",
    "voice.groq_model",
    "agent.concise_mode",
    "searxng_url",
    "approval.enabled",
    "approval.tools",
    "heartbeat.interval_seconds",
    "heartbeat.idle_think_interval",
    "heartbeat.morning_briefing",
]

BLOCKED_PREFIXES = ["api_key", "providers", "models", "llm", "budget"]


class ManageSettingsTool(BaseTool):
    name = "configure_settings"
    category = "memory"
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
                "type": "string",
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

    def _resolve(self, key: str) -> Any:
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

            # Protected keys that cannot be changed via the agent
            _PROTECTED_KEYS = {
                "access.supervised",
                "api_key", "session_secret",
                "mesh.enabled", "peers",
            }
            if key in _PROTECTED_KEYS or key.startswith("peers."):
                return ToolResult(success=False, data="", error=f"Setting '{key}' is protected and cannot be changed by the agent")

            value = params["value"]

            # Persist to config.yaml first (validate on reload)
            from odigos import aio
            config_file = Path(self.config_path)
            data: dict = await aio.read_yaml(config_file) if config_file.exists() else {}

            # Build nested dict for dotted key
            parts = key.split(".")
            target = data
            for part in parts[:-1]:
                if part not in target or not isinstance(target[part], dict):
                    target[part] = {}
                target = target[part]
            target[parts[-1]] = value

            await aio.write_yaml(config_file, data)

            # Reload all settings from disk (validates via Pydantic)
            try:
                from odigos.config import reload_into
                reload_into(self.settings, self.config_path)
            except Exception as exc:
                return ToolResult(
                    success=False, data="",
                    error=f"Setting written but validation failed: {exc}",
                )

            return ToolResult(success=True, data=f"{key} updated to {value!r}")

        return ToolResult(success=False, data="", error=f"Unknown action: '{action}'")
