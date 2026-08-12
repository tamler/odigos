# Odigos: strategic review — 12 Aug 2026

Reviewed against the working tree at `test/odigos` (39.3k LOC in `odigos/`, 18.6k in
`dashboard/src`, 28.8k in `tests/` — 1,399 collected tests, 69 DB tables, 175 config
fields, 64 registered tools).

---

## 0. Bugs found that outrank all four ideas

These are live on Bob and Jessica right now. Fix before any refactor or new product.

### 0.1 `Notifier.notify()` rejects `priority=` — every heartbeat notification has always failed

`notifier.py:32-42` takes no `priority` kwarg and no `**kwargs`. All eight call sites in
`heartbeat/maintenance.py` pass it: lines **128, 142, 154, 193, 204, 235, 261, 284**.
Every one raises `TypeError`, swallowed by an enclosing `except Exception: logger.debug(...)`.

Never worked, on any agent: auto-update notices, storage-quota warnings, new-email alerts,
**nudges**, **follow-ups**.

Tests miss it because `tests/test_heartbeat_announce.py:79-90` mocks out `send_nudges`,
`check_followups` and `check_storage_quota` — the three functions containing the bug.

Fix: add `priority: str = "normal"` to `notifier.py:32`, then delete those mocks.

### 0.2 `ContextAssembler.build()` is unreachable — and the evolution engine is corrupting persona files

Production calls `build_planned()` (`context.py:708`). The 559-line `build()`
(`context.py:149-707`) is reached only by `tests/test_core.py` (1,050 LOC) and
`tests/test_notebook_context.py`. Anything only `build()` calls is dead in production
while looking alive:

- prompt-injection **canary token** (`prompt_builder.py:37-40`) — a security control
- instruction-hierarchy line
- `agent.concise_mode` — configurable, no effect
- `core/routing.py` routing rules
- **`checkpoint_manager.get_working_sections()`** — the only code that applies an active
  evolution trial's prompt override

That last one is the serious one. The evolution stack (~2,300 LOC, 12 tables, a dashboard
page) runs A/B trials whose treatment is **never applied**, scores the resulting noise, and
then `evolution.py:191` auto-promotes LLM-generated text into `data/agent/*.md` —
including `identity.md` and `guardrails.md` — on that noise.

`ProactiveConfig.enabled` also defaults `True` in `config.py:116` while
`config.yaml.example:151` says `false`, and the shipped `config.yaml` omits the block. So
instances run pipelines the docs say are off.

Fix now: set `evolution.enabled: false` by default until trials actually apply.

### 0.3 Peer replies to inbound connections always fail

`api/agent_ws.py:115` stores a **starlette** `WebSocket` in `_ws_connections`, but
`agent_client.py:150` calls `ws.send(json.dumps(...))`. Starlette's `send()` expects an ASGI
dict, so a `str` raises `TypeError: string indices must be integers`. Reproduced against a
real socket: 0 frames sent, message stuck `queued`, connection deleted at
`agent_client.py:160`. `flush_outbox` (`agent_client.py:427`) uses the same call, so it can
never drain either.

Net: **an agent can never reply to a peer that dialed in to it** — which is exactly the
spawned-child case, since `spawner.py:92` emits `netbird_ip: ""`.

Compounding: `WSConnector` snapshots the peer list at construction
(`ws_connector.py:34`) and dials once in `start()`. Peers found via gossip discovery are
**never dialed**, so their messages sit `queued` forever.

Tests pass because the socket is `AsyncMock()` (`test_agent_client.py:75,114,233`).

### 0.4 Heartbeat starves its own flagship features

Phases 4e, 5, 6, 8, 9, 9.5 and 10 are each gated on `if not did_work`
(`orchestrator.py:268, 272, 277, 285, 292, 305, 339`). Any earlier phase returning `True`
suppresses all of them for that tick. On an *active* agent the first things starved are plan
execution, proactive research, evolution, dreaming, experience extraction, memory evolution
and outcome evaluation — i.e. the README's headline "works proactively when idle" claim.

### 0.5 Smaller ones

- `api/state.py:216` reads `cron_manager.entries`, which doesn't exist
  (`cron.py:150-152`) → `/api/state` always reports `cron: {total: 0}`.
- `mark_stale_peers()` always returns 0 — `db.execute` returns `None` (`db.py:267`), see
  `agent_client.py:444-449`.
