"""Routing rules loader -- shared between context assembly and executor."""

from __future__ import annotations

from odigos.core.prompt_loader import load_prompt


def load_routing_rules() -> dict:
    """Load routing rules from data/agent/routing_rules.md.

    Returns a dict mapping classification name to its config dict.
    Values are parsed as booleans (true/false) or left as strings.
    """
    text = load_prompt("routing_rules.md", fallback="", base_dir="data/agent")
    rules: dict[str, dict] = {}
    current_section: str | None = None
    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1]
            rules[current_section] = {}
        elif ":" in line and current_section:
            key, val = line.split(":", 1)
            val = val.strip()
            if val.lower() in ("true", "false"):
                rules[current_section][key.strip()] = val.lower() == "true"
            else:
                rules[current_section][key.strip()] = val
    return rules
