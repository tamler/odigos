from __future__ import annotations

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
        request_timeout: float = 60.0,
        connect_timeout: float = 10.0,
        cost_per_million_tokens: float = 0.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.fallback_model = fallback_model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._cost_per_million = cost_per_million_tokens
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(request_timeout, connect=connect_timeout),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def complete(self, messages: list[dict], **kwargs) -> LLMResponse:
        """Try default model, fall back to fallback model on failure."""
        model = kwargs.pop("model", self.default_model)
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
        tool_choice = kwargs.get("tool_choice")
        if tool_choice and tools:
            payload["tool_choice"] = tool_choice

        logger.info(
            "LLM request: model=%s, tools=%d, messages=%d, tool_choice=%s",
            model, len(tools) if tools else 0, len(messages), tool_choice,
        )

        url = f"{self.base_url}/chat/completions"
        response = await self._client.post(url, json=payload)

        if response.status_code != 200:
            raise RuntimeError(f"LLM API error {response.status_code}: {response.text}")

        data = response.json()
        usage = data.get("usage", {})
        message = data["choices"][0]["message"]

        logger.info(
            "LLM response: model=%s, has_tool_calls=%s, content_preview=%s",
            model,
            bool(message.get("tool_calls")),
            (message.get("content") or "")[:80],
        )

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

        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)
        # Use provider-reported cost if available; fall back to configured rate
        cost = usage.get("cost") or 0.0
        if not cost and self._cost_per_million and (tokens_in or tokens_out):
            cost = (tokens_in + tokens_out) * self._cost_per_million / 1_000_000

        return LLMResponse(
            content=message.get("content") or "",
            model=data.get("model", model),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            generation_id=data.get("id"),
            tool_calls=tool_calls,
        )

    async def stream_complete(self, messages: list[dict], **kwargs):
        """Stream response tokens from the OpenAI-compatible API.

        Yields (chunk_text, None) for content, then (None, LLMResponse) at the end.
        Falls back to non-streaming if the model returns tool_calls (can't stream tools).
        """
        model = kwargs.pop("model", self.default_model)

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
            "stream": True,
        }
        tools = kwargs.get("tools")
        if tools:
            payload["tools"] = tools
        tool_choice = kwargs.get("tool_choice")
        if tool_choice and tools:
            payload["tool_choice"] = tool_choice

        url = f"{self.base_url}/chat/completions"
        try:
            async with self._client.stream("POST", url, json=payload) as response:
                if response.status_code != 200:
                    # Fall back to non-streaming on error
                    resp = await self.complete(messages, model=model, **kwargs)
                    yield resp.content, resp
                    return

                full_content = ""
                response_model = model
                generation_id = None
                tool_calls_data: list = []
                tokens_in = 0
                tokens_out = 0
                provider_cost = 0.0

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json_module.loads(data_str)
                    except json_module.JSONDecodeError:
                        continue

                    if not generation_id:
                        generation_id = chunk.get("id")
                    if chunk.get("model"):
                        response_model = chunk["model"]

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})

                    # Content chunk
                    content = delta.get("content")
                    if content:
                        full_content += content
                        yield content, None

                    # Tool call chunks (accumulate, don't stream)
                    if delta.get("tool_calls"):
                        for tc_delta in delta["tool_calls"]:
                            idx = tc_delta.get("index", 0)
                            while len(tool_calls_data) <= idx:
                                tool_calls_data.append({"id": "", "name": "", "arguments": ""})
                            if tc_delta.get("id"):
                                tool_calls_data[idx]["id"] = tc_delta["id"]
                            fn = tc_delta.get("function", {})
                            if fn.get("name"):
                                tool_calls_data[idx]["name"] = fn["name"]
                            if fn.get("arguments"):
                                tool_calls_data[idx]["arguments"] += fn["arguments"]

                    # Usage in final chunk (some providers include cost here)
                    usage = chunk.get("usage") or choices[0].get("usage", {})
                    if usage:
                        tokens_in = usage.get("prompt_tokens", 0)
                        tokens_out = usage.get("completion_tokens", 0)
                        provider_cost = usage.get("cost") or 0.0

                # Build tool calls if present
                parsed_tool_calls = None
                if tool_calls_data:
                    parsed_tool_calls = []
                    for tc in tool_calls_data:
                        args = tc["arguments"]
                        if isinstance(args, str):
                            try:
                                args = json_module.loads(args)
                            except json_module.JSONDecodeError:
                                args = {}
                        parsed_tool_calls.append(ToolCall(
                            id=tc["id"], name=tc["name"], arguments=args,
                        ))

                cost = provider_cost
                if not cost and self._cost_per_million and (tokens_in or tokens_out):
                    cost = (tokens_in + tokens_out) * self._cost_per_million / 1_000_000
                final = LLMResponse(
                    content=full_content,
                    model=response_model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost,
                    generation_id=generation_id,
                    tool_calls=parsed_tool_calls,
                )
                yield None, final

        except Exception as e:
            logger.warning("Streaming failed, falling back to non-streaming: %s", e)
            resp = await self.complete(messages, model=model, **kwargs)
            yield resp.content, resp

    async def close(self) -> None:
        await self._client.aclose()
