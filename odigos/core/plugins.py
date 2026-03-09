from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

from odigos.core.trace import Tracer

logger = logging.getLogger(__name__)


class PluginManager:
    """Discovers and loads plugins from a directory, wiring hooks into Tracer."""

    def __init__(self, tracer: Tracer) -> None:
        self.tracer = tracer
        self.loaded_plugins: list[dict] = []
        self._plugins_dir: str | None = None
        self._module_names: list[str] = []

    def load_all(self, plugins_dir: str) -> None:
        """Scan plugins_dir for *.py files and register their hooks."""
        for module_name in self._module_names:
            sys.modules.pop(module_name, None)
        self._module_names.clear()
        self.loaded_plugins = []
        self._plugins_dir = plugins_dir
        plugins_path = Path(plugins_dir)
        plugins_path.mkdir(parents=True, exist_ok=True)

        for py_file in sorted(plugins_path.glob("*.py")):
            if py_file.name.startswith("__"):
                continue
            self._load_plugin(py_file)

    def reload(self) -> None:
        """Clear all subscribers, remove cached modules, and reload plugins."""
        self.tracer.clear_subscribers()
        if self._plugins_dir is not None:
            self.load_all(self._plugins_dir)

    def _load_plugin(self, py_file: Path) -> None:
        """Import a single plugin file and register its hooks."""
        stem = py_file.stem
        module_name = f"odigos_plugin_{stem}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                logger.warning("Could not create module spec for %s", py_file)
                return
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception:
            logger.warning("Failed to import plugin %s", py_file, exc_info=True)
            return

        self._module_names.append(module_name)

        hooks = getattr(module, "hooks", None)
        if hooks is None:
            logger.warning("Plugin %s has no 'hooks' attribute, skipping", py_file)
            return

        if not isinstance(hooks, dict):
            logger.warning("Plugin %s 'hooks' is not a dict, skipping", py_file)
            return

        hook_count = 0
        for event_type, callback in hooks.items():
            if not callable(callback):
                logger.warning(
                    "Plugin %s hook '%s' is not callable, skipping",
                    py_file,
                    event_type,
                )
                continue
            self.tracer.subscribe(event_type, callback)
            hook_count += 1

        self.loaded_plugins.append({
            "name": stem,
            "file": str(py_file),
            "hook_count": hook_count,
        })
