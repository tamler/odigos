"""Shared utility for the load-format-complete-parse LLM prompt cycle."""
from __future__ import annotations

import logging
from typing import Any

from odigos.core.json_utils import parse_json_response
from odigos.core.prompt_loader import load_prompt

logger = logging.getLogger(__name__)


async def run_prompt(
    provider,
    prompt_name: str,
    variables: dict[str, str],
    fallback: str,
    *,
    base_dir: str = "data/prompts",
    model: str | None = None,
    max_tokens: int = 800,
    temperature: float = 0.4,
) -> dict | None:
    """Load a prompt template, format it, call the LLM, parse JSON response.

    Returns parsed dict or None on any failure.
    """
    template = load_prompt(prompt_name, fallback, base_dir=base_dir)
    try:
        prompt_text = template.format(**variables)
    except KeyError as e:
        logger.warning("Prompt template %s missing variable: %s", prompt_name, e)
        return None

    try:
        use_model = model or getattr(provider, "background_model", None) or getattr(provider, "fallback_model", None)
        response = await provider.complete(
            [{"role": "user", "content": prompt_text}],
            model=use_model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return parse_json_response(response.content)
    except Exception:
        logger.warning("LLM prompt %s failed", prompt_name, exc_info=True)
        return None