- `check_storage_quota` writes `kv.storage_usage_gb` *after* the notify
  (`maintenance.py:209`), so the write is skipped exactly when usage is over threshold. That
  key has no readers anyway.
- `context.py:989` reads `settings.agent.history_limit`; `AgentConfig` has no such field, so
  the configured value at `context.py:138` is silently ignored.
- `evaluate_tool_output`'s result is discarded at `executor.py:494`.

---

## 1. "Overly complex" — half right, wrong diagnosis

**The depth is fine.** A user message passes 8 layers before the main LLM call: `ws.py:122`
→ `_process_chat_queue` → `AgentService.handle_message` → `Agent.handle_message` →
`Agent._run` → `QueryClassifier.classify` → `Executor.execute` →
`ContextAssembler.build_planned` → `LLMClient.complete`. For auth + queueing + session
locking + classification + context assembly + a ReAct loop + provider routing with
fallback, that is not bloat. Exactly **one** layer is a pure forwarder —
`agent_service.py:36-49` — and `ws.py` reaches through it anyway (`ws.py:246, 268, 376`).

**What actually hurts is abandoned forks.** Every item below is a previous refactor that
added the new path and left the old one wired:

| Fork | Old path | New path | State |
|---|---|---|---|
| Prompt assembly | `context.build()` | `context.build_planned()` | old is dead but holds live features (§0.2) |
| Scheduling | `CronManager` + `cron_entries` | `Scheduler` + `scheduled_tasks` | `CronManager.add()` has **no callers**; nothing writes `cron_entries`; heartbeat Phase 3b always no-ops |
| Entity extraction | `post_response.extract_entities_background` | `memory/extractor.extract_knowledge` | **both run every turn**, near-identical prompts on the same `[:500]` slices |
| Correction detect | inline `<!--correction-->` at `reflector.py:63` | LLM call at `post_response.py:101` | both write `corrections` |
| History load | `_load_history_for_plan` (10 msgs, prose) | `_load_message_history` (20 msgs, turns) | both fire when `plan.needs.history` |

**Cost of the duplicate work: up to 5 non-executor LLM calls per turn** (classifier,
reflector→extractor, post_response entities, post_response corrections, auto_title). Two of
those are the same job twice.

### Verified-dead inventory

Zero production callers, confirmed by grep:

- `core/idle_research.py` (103) — only importer is its own test
- `core/vad.py` (97) — imported nowhere, zero tests
- `tools/template_tools.py` (218, 2 tools) — **never `registry.register()`ed**
- `core/trajectory.py` (147) — 1 caller (`strategist.py:195`), zero tests
- `core/fitness.py` (161) — `update_fitness_score` has no callers, so `current_score` is
  permanently `0.0` and `get_fitness_summary` feeds the strategist a constant
- `ToolSpec` + `register_from_specs` (`registry.py:22-30, 85-104`) — bootstrap uses 64
  plain `register()` calls
- `QueryAnalysis` (`classifier.py:84-92`) — never instantiated; survives as a type hint
- `evaluator.find_qualified_evaluator` (`evaluator.py:463-482`), `agent_client.send_response`
  (`:165`), `agent_client.on_message` (`:288`) — the last makes the handler dispatch loop at
  `:282-286` unreachable
- 4 `EntityGraph` methods: `traverse`, `get_related`, `update_entity`, `merge_entities`
- Tables with no Python reference: `channel_mappings`, `deploy_targets`, `message_artifacts`
- Write-only tables (INSERTed, never SELECTed by Python or the dashboard): `traces`,
  `tool_evaluations`, `strategist_runs`, `skill_verifications`, `consolidation_log`,
  `checkpoints`, `scraped_pages`, `message_deliveries`
- Dead config keys: `proactive.max_per_cycle`, `proactive.safe_tools` (FEATURES.md claims a
  "safe read-only mode" that is **not enforced**), `agent.allow_external_evaluation`,
  `models.*.vision`, `models.*.notes`, `agent.concise_mode`

### Cut list, by value ÷ risk

