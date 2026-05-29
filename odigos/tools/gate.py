"""Declarative tool gate metadata (spec 2026-05-29-tool-catalog).

A ToolGate describes what must be true for a tool to register/activate.
It is PURE METADATA — it does not control registration (tools register
exactly as they do today via bootstrap guards + plugins). The catalog and
skill validator use it to distinguish 'tool is missing' from 'tool exists
but is inactive this run', and to explain why a tool is inactive.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ToolGate:
    kind: Literal["always", "plugin", "service", "config"] = "always"
    key: str = ""  # e.g. "gws", "kie_ai", "search_provider"

    def describe(self) -> str:
        if self.kind == "always":
            return "always available"
        if self.kind == "plugin":
            return f"requires the {self.key} plugin (enabled + its CLI installed)"
        if self.kind == "service":
            return f"requires the {self.key} service key"
        if self.kind == "config":
            return f"requires {self.key} to be configured"
        return self.kind

    @staticmethod
    def plugin(key: str) -> "ToolGate":
        return ToolGate("plugin", key)

    @staticmethod
    def service(key: str) -> "ToolGate":
        return ToolGate("service", key)

    @staticmethod
    def config(key: str) -> "ToolGate":
        return ToolGate("config", key)


ALWAYS = ToolGate("always")
