from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.core.plugin_context import PluginContext

logger = logging.getLogger(__name__)


class PluginManager:
    """Discovers and loads plugins from a directory.

    Supports two plugin patterns:
    1. New: register(ctx) function -- receives PluginContext for registering tools/channels/providers
    2. Legacy: hooks dict -- event type -> callback, wired into Tracer
    """

    def __init__(self, plugin_context: PluginContext | None = None, tracer=None) -> None:
        self._ctx = plugin_context
        self._tracer = tracer or (plugin_context.tracer if plugin_context else None)
        self.loaded_plugins: list[dict] = []
        self._plugins_dir: str | None = None
        self._module_names: list[str] = []

    def load_all(self, plugins_dir: str) -> None:
        """Scan plugins_dir for plugin files/directories and load them."""
        self._plugins_dir = plugins_dir
        plugins_path = Path(plugins_dir)
        plugins_path.mkdir(parents=True, exist_ok=True)

        # Load .py files directly
        for py_file in sorted(plugins_path.glob("*.py")):
            if py_file.name.startswith("__"):
                continue
            self._load_plugin(py_file)

        # Load directories with __init__.py
        for subdir in sorted(plugins_path.iterdir()):
            if subdir.is_dir() and not subdir.name.startswith("__"):
                init = subdir / "__init__.py"
                if init.exists():
                    self._load_plugin(init, name_override=subdir.name)

        # Recurse into category subdirectories (providers/, tools/)
        # Note: channels/ is loaded separately via load_channels() (phase 2)
        for category_dir in sorted(plugins_path.iterdir()):
            if category_dir.is_dir() and category_dir.name in ("providers", "tools"):
                for subdir in sorted(category_dir.iterdir()):
                    if subdir.is_dir() and not subdir.name.startswith("__"):
                        init = subdir / "__init__.py"
                        if init.exists():
                            self._load_plugin(init, name_override=subdir.name)
                    elif subdir.suffix == ".py" and not subdir.name.startswith("__"):
                        self._load_plugin(subdir)

    def load_channels(self, plugins_dir: str) -> None:
        """Phase 2: Load channel plugins that need AgentService.

        Scans for plugins in a 'channels' subdirectory.
        These are loaded after the Agent is created and AgentService is set on the context.
        """
        channels_path = Path(plugins_dir) / "channels"
        if not channels_path.exists():
            return

        for subdir in sorted(channels_path.iterdir()):
            if subdir.is_dir() and not subdir.name.startswith("__"):
                init = subdir / "__init__.py"
                if init.exists():
                    self._load_plugin(init, name_override=subdir.name)
            elif subdir.suffix == ".py" and not subdir.name.startswith("__"):
                self._load_plugin(subdir)

    def reload(self) -> None:
        """Clear and reload all plugins."""
        if self._tracer:
            self._tracer.clear_subscribers()
        for module_name in self._module_names:
            sys.modules.pop(module_name, None)
        self._module_names.clear()
        self.loaded_plugins = []
        if self._plugins_dir is not None:
            self.load_all(self._plugins_dir)

    def _load_plugin(self, py_file: Path, name_override: str | None = None) -> None:
        """Import a plugin and register via register(ctx) or legacy hooks."""
        stem = name_override or py_file.stem
        module_name = f"odigos_plugin_{stem}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                logger.warning("Could not create module spec for %s", py_file)
                return
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as e:
            logger.warning("Failed to import plugin %s", py_file, exc_info=True)
            self.loaded_plugins.append({"name": stem, "file": str(py_file), "pattern": "import", "status": "error", "error_message": str(e)})
            return

        self._module_names.append(module_name)

        # Try new pattern: register(ctx)
        register_fn = getattr(module, "register", None)
        if register_fn is not None and callable(register_fn) and self._ctx is not None:
            try:
                register_fn(self._ctx)
                self.loaded_plugins.append({"name": stem, "file": str(py_file), "pattern": "register", "status": "active"})
                return
            except Exception as e:
                logger.warning("Plugin %s register() failed", py_file, exc_info=True)
                self.loaded_plugins.append({"name": stem, "file": str(py_file), "pattern": "register", "status": "error", "error_message": str(e)})
                return

        # Fall back to legacy pattern: hooks dict
        hooks = getattr(module, "hooks", None)
        if hooks and isinstance(hooks, dict) and self._tracer:
            hook_count = 0
            for event_type, callback in hooks.items():
                if callable(callback):
                    self._tracer.subscribe(event_type, callback)
                    hook_count += 1
            self.loaded_plugins.append({"name": stem, "file": str(py_file), "pattern": "hooks", "hook_count": hook_count, "status": "active"})
            return

        logger.warning("Plugin %s has no register() or hooks, skipping", py_file)
        self.loaded_plugins.append({"name": stem, "file": str(py_file), "pattern": "none", "status": "error", "error_message": "No register() function or hooks dict found"})

    def scan_metadata(self, plugins_dir: str) -> list[dict]:
        """Scan plugin directories for plugin.yaml metadata files."""
        results = []
        plugins_path = Path(plugins_dir)
        if not plugins_path.exists():
            return results

        for subdir in sorted(plugins_path.iterdir()):
            if not subdir.is_dir() or subdir.name.startswith("__"):
                continue

            # Category subdirs (providers/, tools/, channels/)
            if subdir.name in ("providers", "tools", "channels"):
                for nested in sorted(subdir.iterdir()):
                    if nested.is_dir() and not nested.name.startswith("__"):
                        meta = self._read_plugin_yaml(nested)
                        if meta:
                            results.append(meta)
                continue

            meta = self._read_plugin_yaml(subdir)
            if meta:
                results.append(meta)

        return results

    @staticmethod
    def _read_plugin_yaml(plugin_dir: Path) -> dict | None:
        """Read and parse a plugin.yaml, falling back to defaults."""
        import yaml

        init = plugin_dir / "__init__.py"
        if not init.exists():
            return None

        yaml_file = plugin_dir / "plugin.yaml"
        if yaml_file.exists():
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f) or {}
                data.setdefault("id", plugin_dir.name)
                data.setdefault("name", plugin_dir.name)
                data.setdefault("description", "")
                data.setdefault("category", "tools")
                data.setdefault("requires", [])
                data.setdefault("config_keys", [])
                return data
            except Exception:
                logger.warning("Failed to parse %s", yaml_file)

        return {
            "id": plugin_dir.name,
            "name": plugin_dir.name,
            "description": "",
            "category": "tools",
            "requires": [],
            "config_keys": [],
        }
