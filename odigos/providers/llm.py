"""Multi-provider OpenAI-compatible LLM client with intelligence-tier routing.

The client holds a registry of providers and models, and a routing table that
maps intelligence tiers (fast/smart/background/fallback) to model aliases.
Callers pass `intelligence="smart"` (or accept the default) and the client
dispatches to the correct provider, URL, key, and cost table automatically.
"""
from __future__ import annotations

import json as json_module
import logging
from typing import TYPE_CHECKING

import httpx

from odigos.providers.base import LLMProvider, LLMResponse, ToolCall

if TYPE_CHECKING:
    from odigos.config import ModelConfig, ProviderConfig

logger = logging.getLogger(__name__)


INTELLIGENCE_TIERS = ("fast", "smart", "background", "fallback")


def _is_anthropic_family(model_cfg, provider_cfg) -> bool:
    """True if the model should use Anthropic-style explicit cache breakpoints."""
    model_lc = (getattr(model_cfg, "id", "") or "").lower()
    url_lc = (getattr(provider_cfg, "base_url", "") or "").lower()
    return "claude" in model_lc or "anthropic" in url_lc


def _apply_anthropic_cache_control(
    messages: list[dict], model_cfg, provider_cfg,
) -> list[dict]:
    """Inject cache_control: ephemeral onto the last system message for Claude.

    For non-Claude providers this is a no-op — DeepSeek, OpenAI, and Meta all
    auto-cache stable prefixes without explicit breakpoints. For Claude-family
    models routed through OpenRouter or direct Anthropic, we need to mark the
    content block with cache_control so the system prompt is cacheable.

    Rewrites messages into Anthropic-style content blocks only for the system
    prompt(s) at the start; user/assistant messages stay in plain string form.
    """
    if not _is_anthropic_family(model_cfg, provider_cfg):
        return messages
    if not messages:
        return messages

    # Find the index of the last system-role message at the start of the list.
    last_system_idx = -1
    for i, m in enumerate(messages):
        if m.get("role") == "system":
            last_system_idx = i
        else:
            break
    if last_system_idx < 0:
        return messages

    rewritten: list[dict] = []
    for i, m in enumerate(messages):
        if i == last_system_idx:
            content = m.get("content", "")
            if isinstance(content, str):
                rewritten.append({
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": content,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                })
            else:
                rewritten.append(m)
        else:
            rewritten.append(m)
    return rewritten


class LLMClient(LLMProvider):
    """Multi-provider LLM client with intelligence-tier routing.

    Pass `intelligence="fast"|"smart"|"background"|"fallback"` to `.complete()`
    and the client picks the right model/provider/key/cost automatically.
    Unknown tiers fall back to `fast`.
    """

    def __init__(
        self,
        providers: dict[str, ProviderConfig],
        models: dict[str, ModelConfig],
        routing: dict[str, str],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        request_timeout: float = 60.0,
        connect_timeout: float = 10.0,
    ) -> None:
        if not providers:
            raise ValueError("LLMClient requires at least one provider")
        if not models:
            raise ValueError("LLMClient requires at least one model")
        if "fast" not in routing or not routing["fast"]:
            raise ValueError("LLMClient routing must define a 'fast' tier")

        self._providers = dict(providers)
        self._models = dict(models)
        self._routing = dict(routing)
        self.max_tokens = max_tokens
        self.temperature = temperature

        # One httpx client per provider — separate base_url and auth headers.
        self._clients: dict[str, httpx.AsyncClient] = {}
        for name, p in providers.items():
            headers = {"Content-Type": "application/json"}
            if p.api_key:
                headers["Authorization"] = f"Bearer {p.api_key}"
            self._clients[name] = httpx.AsyncClient(
                timeout=httpx.Timeout(request_timeout, connect=connect_timeout),
                headers=headers,
            )

        self._validate_routing()

    def _validate_routing(self) -> None:
        """Fail fast if a routing tier points at a missing model or provider."""
        for tier, alias in self._routing.items():
            if not alias:
                continue
            if alias not in self._models:
                raise ValueError(
                    f"Routing tier '{tier}' references unknown model '{alias}'"
                )
            provider_name = self._models[alias].provider
            if provider_name not in self._providers:
                raise ValueError(
                    f"Model '{alias}' references unknown provider '{provider_name}'"
                )

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------
    def resolve(self, intelligence: str = "fast") -> ModelConfig:
        """Return the ModelConfig bound to a given intelligence tier.

        Unknown or empty tiers fall back to 'fast'. If the tier has no explicit
        alias, falls through to 'fast'.
        """
        alias = self._routing.get(intelligence) or self._routing.get("fast")
        if alias not in self._models:
            raise RuntimeError(f"Routing points at missing model alias '{alias}'")
        return self._models[alias]

    def _find_model_by_id(self, model_id: str) -> ModelConfig | None:
        """Look up a ModelConfig by either its alias or its literal id."""
        if model_id in self._models:
            return self._models[model_id]
        for m in self._models.values():
            if m.id == model_id:
                return m
        return None

    @property
    def default_model(self) -> str:
        """Resolved id of the `fast` tier — used by callers that log/introspect."""
        return self.resolve("fast").id

    @property
    def fallback_model(self) -> str:
        """Resolved id of the `fallback` tier, or empty if none configured."""
        alias = self._routing.get("fallback")
        if not alias or alias not in self._models:
            return ""
        return self._models[alias].id

    @property
    def supports_explicit_cache(self) -> bool:
        """Does the `fast` tier's provider need explicit cache_control breakpoints?"""
        model_cfg = self.resolve("fast")
        provider = self._providers.get(model_cfg.provider)
        model_lc = (model_cfg.id or "").lower()
        url_lc = (provider.base_url if provider else "").lower()
        return "claude" in model_lc or "anthropic" in url_lc

    # ------------------------------------------------------------------
    # Public API: complete / stream_complete / complete_json
    # ------------------------------------------------------------------
    async def complete(self, messages: list[dict], **kwargs) -> LLMResponse:
        """Dispatch a completion by intelligence tier.

        Accepts either `intelligence="fast"|"smart"|"background"|"fallback"`
        or a literal `model="..."` kwarg (model id or alias). On failure, retries
        with the `fallback` tier if one is configured and distinct.
        """
        intelligence = kwargs.pop("intelligence", "fast")
        literal_model = kwargs.pop("model", None)

        if literal_model:
            primary = self._find_model_by_id(literal_model)
            if primary is None:
                # Unknown literal — treat as passthrough with no cost tracking.
                primary = self._synthesize_model(literal_model)
        else:
            primary = self.resolve(intelligence)

        models_to_try = [primary]
        fb_alias = self._routing.get("fallback")
        if intelligence != "fallback" and fb_alias and fb_alias in self._models:
            fb = self._models[fb_alias]
            if fb.id != primary.id:
                models_to_try.append(fb)

        last_error: Exception | None = None
        for model_cfg in models_to_try:
            try:
                return await self._call(messages, model_cfg, **kwargs)
            except Exception as e:
                logger.warning("Model %s failed: %s", model_cfg.id, e)
                last_error = e

        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    def _synthesize_model(self, model_id: str) -> ModelConfig:
        """Build an ephemeral ModelConfig for a literal passthrough id.

        Uses the first configured provider as the destination. Cost falls back
        to the safety rates in _call() since rates are 0.
        """
        from odigos.config import ModelConfig
        first_provider = next(iter(self._providers.keys()))
        return ModelConfig(provider=first_provider, id=model_id)

    async def _call(
        self, messages: list[dict], model_cfg: ModelConfig, **kwargs,
    ) -> LLMResponse:
        provider = self._providers[model_cfg.provider]
        client = self._clients[model_cfg.provider]

        # For Anthropic-family models (Claude via direct or OpenRouter), add
        # explicit cache_control breakpoints. DeepSeek, OpenAI, and most other
        # providers auto-cache stable prefixes without needing breakpoints, so
        # this is Anthropic-only extra work.
        out_messages = _apply_anthropic_cache_control(messages, model_cfg, provider)

        payload: dict = {
            "model": model_cfg.id,
            "messages": out_messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
        }
        tools = kwargs.get("tools")
        if tools:
            payload["tools"] = tools
        tool_choice = kwargs.get("tool_choice")
        if tool_choice and tools:
            payload["tool_choice"] = tool_choice
        response_format = kwargs.get("response_format")
        if response_format:
            payload["response_format"] = response_format

        logger.info(
            "LLM request: provider=%s model=%s tools=%d messages=%d",
            model_cfg.provider, model_cfg.id,
            len(tools) if tools else 0, len(messages),
        )

        url = f"{provider.base_url.rstrip('/')}/chat/completions"
        response = await client.post(url, json=payload)

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

        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        if not cached:
            cached = usage.get("cache_read_input_tokens", 0)

        cost = usage.get("cost") or 0.0
        if not cost:
            cost = self._compute_cost(model_cfg, tokens_in, tokens_out)

        return LLMResponse(
            content=message.get("content") or "",
            model=data.get("model", model_cfg.id),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            generation_id=data.get("id"),
            tool_calls=tool_calls,
            cached_tokens=cached,
        )

    def _compute_cost(
        self, model_cfg: ModelConfig, tokens_in: int, tokens_out: int,
    ) -> float:
        """Fall-back cost computation using the model's declared rates.

        If a model has zero declared rates, we don't invent a number — the
        budget tracker can still enforce limits using provider-reported cost
        when the API supplies one.
        """
        rate_in = model_cfg.cost_in_per_mtok
        rate_out = model_cfg.cost_out_per_mtok
        return (tokens_in * rate_in / 1_000_000) + (tokens_out * rate_out / 1_000_000)

    async def stream_complete(self, messages: list[dict], **kwargs):
        """Stream response tokens from the OpenAI-compatible API.

        Yields (chunk_text, None) for content, then (None, LLMResponse) at the end.
        Falls back to non-streaming if the model returns tool_calls.
        """
        intelligence = kwargs.pop("intelligence", "fast")
        literal_model = kwargs.pop("model", None)

        if literal_model:
            model_cfg = self._find_model_by_id(literal_model) or self._synthesize_model(literal_model)
        else:
            model_cfg = self.resolve(intelligence)

        provider = self._providers[model_cfg.provider]
        client = self._clients[model_cfg.provider]

        out_messages = _apply_anthropic_cache_control(messages, model_cfg, provider)

        payload: dict = {
            "model": model_cfg.id,
            "messages": out_messages,
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

        url = f"{provider.base_url.rstrip('/')}/chat/completions"
        try:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code != 200:
                    resp = await self.complete(messages, model=model_cfg.id, **kwargs)
                    yield resp.content, resp
                    return

                full_content = ""
                response_model = model_cfg.id
                generation_id = None
                tool_calls_data: list = []
                tokens_in = 0
                tokens_out = 0
                provider_cost = 0.0
                usage: dict = {}

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

                    content = delta.get("content")
                    if content:
                        full_content += content
                        yield content, None

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

                    usage = chunk.get("usage") or choices[0].get("usage", {})
                    if usage:
                        tokens_in = usage.get("prompt_tokens", 0)
                        tokens_out = usage.get("completion_tokens", 0)
                        provider_cost = usage.get("cost") or 0.0

                cached = 0
                if usage:
                    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
                    if not cached:
                        cached = usage.get("cache_read_input_tokens", 0)

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

                cost = provider_cost or self._compute_cost(model_cfg, tokens_in, tokens_out)
                final = LLMResponse(
                    content=full_content,
                    model=response_model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost,
                    generation_id=generation_id,
                    tool_calls=parsed_tool_calls,
                    cached_tokens=cached,
                )
                yield None, final

        except Exception as e:
            logger.warning("Streaming failed, falling back to non-streaming: %s", e)
            resp = await self.complete(messages, model=model_cfg.id, **kwargs)
            yield resp.content, resp

    async def complete_json(
        self,
        messages: list[dict],
        schema: dict | None = None,
        **kwargs,
    ) -> tuple[dict, bool]:
        """LLM call with 3-tier JSON fallback. Returns (parsed_dict, success)."""
        import json as _json

        from odigos.core.json_utils import parse_json_response

        if schema:
            try:
                resp = await self.complete(
                    messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": "response", "schema": schema},
                    },
                    **kwargs,
                )
                parsed = _json.loads(resp.content)
                return parsed, True
            except Exception:
                pass

        try:
            resp = await self.complete(
                messages,
                response_format={"type": "json_object"},
                **kwargs,
            )
            parsed = _json.loads(resp.content)
            if schema:
                try:
                    import jsonschema

                    jsonschema.validate(parsed, schema)
                except ImportError:
                    pass
                except Exception as e:
                    logger.warning("JSON schema validation failed (tier 2): %s", str(e)[:100])
                    return {}, False
            return parsed, True
        except Exception:
            pass

        try:
            resp = await self.complete(messages, **kwargs)
            parsed = parse_json_response(resp.content)
            if parsed is not None:
                if schema:
                    try:
                        import jsonschema

                        jsonschema.validate(parsed, schema)
                    except ImportError:
                        pass
                    except Exception as e:
                        logger.warning("JSON schema validation failed (tier 3): %s", str(e)[:100])
                        return {}, False
                return parsed, True
        except Exception:
            pass

        return {}, False

    async def close(self) -> None:
        for client in self._clients.values():
            await client.aclose()