| # | Action | LOC (src/test) | Risk |
|---|---|---|---|
| 1 | Fix §0.1 `priority=`; un-mock the three heartbeat tests | +5 | ~0 — restores 5 features |
| 2 | Delete the verified-dead inventory above | ~600 / ~244 | ~0 |
| 3 | Delete `CronManager` (`cron.py:147-265`), Phase 3b, `cron_entries`, `api/state.py:214-219`. **Keep `CronExpression`** — `scheduler.py:9` imports it | ~190 / ~200 | low; check for legacy rows first |
| 4 | Delete `post_response.extract_entities_background` + `agent.py:306-311,320` | ~60 | low — **also cuts one LLM call per turn** |
| 5 | Delete `core/fitness.py`, `api/evolution.py:139-190`, `fitness_functions`/`trial_patterns` | ~200 / ~102 | low |
| 6 | **Port-then-delete `build()`.** First move the canary, instruction-hierarchy line, `concise_mode`, and `get_working_sections()` (replacing `fallback_registry.load_all()` at `context.py:877`) into `build_planned`. *Then* delete `build()`, `personality/prompt_builder.py`, `core/routing.py`, `registry.validate_routing_rules`, `bootstrap.py:1190-1198`, `data/agent/routing_rules.md` | ~720 / ~1,110 | **medium — highest value.** Deleting first silently drops a security control |
| 7 | Fold `AgentService` into `Agent`; de-dupe the double history load; fix the phantom `history_limit` | ~90 | medium — 4 call sites incl. telegram |
| 8 | Default `evolution.enabled: false` until #6 lands | 0 now, ~2,300 later | leaving it on is the risk |

Mechanically safe (#2–5): **~1,050 src / ~550 test LOC.** With #6: ~1,770 / ~1,660. With
#8: **~4,200 src LOC (≈11% of `odigos/`)** and ~20 of 69 tables.

### Do NOT touch — this is scar tissue, not over-engineering

1. **The executor's tool contract.** `executor.py:722-908` + `core/failure.py`: parameter
   coercion and jsonschema validation (`_coerce_and_validate`, `executor.py:180`), the
   4-category failure taxonomy with per-category retry (`failure.py:11-51`), `ToolContract`
   timeouts, the `find_tools` loop guard (`executor.py:552-577`), the stuck detector
   (`:539-550`). Each exists because a specific model behaviour broke production —
   anti-pattern registry entries #2, #3, #4.
2. **`find_tools` + JIT schema injection.** `registry.py:44-49` (`tool_definitions()`
   deliberately returns *only* `find_tools`), `tools/find_tools.py`, same-turn expansion at
   `executor.py:517-537`. With 64 registered tools against a documented 15–20 degradation
   threshold, this is what makes the surface usable. `_PRUNE_AFTER_TURNS = 4` /
   `_PRUNED_MAX_CHARS = 1500` (`executor.py:30-31`) carry a 9-line comment explaining why
   the obvious smaller values were wrong. Registry entry #11 is a real bug caught here (12
   of 66 tools undiscoverable).
3. **Hybrid memory retrieval.** `memory/recall.py:62-107` (parallel vector + FTS5, RRF
   merge), `memory/store.py`, `memory/graph.py:145-223` (2-hop traversal with relationship
   paths), one entry point at `context._load_rag_for_plan`. The actual differentiator, the
   most-tested area (12 test files), one call path. Trim the 4 unused `EntityGraph` methods,
   leave the rest.

### The counter-evidence, taken seriously

`docs/superpowers/anti-patterns.md` logs 8 dated incidents, **all** of the shape "a change
that looked like cleanup broke real LLM behaviour."

- Entry #1: `_load_identity()` reduced to loading only `identity.md`, silently dropping 8
  persona sections **including guardrails**. 🔴 high, 3 agents, detection latency `>30d`.
- Entry #2: pruning tightened to 200 chars / 2 turns — "broke every multi-turn tool chain,"
  🔴 high, `>30d`.
