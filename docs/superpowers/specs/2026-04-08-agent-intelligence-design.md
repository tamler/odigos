# Agent Intelligence — Context & Retrieval Improvements

**Date:** 2026-04-08
**Status:** Approved
**Goal:** Four improvements to how the agent assembles context, retrieves knowledge, and communicates with LLM providers — structured output fallback, static-first prompt ordering with provider-aware caching, pyramid expansion in recall, and parallel tool call instruction.

## Context

The agent's context assembly (`context.py`) and retrieval (`manager.py`) have known inefficiencies: every RAG result gets the same 500-char treatment regardless of relevance, the system prompt doesn't optimize for provider caching, JSON extraction from LLMs fails silently on malformed responses, and the model isn't explicitly told to batch independent tool calls. These are quick wins with high impact.

## Design

### 1. Structured Output Fallback

A `complete_json()` method on the LLM provider that guarantees parsed JSON output via a three-tier fallback:

1. **json_schema** — strict mode with a schema. Tried first if provider supports it.
2. **json_object** — guaranteed JSON, no schema. Fallback if strict mode fails or returns 400.
3. **Regex extraction** — find the largest balanced `{}` block from freeform text (not just first match). Last resort.

```python
class LLMClient:
    async def complete_json(
        self,
        messages: list[dict],
        schema: dict | None = None,
        **kwargs,
    ) -> tuple[dict, bool]:
        """LLM call that guarantees parsed JSON output.
        Returns (parsed_dict, success). Empty dict + False on failure."""
```

The method:
1. Tries `complete()` with `response_format={"type": "json_schema", "json_schema": schema}` if schema provided
2. On 400/error, retries with `response_format={"type": "json_object"}`
3. On parse failure, falls back to regex extraction (largest balanced `{}` block)
4. **Schema validation:** If `schema` was provided and we fell back to tier 2 or 3, validate the parsed JSON against the schema locally (jsonschema). Log and return `({}, False)` if invalid.
5. Returns `({}, False)` if all three fail (logged at ERROR for visibility)

Callers can check the `success` bool to distinguish "nothing to extract" (`({"entities": []}, True)`) from "extraction failed" (`({}, False)`).

**Callers that switch to `complete_json()`:**
- `odigos/memory/extractor.py` — entity/fact extraction
- `odigos/core/classifier.py` — query classification
- `odigos/core/heartbeat/profiling.py` — user profile analysis, experience extraction
- `odigos/core/evaluator.py` — response evaluation

Each caller replaces its manual `json.loads()` + try/except with a single `provider.complete_json()` call.

### 2. Static-First Prompt Ordering + Provider-Aware Caching

**Convention:** Every LLM call orders content static-first, dynamic-last. This maximizes automatic prefix caching on Groq, OpenAI, and Gemini without code changes.

**Main chat path (`build_planned()`):**

New ordering:
1. Identity (static)
2. Tool instruction (static)
3. Response style (static per classification)
4. Active skill instructions (static per conversation)
5. --- cache boundary ---
6. Experiences (dynamic)
7. User facts (dynamic)
8. User profile (dynamic)
9. RAG results (dynamic)
10. History summary (dynamic)

**Anthropic-specific caching:** When the provider targets Claude models, wrap the static prefix (sections 1-4) in a content block with `cache_control: {type: "ephemeral"}`:

```python
@property
def supports_explicit_cache(self) -> bool:
    """Does this provider need explicit cache_control breakpoints?"""
    model = (self.default_model or "").lower()
    url = (self.base_url or "").lower()
    return "claude" in model or "anthropic" in url
```

When `supports_explicit_cache` is True, the system prompt message is formatted as:

```python
{"role": "system", "content": [
    {"type": "text", "text": static_prefix, "cache_control": {"type": "ephemeral"}},
    {"type": "text", "text": dynamic_suffix},
]}
```

When False (Groq, OpenAI, etc.), the system prompt stays a plain string — the provider handles caching automatically based on prefix matching. Use exactly one cache breakpoint to stay well within Anthropic's 4-breakpoint limit.

**Stable sort for cache consistency:** Tool definitions and skill instructions within the static prefix must be sorted alphabetically. Non-deterministic ordering (dict iteration, dynamic loading order) would change the prefix text on every call, invalidating the cache.

**All other LLM calls:** The prompt template is already the first message in classifier, evaluator, profiling, and extraction calls. No reordering needed — just document the convention: static prompt templates first, variable data last.

