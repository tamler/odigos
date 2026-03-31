"""Routing rules loader -- shared between context assembly and executor."""

from __future__ import annotations

from pathlib import Path

from odigos.core.prompt_loader import load_prompt

# mtime-keyed cache for parsed routing rules
_routing_cache: tuple[float, dict] | None = None


def load_routing_rules() -> dict:
    """Load routing rules from data/agent/routing_rules.md.

    Returns a dict mapping classification name to its config dict.
    Values are parsed as booleans (true/false) or left as strings.
    Uses mtime-keyed cache so parsing only runs when the file changes.
    """
    global _routing_cache
    rules_path = Path("data/agent/routing_rules.md")
    if rules_path.exists():
        mtime = rules_path.stat().st_mtime
        if _routing_cache is not None and _routing_cache[0] == mtime:
            return _routing_cache[1]

    text = load_prompt("routing_rules.md", fallback="", base_dir="data/agent")
    rules: dict[str, dict] = {}
    current_section: str | None = None
    in_frontmatter = False
    for line in text.strip().split("\n"):
        line = line.strip()
        if line == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            continue
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

    if rules_path.exists():
        _routing_cache = (rules_path.stat().st_mtime, rules)
    return rules
