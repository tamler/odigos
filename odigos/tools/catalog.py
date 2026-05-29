"""Authoritative catalog of every tool that exists in the codebase.

Independent of what registered this boot — built by walking BaseTool
subclasses and reading their (name, gate) class attrs. See spec
docs/superpowers/specs/2026-05-29-tool-catalog-design.md.

Import safety: imports only the CORE odigos.tools package so its tool
classes register with the interpreter. It does NOT import plugins/* (they
pull optional third-party deps that may be absent). Plugin-gated tools whose
classes live in odigos.tools (run_gws, run_browser, speak, transcribe_audio,
generate_image, ...) are still visible because their modules import cleanly.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil

from odigos.tools.base import BaseTool
from odigos.tools.gate import ALWAYS, ToolGate

logger = logging.getLogger(__name__)

_CACHE: dict[str, ToolGate] | None = None


def _import_all_tool_modules() -> None:
    """Import every module in odigos.tools so all BaseTool subclasses exist."""
    import odigos.tools as tools_pkg
    for mod in pkgutil.iter_modules(tools_pkg.__path__):
        if mod.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"odigos.tools.{mod.name}")
        except ImportError as e:  # optional third-party dep absent — expected, skip quietly
            logger.debug("catalog: skipping odigos.tools.%s (%s)", mod.name, e)
        except Exception as e:  # a real error in the module — surface it, don't hide a missing tool
            logger.warning(
                "catalog: unexpected error importing odigos.tools.%s — tool(s) may be missing from the catalog: %s",
                mod.name, e,
            )


def _walk_subclasses(cls: type) -> list[type]:
    out: list[type] = []
    for sub in cls.__subclasses__():
        out.append(sub)
        out.extend(_walk_subclasses(sub))
    return out


def build_catalog() -> dict[str, ToolGate]:
    """Return {tool_name: gate} for every concrete tool class. Memoized.

    Raises ValueError on a duplicate tool name (two classes claiming the
    same name is always a bug)."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    _import_all_tool_modules()
    catalog: dict[str, ToolGate] = {}
    for cls in _walk_subclasses(BaseTool):
        name = cls.__dict__.get("name")  # class's OWN name, not inherited
        if not isinstance(name, str) or not name:
            continue  # abstract intermediate (APITool, SubprocessTool, ...)
        gate = getattr(cls, "gate", None)
        if not isinstance(gate, ToolGate):
            gate = ALWAYS
        if name in catalog:
            raise ValueError(f"Duplicate tool name in catalog: {name!r}")
        catalog[name] = gate

    _CACHE = catalog
    return _CACHE


def reset_catalog_cache() -> None:
    """Clear the memoized catalog (tests only)."""
    global _CACHE
    _CACHE = None
