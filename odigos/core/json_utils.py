"""Shared utility for extracting JSON from LLM responses."""
from __future__ import annotations

import json
import re


def _find_largest_json_block(text: str) -> str | None:
    """Find the largest balanced {} block in text."""
    best = None
    for i, ch in enumerate(text):
        if ch == '{':
            depth = 0
            for j in range(i, len(text)):
                if text[j] == '{':
                    depth += 1
                elif text[j] == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = text[i:j+1]
                        if best is None or len(candidate) > len(best):
                            best = candidate
                        break
    return best


def parse_json_response(text: str) -> dict | None:
    """Extract JSON from an LLM response.

    Tries direct parse, then code block extraction, then balanced-brace fallback.
    """
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            pass
    candidate = _find_largest_json_block(text)
    if candidate:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            pass
    return None