- §3.2 explicitly forbids collapsing tool families ("surface completeness over surface
  minimalism") — collapsing kanban is what made `kanban_create_board` not exist (entry #6).
- §3.4 forbids re-tightening context budgets globally.

Those two are the first things a naive complexity pass reaches for. The spec also names the
missing primitive: *"There is no contract test between human-readable and LLM-readable
output."*

**Both instincts are right about different things.** The harmful complexity is not depth —
it is forked-and-abandoned paths. Operating rule: **forbid "simplify by collapsing"; mandate
"simplify by finishing the last migration."** Start with `ContextAssembler.build()`.

---

## 2. Extracting the comms layer — not yet, and probably not this layer

### What's actually there

Envelope (`agent_client.py:35-69`): 8 JSON fields — `id`, `from_agent`, `to_agent`, `type`,
`payload`, `correlation_id`, `priority`, `timestamp`. **No version field anywhere.**

Transport: WebSocket only, plaintext `ws://{netbird_ip}:{ws_port}/api/agent`
(`ws_connector.py:85`) — no `wss://`, security delegated to an assumed WireGuard underlay.
The one HTTP send endpoint, `POST /api/mesh/peers/{peer}/message`, is a **501 stub with dead
`inspect.currentframe()` code** (`mesh.py:70-78`).

Auth: symmetric shared bearer secret compared against *the receiver's own*
`settings.api_key` (`agent_ws.py:62`), plus optional `card-sk-*` scoped keys
(`cards.py:73`). **Identity is unbound from the credential** — `peer_name = msg.from_agent`
(`agent_ws.py:112`) is self-asserted and never checked, so anyone with the shared secret can
claim any name. The HTTP announce uses `require_api_key`, an alias for `require_auth`
(`deps.py:69`), so a **dashboard session cookie** can register peers.

Live message types: `registry_announce`, `status_ping`, `status_pong`, free-form `"message"`.
The five constants `MSG_TASK_REQUEST/RESPONSE/STREAM`, `MSG_EVAL_REQUEST/RESPONSE`
(`agent_client.py:26-32`) are referenced **nowhere** outside their declaration. The
`message_type` enum advertised to the LLM (`tools/peer.py:34`: `help_request`,
`knowledge_share`, `task_delegation`, `status`) is never validated or branched on — they are
decorative strings.

Request/response **is not implemented**: `correlation_id` is propagated and
`send_response()` exists (`:165`), but there is no pending-reply map anywhere and
`send_response` has zero callers. The only reply path is inbound row → heartbeat polls
`get_unprocessed_inbound` → full agent turn → `send()` (`heartbeat/peers.py:42-97`). Latency
is one heartbeat interval, and the reply is whatever the LLM decides to emit.

### The seam is real, the substance isn't

Coupling is genuinely shallow. `agent_client.py` **never imports the agent** — it needs only
"something that can receive a message." Persistence is 11 queries over 2 tables behind a
3-method surface, and only **4 lines** use SQLite dialect (`datetime('now', ?)` at
`agent_client.py:153, 406, 429, 446`). A standalone `agentmesh/` package would be ~990 LOC,
~700 derived and ~290 newly invented across five interfaces that don't exist yet: `Transport`
ABC, `Store` ABC, `PeerAddress`/`AgentIdentity`, a `ContentScanner` hook (replacing the
module-global at `agent_client.py:24`), and an inbox-cursor abstraction.

Breaking changes to odigos: the private `_ws_connections` reach-in from 4 sites
(`agent_ws.py:115,137`, `ws_connector.py:110,122`); `netbird_ip` → `host`, which touches
**28 references across 8 files including `schema.sql`** and the dashboard JSON — needs a
migration.

### Verdict: it's three glue endpoints and a table

What runs in production is announce + ping/pong + free-form messages dropped into a SQLite
inbox that an LLM eventually reads. Plus §0.3: replies to inbound peers always fail, and
discovered peers are never dialed. Publishing this would freeze those defects into a public
API **with no version field to fix them behind**.

And Google's **A2A** is already a superset: `registry_announce` ≈ Agent Card (though A2A
fetches from `/.well-known/agent.json` rather than gossiping), `capabilities[]`/`role` ≈
skills, `task_request`/`task_stream` ≈ tasks + SSE — the exact five constants declared here
and never implemented. A2A has JSON-RPC framing, task lifecycle states, and a version.
Nothing in `odigos/`, `docs/` or `README.md` references A2A, MCP, ACP or ActivityPub, so this
was designed independently — which is why it lands as a subset.

### But there is a real idea in here — about 30 lines of it

`agent_client.py:216-244` scans **every inbound payload for prompt injection before storage
or routing**: `risk_level == "high"` is rejected to a terminal `'rejected'` state, medium
risk is allowed but annotated into the payload as `_injection_warning`, then re-scanned and
sanitized in the heartbeat (`heartbeat/peers.py:68-73`). A2A and MCP specify **nothing**
equivalent. Neighbouring: `evolution_score` + `allow_external_evaluation` as a *reputation*
field in the registry (peer-evaluated agent quality — no standard models this), and contact
cards as capability-scoped invite keys.

