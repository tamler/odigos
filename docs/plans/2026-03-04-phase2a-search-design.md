# Phase 2a Design: Web Search

**Date:** 2026-03-04
**Status:** Approved
**Milestone:** "It searches for me" -- ask the agent something it doesn't know, and it searches the web and synthesizes an answer.

---

## Scope

SearXNG web search only. A tool registry and two-pass executor establish the pattern for all future tools. The planner gets LLM-based intent classification so the agent can proactively decide to search without being explicitly asked.

Deferred to later phases: page scraping, document processing, code sandbox, scheduling.

### Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Scope | Web search only | Smallest useful increment. SearXNG instance is ready. |
| Intent detection | LLM classification (cheap model) | Agent should proactively search. Swap to local model later. |
| Execution pattern | Tool registry + two-pass | First pass: run tool, get results. Second pass: LLM synthesizes with results in context. Extensible. |
| SearXNG auth | Everything in .env | Keeps secrets together, consistent with existing pattern. |
| Search results format | JSON API, top 5 results | SearXNG has a JSON endpoint. 5 results balances context size vs. coverage. |

---

## New Modules

```
odigos/
  tools/
    __init__.py
    registry.py         # Tool registry: register, lookup, list tools
    base.py             # BaseTool abstract class
    search.py           # SearXNG web search tool
  providers/
    searxng.py          # SearXNG API client (HTTP + basic auth)
```

---

## Tool Registry (tools/registry.py + tools/base.py)

`BaseTool` defines the interface every tool implements:
- `name: str` -- unique identifier (e.g. "web_search")
- `description: str` -- what it does (used in prompt context)
- `async execute(params: dict) -> ToolResult` -- run the tool, return results

`ToolRegistry` is a simple dict-based registry:
- `register(tool: BaseTool)` -- add a tool
- `get(name: str) -> BaseTool` -- look up by name
- `list() -> list[BaseTool]` -- all registered tools (for future prompt injection of available tools)

`ToolResult` dataclass: `success: bool`, `data: str`, `error: str | None`

---

## SearXNG Provider (providers/searxng.py)

HTTP client for the SearXNG JSON API:
- Uses httpx.AsyncClient with basic auth (same pattern as OpenRouter provider)
- `search(query: str, num_results: int = 5) -> list[SearchResult]`
- Hits `https://search.uxrls.com/search?q=...&format=json`
- `SearchResult` dataclass: `title`, `url`, `snippet`
- Graceful error handling: returns empty list on failure, logs the error

---

## Search Tool (tools/search.py)

Wraps the SearXNG provider as a `BaseTool`:
- `name = "web_search"`
- `execute({"query": "..."})` calls SearXNG provider, formats results into a readable string for context injection

---

## Planner Upgrade (core/planner.py)

Currently returns hardcoded `Plan(action="respond")`. Upgraded to:

1. Call a cheap LLM model with a classification prompt: "Given this user message, should the assistant search the web? Respond with YES or NO and a brief reason."
2. If YES, return `Plan(action="search", tool_params={"query": "<search query>"})`
3. If NO, return `Plan(action="respond")`

The classification prompt also asks the LLM to extract/refine the search query from the user's message (e.g. "what's the weather in NYC" -> query: "weather NYC today").

Uses the same OpenRouter provider but with a cheaper/faster model (configurable, defaults to the free model).

---

## Executor Upgrade (core/executor.py)

Currently just calls the LLM. Upgraded to two-pass pattern:

1. Check `plan.action`
2. If `"search"`: look up tool from registry, call `tool.execute(plan.tool_params)`, get `ToolResult`
3. Build context with tool results injected (via context assembler)
4. Call LLM with results in context -- the LLM synthesizes the answer
5. If `"respond"`: current behavior (just call LLM)

The context assembler gets a new optional `tool_context` parameter that injects tool results between memory context and conversation history.

---

## Config Changes

**.env** (new vars):
```
SEARXNG_URL=https://search.uxrls.com
SEARXNG_USERNAME=nimda
SEARXNG_PASSWORD=<password>
```

**config.py**: New `SearxngConfig` with `url`, `username`, `password` fields, all from env vars.

**config.yaml**: No changes needed (all SearXNG config from .env).

---

## Integration Points

- **main.py**: Initializes SearXNG provider, search tool, tool registry. Passes registry to executor, provider to planner.
- **planner.py**: Gets its own provider reference for cheap LLM calls.
- **executor.py**: Gets tool registry, two-pass logic.
- **context.py**: New `tool_context` parameter in `build()`.
- **prompt_builder.py**: New optional `tool_results` section between memory and entity extraction.

What does NOT change: reflector, memory manager, personality loader, database schema.
