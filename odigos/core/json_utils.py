"""Shared utility for extracting JSON from LLM responses."""
from __future__ import annotations

import json
import re


def parse_json_response(text: str) -> dict | None:
    """Extract JSON from an LLM response.

    Tries direct parse, then code block extraction, then regex fallback.
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
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, TypeError):
            pass
    return None