That's the publishable asset: **"untrusted inbound for agent protocols"** — a scanner +
quarantine state machine + reputation field, shipped as an **A2A/MCP middleware**, not as a
ninth competing protocol. `content_filter.py` is already stdlib-only, zero odigos imports.

### If you pursue it, do exactly one thing first

**Introduce the `Transport` ABC in place, inside odigos**, with two implementations
(`websockets` client, starlette server), plus one integration test that stands up two real
agents and asserts a round-trip reply.

That single move fixes §0.3, removes the largest coupling (the `_ws_connections` reach-in
from all 4 sites), is precisely the seam a library would need so no work is wasted, and the
two-real-agent test is the only thing that will surface the remaining gaps — never-dialed
discovered peers, absent request/response, spoofable `from_agent` — *before* they'd get
baked into a published interface.

---

## 3. Zoho version — good technical read, bad market read as framed

### Zoho already shipped your product and priced it at zero

- **Zia LLM** (Jul 2025): three in-house models (1.3B / 2.6B / 7B) + ASR, in Zoho's own DCs
- **Zia Agent Studio**: low-code agent builder, **700+ prebuilt actions** across Zoho apps
- **Agent Marketplace**: **25+ prebuilt agents**; ISVs and partners can publish
- **Official MCP servers** for **15+ apps**, four dedicated to CRM (Data Insights, Data
  Operations, Module Customization, Workflow), plus `mcp.zoho.com` for Mail, Calendar, Desk,
  Cliq, Projects, WorkDrive — OAuth 2.0, no self-hosting
- GA at Zoholics USA 2026, with "Digital Employees" (human-equivalent access controls + audit)
- **Pricing: Zia Agents are free.** You pay only for models — 30M free tokens/month, then
  ~$0.30/M; Pro tier 20M free then ~$0.90/M. **BYOK supported.** Zia is bundled into CRM
  Enterprise at $40/user/mo.

You would be selling against free, from inside their store, to the most price-sensitive base
in B2B SaaS — Zoho One is $37/employee/mo for ~45 apps.

### The marketplace is not the channel you'd hope

- 2,000+ extensions, ~30k installs/month, 500+ ISV/SI partners
- Independent analysis: ~200 developers, ~1,100 apps, 32% paid — and **97% of all installs
  belong to Zoho's own apps**. Discovery is weak.
- Best-documented success: **Ulgebra**, ~9 people, 27 paid apps, author judged "$10k+/month
  is absolutely possible." That's the ceiling case, not the median.
- No listing or review fees; 4-stage review (~2 weeks); payouts monthly, $100 minimum
- **Zoho's revenue-share percentage is undocumented** across pricing, payments, sales-reports
  and ToS pages, and no developer has disclosed it. Ask Zoho directly before committing.
- Base rate from Shopify (best-documented proxy): median app **under $1,000/mo**, majority
  earn nothing, top 10% ~$100k ARR. Assume Zoho is *worse* — smaller store, poorer discovery,
  cheaper buyers.

### Customer base and API reality

1M+ paying orgs, 150M+ users (Feb 2026), 32% customer growth, ~$1.5–2B ARR. CRM > Books >
Desk > People > Campaigns > Creator > Projects by usage; CRM alone has 250k+ businesses,
>50% SMB.

CRM v8 is mature. Credits/24h: Free 5k; Standard 50k + 250×users (cap 100k); Professional
50k + 500×users (cap 3M); Enterprise 50k + 1,000×users (cap 5M). **Concurrency is only
5–25 calls.** Send-mail costs 20 credits, bulk ops 50–500. A polling-heavy agent is fine on
a 10-user Professional org (55k/day) and not fine on Standard. **Books is the pain point** —
a 2,500 call/day/org limit *shared with Zoho's own mobile apps*. Multi-DC OAuth
(`.com/.eu/.in/.au`) plus per-product API dialects is the real integration cost.

### The gap that is actually yours

Zia's MCP servers are **chat-session-bound, have no event triggers, and are single-app per
server**. No persistent background loops, no cross-app orchestration, no audit trail across
apps. That is precisely what a 39k-LOC harness with a heartbeat already does. It is also a
gap Zoho will plausibly close — Forrester notes AppOS plus AI-assisted agent codegen is
their stated direction, explicitly to let *partners* build agents without ISVs.

