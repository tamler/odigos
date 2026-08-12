# Container 04 — tool-router

**Outcome:** `find_tools` + just-in-time schema injection as a standalone MCP router that
anyone can install, with **zero Odigos imports**.

Its own repo from day one. Starts after Container 01 (extracting from a tree with abandoned
forks means you can't tell which version of a behaviour you're extracting).

---

## Why this and not the mesh

The agent-to-agent mesh looked like the extractable asset. It isn't: five of its seven message
types are unreferenced constants, `send_response` and `on_message` have zero callers, request/
response has no pending-reply map, the one HTTP send endpoint is a 501 stub, and there's no
version field. Google's A2A is already a superset of the parts that were declared and never
built.

The tool router is the opposite: a solved-in-place answer to a problem **every** agent builder
has right now. 64 registered tools against a documented 15–20 degradation threshold, and the
industry is converging on deferred tool loading. Anyone running more than a handful of MCP
servers has this problem today.

## What's differentiated — port these deliberately, they're the value

- `registry.py:44-49` — `tool_definitions()` returns **only** `find_tools`, so N tools present
  as one
- `tools/find_tools.py` — semantic retrieval over the tool catalog
- `executor.py:517-537` — **same-turn** schema injection, so discovery doesn't cost a round trip
- `executor.py:552-577` — loop guard against the model re-discovering forever
- `executor.py:539-550` — stuck detector
- `executor.py:30-31` — `_PRUNE_AFTER_TURNS = 4`, `_PRUNED_MAX_CHARS = 1500`, with the 9-line
  comment explaining why the obvious smaller values were wrong. **Port the comment.** It is
  the most valuable line in the file.
- `tools/catalog.py` — catalog construction
- The lesson behind anti-pattern registry entry #11: 12 of 66 tools were undiscoverable in
  production. Whatever fixed that must survive the port, and needs a coverage test asserting
  every registered tool is reachable via discovery.

## Shape

An MCP server that fronts N upstream MCP servers and exposes one `find_tools` tool, expanding
matched schemas in-place. Drops into an existing stack with no protocol invention, no version-
field problem, no adoption ceremony.

## Non-goals

❌ Any Odigos import — this is the entire product thesis. Enforce it with a test.
❌ Inventing a protocol. It's an MCP server; MCP already exists.
❌ Porting the mesh, memory, heartbeat, or anything product-shaped.
❌ Reimplementing tool execution. Route and inject; upstream servers execute.

## Launch

Publish `docs/superpowers/anti-patterns.md` as the launch essay — 8 dated incidents with
severity, blast radius and detection latency, each a case of a simplification backfiring
against real LLM behaviour. It's unusually good writing about agent engineering and it's the
credibility asset that makes someone install the router.

## Definition of done

- [ ] Fronts ≥3 real MCP servers; a client sees one tool and reaches all of them
- [ ] Loop guard, stuck detector and pruning constants ported **with their comments**
- [ ] Discovery-coverage test: every upstream tool is findable (entry #11's lesson)
- [ ] A test asserting zero Odigos imports
- [ ] README with a benchmark: tool-call accuracy at 5 / 20 / 60 tools, with and without the router
