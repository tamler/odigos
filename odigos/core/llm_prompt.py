"""Shared LLM call utilities with retry, logging, and cost tracking."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from odigos.core.json_utils import parse_json_response
from odigos.core.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_TRANSIENT_EXCEPTIONS = (TimeoutError, ConnectionError, OSError)


async def call_llm(
    provider,
    messages: list[dict],
    *,
    model: str | None = None,
    max_tokens: int = 800,
    temperature: float = 0.4,
    log_name: str = "llm_call",
    retries: int = 1,
    response_format=None,
):
    """Standard LLM call with retry on transient errors and logging.

    Returns LLMResponse or None on failure.
    """
    use_model = model or getattr(provider, "background_model", None) or getattr(provider, "fallback_model", None)

    for attempt in range(retries + 1):
        try:
            kwargs = {"model": use_model, "max_tokens": max_tokens, "temperature": temperature}
            if response_format:
                kwargs["response_format"] = response_format
            response = await provider.complete(messages, **kwargs)
            logger.debug(
                "%s: %d in / %d out / $%.5f",
                log_name, response.tokens_in, response.tokens_out, response.cost_usd,
            )
            return response
        except _TRANSIENT_EXCEPTIONS:
            if attempt < retries:
                await asyncio.sleep(1.0 * (attempt + 1))
                logger.info("%s: transient error, retrying (%d/%d)", log_name, attempt + 1, retries)
                continue
            logger.warning("%s: failed after %d retries", log_name, retries, exc_info=True)
            return None
        except Exception:
            logger.warning("%s: non-transient failure", log_name, exc_info=True)
            return None


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
    response_format=None,
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

    response = await call_llm(
        provider, [{"role": "user", "content": prompt_text}],
        model=model, max_tokens=max_tokens, temperature=temperature,
        log_name=f"prompt:{prompt_name}", response_format=response_format,
    )
    if response is None:
        return None
    return parse_json_response(response.content)