### Competition

Nobody ships a Zoho-native agent *harness*. The field is Zia itself, plus horizontal AI
support tools with Zoho connectors — eesel AI $0.40/resolution, Tidio Lyro
$0.50/conversation, Ada ~$1.50/resolution (300k minimum), Forethought/Aisera/Kore.ai
quote-only — plus consultants wiring n8n agent meshes onto Zoho.

### Reframe

Don't sell a Zoho agent product **on the marketplace**. Sell **Odigos-for-Zoho to Zoho
consulting partners** as their delivery tooling — triggers, background loops, cross-app
orchestration, audit — with a free marketplace connector purely as a lead magnet. Hundreds
of partners exist, they resell and bill implementation, and Zoho is expanding partner
monetization (Vertical Studio, AppOS).

**Validation gate: get 3 partners to pre-pay before writing code.** I could not find data on
whether Zoho partners actually buy third-party tooling — that is the load-bearing unknown,
and ten phone calls closes it. If they won't pre-pay, the bet fails at the demand layer, not
the tech layer, and no amount of building fixes it.

---

## 4. The missing option: extract the tool-routing layer instead

You're pointing the extraction instinct at the wrong subsystem. The comms layer is a subset
of an existing standard. But `find_tools` + JIT schema injection is a solution to a problem
**every** agent builder hits and almost nobody has solved well:

`registry.py:44-49` — `tool_definitions()` deliberately returns *only* `find_tools`, so a
64-tool agent presents one tool. `tools/find_tools.py` does semantic retrieval over the
catalog. `executor.py:517-537` injects the matched schemas **in the same turn**, and
`:552-577` guards against the model looping on discovery. `_PRUNE_AFTER_TURNS = 4` /
`_PRUNED_MAX_CHARS = 1500` (`executor.py:30-31`) are tuned values with a comment explaining
why the obvious ones failed.

Why this is the better extraction:

- **Demand is proven.** The 15–20 tool degradation wall is universal, and the industry is
  converging on this exact pattern — deferred tool loading is now standard in agent
  harnesses. An MCP-server-count problem is something every MCP user has *today*.
- **It's genuinely differentiated.** Yours has the loop guard, the stuck detector, the
  same-turn injection, and the tuning constants — the parts everyone gets wrong on the first
  try. Registry entry #11 (12 of 66 tools undiscoverable) is evidence you've already debugged
  the failure mode others haven't hit yet.
- **It's a natural MCP-shaped product**: a router/proxy that sits in front of N MCP servers
  and presents one `find_tools` tool. No new protocol, no version-field problem, drops into
  anyone's existing stack.
- **Cleaner seam than the mesh.** It depends on the registry and the catalog, not on SQLite
  schema or the heartbeat.

**Second candidate, smaller but cheap:** `docs/superpowers/anti-patterns.md` — 8 dated
incidents with severity, blast radius and detection latency, each of the form "a
simplification that backfired against real LLM behaviour." That is unusually good writing
about agent engineering and near-zero marginal effort to publish. It's the credibility asset
that makes anyone believe the tool-router is worth installing.

**Third, and this one is a gap not a product:** your own brittleness spec names the missing
primitive — *"There is no contract test between human-readable and LLM-readable output."*
Every §0 bug and every registry entry is a variant of it. Build that harness and the class of
regression stops recurring; without it, item 1's cut list will grow item 1 back.

---

## Recommended order

1. **§0.1, §0.2, §0.3, §0.4** — the live bugs. Default `evolution.enabled: false` today.
2. **Cut list #2–5** — mechanically safe, ~1,050 src LOC, zero-callers verified.
3. **Cut list #6** — port-then-delete `build()`. The highest-value item and the only one
   needing care.
4. **The `Transport` ABC + two-real-agent integration test** — pays for itself whether or not
   a library ever ships.
5. **The contract-test harness** (§4, third) — stops the regression class.
6. *Then* pick a commercial bet, and pick it on validation, not on code: 10 calls to Zoho
   partners for #3, or ship the tool-router (§4) as the extraction instead of the mesh.

The pre-launch blockers in `ROADMAP.md` are ahead of all four ideas. You have a waitlist and
testers on a fleet where nudges and follow-ups have never fired.
