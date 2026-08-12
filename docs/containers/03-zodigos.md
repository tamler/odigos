# Container 03 — ZOdigos: the race car

**Outcome:** a Zoho-native agent in **TypeScript/Node**, informed by everything Odigos learned,
carrying none of its code.

Starts only after Project A delivers `docs/DESIGN-DECISIONS.md`. That is your bill of materials:
the failure taxonomy and what caused each category, why `find_tools` presents one tool instead
of N, the tuned pruning constants *with their reasoning*, context-assembly order and why it
matters for cache hits, hybrid recall, budget shape, and every `anti-patterns.md` lesson
generalised past its incident. Read it before writing a line. You are not starting blind — you
are starting with someone else's scar tissue written down.

---

## What this is, and what it deliberately isn't

Odigos is a kitchen sink: 64 registered tools covering kanban, notebooks, feeds, music, images,
quizzes, calendars, email, QR codes. That breadth is correct for a personal agent and **wrong**
for someone whose job is Zoho CRM / Books / Desk. A Zoho operator wants Zoho primitives —
records, modules, workflows, blueprints, pipelines — presented as a small, sharp surface.

So this project **removes more than it adds**. That is the point. Two sibling products, one
shared body of hard-won knowledge and zero shared code: kitchen sink and race car.

### Non-goals — these are the whole discipline of this container

- ❌ **Do not port PRODUCT-layer features.** No kanban, notebooks, feed, music_gen, image_gen,
  quiz, horoscope, generic personal memory schema, or the personal-agent dashboard. If you find
  yourself wanting one, write it to `ESCALATIONS.md` and justify it against a Zoho user's job.
- ❌ Do not reimplement `evolution`, `strategist`, `checkpoint`, `consolidation`, `fitness`,
  `trajectory`, `idle_research`. Project A is deleting or defaulting-off most of these for
  cause — read why before deciding you want them.
- ❌ **No native dependencies.** This is the reason the project is TypeScript: `npx zodigos`
  must work with no build step. Hosted embeddings over the API — no `transformers.js`, no ONNX,
  no natively-built `sqlite-vec`. Use Node 22+'s built-in `node:sqlite`, or hosted vector
  search. One native module and the entire distribution rationale is gone.
- ❌ Do not add `user_id` to data tables. Same invariant: one install, one person, one DB.
- ❌ Do not build billing or a marketplace listing until the gate below opens.

---

## The commercial gate — read before writing code

Zoho has already shipped the generic version of this and **priced it at zero**: Zia Agent Studio
(700+ prebuilt actions), an Agent Marketplace (25+ agents), official MCP servers for 15+ apps
including four for CRM, 30M free tokens/month then ~$0.30/M, and BYOK. 97% of Zoho Marketplace
installs go to Zoho's own listings. Zoho One is $37/employee/mo, which anchors what SMBs will pay.

**The defensible gap is narrow and real:** Zia's MCP servers are chat-session-bound, have **no
event triggers**, and are **single-app per server**. No persistent background loops, no
cross-app orchestration, no cross-app audit trail. Odigos's heartbeat, scheduler, plans and
subagents are exactly that. Build to *that* gap; everything else is a race against a free
first-party product.

**Gate: 3 Zoho consulting partners pre-pay before this container gets real investment.** The
load-bearing unknown is whether partners buy third-party delivery tooling — no data exists
either way, and ten phone calls closes it. Until then, keep this container to a spike that
proves the technical thesis, not a product.

---

## Technical ground truth (researched 2026-08-12)

- **Use Zoho's own MCP servers** rather than hand-rolling REST clients. Four dedicated CRM servers (Data Insights, Data Operations, Module Customization,
  Workflow) plus `mcp.zoho.com` for Mail, Calendar, Desk, Cliq, Projects, WorkDrive.
- **OAuth is multi-datacentre**: `.com` / `.eu` / `.in` / `.au`. Per-product API dialects are
  the real integration cost. Get this right in the first week; it is painful to retrofit.
- **Credits are the design constraint, not rate limits.** CRM/24h: Free 5k; Standard
  50k + 250×users (cap 100k); Professional 50k + 500×users (cap 3M); Enterprise 50k + 1,000×users
  (cap 5M). **Concurrency is only 5–25 calls.** Send-mail costs 20 credits, bulk ops 50–500.
  **Books is the trap: 2,500 calls/day/org, shared with Zoho's own mobile apps.**
  → A polling-heavy agent is fine on a 10-user Professional org and fatal on Standard. Make
  poll intervals credit-aware and budget-tracked, reusing the budget shape from `DESIGN-DECISIONS.md`.
- Zoho: 1M+ paying orgs, 150M+ users, >50% SMB. Product order by usage: CRM > Books > Desk >
  People > Campaigns > Creator > Projects. Target CRM and Desk first.

---

## Work

1. **Spike the thesis.** One event trigger → background loop → cross-app action → audit entry,
   end to end on a real Zoho sandbox. This is the thing Zia cannot do. If it doesn't work, stop.
2. **Build the harness in TypeScript.** Agent loop, executor, tool contract, failure taxonomy,
   `find_tools` + JIT schema injection, budget tracking — implemented **from
   `DESIGN-DECISIONS.md`**. Fresh code, proven design. Official MCP TypeScript SDK v2.x
   (ESM-only, Node 20+).
3. **Zoho product layer.** OAuth multi-DC, MCP registration, credit-aware scheduling, a
   Zoho-shaped tool surface (small — resist growth), and an entity graph over
   accounts/deals/contacts/tickets rather than personal memory.
4. **Zoho-shaped UI.** Not the personal-agent dashboard.

## Definition of done for the spike

- [ ] Trigger → background loop → cross-app write → audit trail, working against a real sandbox
- [ ] Credit accounting that cannot exhaust a Professional org's daily allowance
- [ ] `npx zodigos` runs on a clean machine with **zero native dependencies**
- [ ] Every design decision traceable to `DESIGN-DECISIONS.md`, or a written reason for departing
- [ ] A one-page honest answer to "why not just use Zia?" that a Zoho partner finds convincing
