# JIT Tool Schema Injection Design

**Date:** 2026-04-04
**Status:** Approved
**Goal:** Auto-inject relevant tool schemas based on query classification so the agent can use tools immediately without calling `find_tools` first.

## Context

Currently the agent only sees `find_tools` in its tool list. To use any tool, it must first call `find_tools`, read the results, then call the actual tool — a round trip that costs 1 extra LLM turn (~$0.01-0.05 per query). JIT injection eliminates this by pre-loading the most likely tools based on the query classification.

## Design

**`tool_definitions(inject_tools=...)` in registry.py:** Accepts an optional list of tool names to inject alongside `find_tools`. Returns OpenAI-compatible tool definitions for find_tools + up to 5 injected tools.

**Executor resolves tool names:** Before calling `tool_definitions()`, the executor uses the existing `_get_likely_tools()` function (from XSkill) to look up which tools are historically used for this classification type. Falls back to `_FALLBACK_TOOLS` static map.

**`find_tools` always included:** Acts as a safety valve if the JIT selection misses something. 94 tokens — negligible cost.

## Files Changed

| File | Change |
|------|--------|
| `odigos/tools/registry.py` | `tool_definitions()` accepts `inject_tools` param |
| `odigos/core/executor.py` | Resolve likely tools, pass to `tool_definitions(inject_tools=...)` |

## What Doesn't Change

- `find_tools` tool — still works, still included
- Dynamic injection after `find_tools` call (executor lines 416-436) — still works as fallback
- Context assembly, XSkill, experience retrieval — untouched
