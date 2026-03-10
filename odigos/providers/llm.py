import json as json_module
import logging

import httpx

from odigos.providers.base import LLMProvider, LLMResponse, ToolCall

logger = logging.getLogger(__name__)


class LLMClient(LLMProvider):
    """OpenAI-compatible LLM provider with fallback support.

    Works with any OpenAI-compatible API: OpenRouter, Ollama, LM Studio,
    vLLM, OpenAI, and others.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        default_model: str,
        fallback_model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.fallback_model = fallback_model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def complete(self, messages: list[dict], **kwargs) -> LLMResponse:
        """Try default model, fall back to fallback model on failure."""
        model = kwargs.get("model", self.default_model)
        models_to_try = [model]
        if model != self.fallback_model:
            models_to_try.append(self.fallback_model)

        last_error: Exception | None = None
        for try_model in models_to_try:
            try:
                return await self._call(messages, try_model, **kwargs)
            except Exception as e:
                logger.warning("Model %s failed: %s", try_model, e)
                last_error = e

        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    async def _call(self, messages: list[dict], model: str, **kwargs) -> LLMResponse:
        """Make a single API call to the OpenAI-compatible endpoint."""
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
        }
        tools = kwargs.get("tools")
        if tools:
            payload["tools"] = tools

        url = f"{self.base_url}/chat/completions"
        response = await self._client.post(url, json=payload)

        if response.status_code != 200:
            raise RuntimeError(f"LLM API error {response.status_code}: {response.text}")

        data = response.json()
        usage = data.get("usage", {})
        message = data["choices"][0]["message"]

        tool_calls = None
        raw_tool_calls = message.get("tool_calls")
        if raw_tool_calls:
            tool_calls = []
            for tc in raw_tool_calls:
                args = tc["function"]["arguments"]
                if isinstance(args, str):
                    args = json_module.loads(args)
                tool_calls.append(ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=args,
                ))

        return LLMResponse(
            content=message.get("content") or "",
            model=data.get("model", model),
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            cost_usd=0.0,
            generation_id=data.get("id"),
            tool_calls=tool_calls,
        )

    async def close(self) -> None:
        await self._client.aclose()