**Observability:** Add `cached_tokens: int = 0` to the `LLMResponse` dataclass in `odigos/providers/base.py`. Populate from `usage.prompt_tokens_details.cached_tokens` (Groq/OpenAI) or `cache_read_input_tokens` (Anthropic). Log cache hit rate periodically.

### 3. Pyramid Expansion in Recall

Current: `recall()` returns 500-char `content_preview` for all results. New: three-tier content loading gated by relevance score.

**Tier 1 — Summaries (all results):**
- `content_preview` (500 chars) for all top-k results
- One DB query, already happening

**Tier 2 — Full content (high-relevance results):**
- For results with cross-encoder score above `EXPANSION_SCORE_THRESHOLD` (default 0.4), up to `MAX_FULL_EXPANSIONS` (default 3)
- Load from source: `document_text.full_text` for documents, `messages.content` for conversation memories
- Replace 500-char preview with full text in context

**Token budget enforcement:**
- `recall()` adds `token_budget: int = 2000` parameter
- **Expansions first:** Calculate token cost for Tier 2 full-text expansions (highest relevance first), reserve that budget
- **Summaries fill remainder:** Tier 1 summaries fill the remaining budget greedily by score
- **Clean truncation:** If a full expansion exceeds its allocation, truncate at the nearest sentence boundary and append `[... truncated ...]` — never mid-sentence or mid-code-block
- **Bulk fetch:** Load all Tier 2 full texts in a single DB query (not N+1)

**Score threshold note:** Cross-encoder scores (ms-marco-MiniLM) are not normalized 0-1. The 0.4 default may need calibration. Use `estimate_tokens()` (tiktoken-based, already in context.py) for budget math, not `len//4`.

**Configurable parameters:**

```python
RAG_TOKEN_BUDGET = 2000
EXPANSION_SCORE_THRESHOLD = 0.4
MAX_FULL_EXPANSIONS = 3
```

These are defaults. Per-classification overrides are possible via routing_rules.md (e.g., `document_query` gets budget 4000). The evolution engine can trial changes to these values via the existing experiment loop.

**Changes to `recall()` signature:**

```python
async def recall(self, query: str, limit: int = 5, token_budget: int = 2000) -> str:
```

`context.py` passes the remaining prompt budget to `recall()`.

**Internal refactor:** `_hybrid_search()` returns raw result objects with scores and accepts a `strategy: str = "rrf"` parameter for the merge algorithm (RRF fusion vs set-union). Formatting (the markdown string with sections) moves to a separate `_format_results()` method that handles tier selection and budget enforcement. This keeps search and presentation cleanly separated and enables A/B testing of retrieval strategies.

### 4. Parallel Tool Call Instruction

Add to `_TOOL_INSTRUCTION` in `context.py`:

```
"When you need to call multiple tools that don't depend on each other, call them all in a single response rather than one at a time."
```

The executor already handles parallel tool calls if the model returns multiple in one response. This instruction tells the model to actually do it.

**Note:** This is a best-effort behavioral hint. Some models may not parallelize correctly or may hallucinate dependencies. The executor remains the source of truth for dependency handling — if a tool call fails, the retry logic handles it regardless of whether other tools ran in parallel.

## File Changes

| File | Change |
|------|--------|
| `odigos/providers/base.py` | Add `cached_tokens: int = 0` to `LLMResponse` dataclass |
| `odigos/providers/llm.py` | Add `complete_json()` with 3-tier fallback, add `supports_explicit_cache` property, populate cached_tokens from response |
| `odigos/core/context.py` | Reorder `build_planned()` static-first, format Anthropic cache blocks, pass token budget to recall, add parallel tool instruction |
| `odigos/memory/manager.py` | Add `token_budget` to `recall()`, refactor `_hybrid_search()` to return raw results, add `_format_results()` with tier logic |
| `odigos/memory/extractor.py` | Switch to `complete_json()` |
| `odigos/core/classifier.py` | Switch to `complete_json()` |
| `odigos/core/evaluator.py` | Switch to `complete_json()` |
| `odigos/core/heartbeat/profiling.py` | Switch to `complete_json()` |

## What Doesn't Change

- Tool registry, executor, skill system
- Entity graph, wiki writer/reader
- Frontend — no UI changes
- MessageBus, channel adapters
- Heartbeat phases (except profiling calls switch to complete_json)
- Database schema — no new tables or columns

## What This Enables (Future)

- Per-classification RAG budgets in routing_rules.md
- Evolution engine trials on RAG parameters (budget, threshold, max expansions)
- Anthropic prompt caching cost savings when switching providers
- Hybrid retrieval union vs fusion A/B testing (parameter in recall)
