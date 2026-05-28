# Odigos Roadmap

Durable tracking of what's shipped, what's in design, and what's coming.
Keep this file short — one line per item, link out to specs/PRs for detail.

Legend: ✅ shipped · 🔧 in design · ⏭️ planned · 💭 open question

---

## Current fleet (2026-05-27)

Single OVH VPS at `51.81.82.221` (Tailscale-only SSH, public 80/443 for Caddy).

| Service | Path | Domain | Backend |
|---------|------|--------|---------|
| Bob (Jacob's personal agent) | `/opt/odigos` | `jacob.odigos.one` | Groq scout (fast) + OpenRouter mimo-pro (smart) |
| Jessica (tester) | `/opt/odigos-jessica` | `jessica.odigos.one` | Same as Bob |
| Site (marketing + auth UI) | `/opt/odigos-site` | `odigos.one` | Node/Express/SSR React |
| Platform API | `/opt/odigos-platform` | `odigos.one/api/v1/*` | FastAPI + Postgres ([repo](https://github.com/tamler/odigos-platform), private) |
| Postgres | docker `odigos-postgres` | (internal, 127.0.0.1:5432) | postgres:16-alpine |

Retired during 2026-05-27 migration: Rachel, Honey, HomeRun (odigos.one bare-metal); old Bob (data wiped); Jessica Docker on uxrls.com. Retired 2026-05-28: Sales (public chat widget) — replaced with static FAQ.

---

## Recently shipped

### Infrastructure migration (2026-05-27)
- ✅ Migrated odigos.one off bare-metal OVH (Ubuntu 24.04, 5 systemd agents) to a new OVH VPS (Ubuntu 26.04, 4 vCPU / 7.6 GB / 72 GB)
- ✅ Tailscale-only SSH (public port 22 firewalled, key auth only)
- ✅ Caddy + Let's Encrypt for `odigos.one`, `jacob.odigos.one`, `jessica.odigos.one`
- ✅ Postgres dump (~90 MB) restored to new VPS; site + platform reconnected
- ✅ All hand-curated Sales customizations (`data/agent/identity.md`, `capabilities.md`, `guardrails.md`, sources, skills) restored from salvage
- ✅ `~/odigos-vps-archive/` holds salvage tarballs (manifest, code, postgres dump, systemd units) as offsite backup

### Platform repo extracted (2026-05-27)
- ✅ `/opt/odigos-platform` is now its own private GitHub repo: `tamler/odigos-platform`
- ✅ Deploy pattern: edit locally → push → rsync to VPS (`platform.env` stays server-only via .gitignore)
- ⏭️ Future: replace rsync with proper `git pull` on VPS via deploy key

### Auth + SSO bridge (2026-05-27)
- ✅ Case-insensitive auth: email (platform) and username (agent) normalize to lowercase before INSERT/SELECT — fixed silent login failures on mixed-case
- ✅ `LowerEmail` Annotated type on all platform `EmailStr` fields (auth.py, contacts.py)
- ✅ **Level 1 SSO bridge** — platform issues HS256 JWT (5-min TTL) via `POST /api/v1/auth/agent-token`; agent verifies + sessions via `GET /api/auth/sso?token=`. Shared `PLATFORM_AGENT_JWT_SECRET`. 5/5 attack-vector tests pass (wrong audience, expired, unknown email, bad signature, no auth).
- ✅ **Auto-provision** — SSO with unknown email creates the local agent user (config flag `sso_auto_provision: true` default). Username derived from email local-part.
- ✅ **"Open my agent" button wired** (2026-05-28) — `Dashboard.tsx` instance card calls `/api/v1/auth/agent-token` then redirects through `/api/auth/sso?token=`. Shipped in SSR bundle. Awaits `instances` table seeding to be user-visible.
- ⏭️ Collect `chosen_subdomain` during platform signup
- ⏭️ Provisioning automation: `INSERT INTO instances` on signup so the button is visible without a manual seed

### LLM routing improvements (2026-05-27)
- ✅ `ModelConfig.max_output_tokens` per-model override — fast-tier providers like Groq scout (8k cap) get clamped while smart-tier mimo-pro (1M ctx) uses the full budget
- ✅ Global `llm.max_tokens` default raised 2048 → 32768
- ✅ Bob/Jessica routing: `fast=scout (Groq) · smart=mimo-pro (OpenRouter, xiaomi/mimo-v2.5-pro, 1M ctx, ~3× cheaper than kimi-k2)`
- ✅ Sales on Groq llama-3.3-70b-versatile (after evaluating NVIDIA minimax + stepfun-flash — both too slow + weak instruction following for public chat UX)

### Dashboard fixes (2026-05-27)
- ✅ `BudgetStatus` field shape aligned with backend (Activity page no longer crashes on `.toFixed()` of undefined)
- ✅ `'new'` conversation sentinel skipped in message-fetch paths (no more `/api/conversations/new/messages 404` loop in console)

### Earlier (carried forward, still accurate)
- ✅ Multi-provider + BYOK + intelligence routing (provider registry, model registry, `${ENV_VAR}` interpolation, BYOK dashboard panel)
- ✅ Account creation + operator pre-provisioning (`/api/auth/setup`, `scripts/seed-account.sh`, current-password check on rotation)
- ✅ Prompt caching wiring (stable prefix order, per-turn cache hit logging)
- ✅ `deploy.sh --fresh` flag for multi-agent reset + key-rotation

---

## In flight / next up

- ⏭️ **Old VPS wipes** — `82.25.91.86` (old odigos.one bare-metal) and `100.89.147.103` (uxrls.com Jessica Docker) are still running but unused. Cancel contracts at leisure.

---

## Decided against

- 🚫 **Sales agent / public chat widget** (2026-05-28) — Replaced with a static FAQ at `odigos.one/faq`. Open-weights LLMs couldn't reliably stay on-script for product Q&A; a curated FAQ is more trustworthy and faster. Resolved the prior in-flight items "Sales identity drift" and "Site/proxy decoupling claim was wrong" in one move. `odigos-sales` systemd unit stopped + disabled, `agent-proxy.js` middleware deleted, WebSocket upgrade handler removed from `server.js`, Caddy `/api/sales/*` + `/api/agent` routes dropped. `/opt/odigos-sales/data/agent/*.md` retained on disk as the FAQ content source.

---

## Pre-launch blockers (before hosted paid signups)

These two land together — share the budget-tracker extension, and Pro tier's
image+music story only works reliably with both.

- 🔧 [Unified capabilities config](docs/superpowers/specs/2026-04-16-unified-capabilities-config-design.md) — Extend the `providers` + `models` + routing pattern to image, music, voice STT/TTS, embeddings. One BYOK UI for everything, cost-per-unit declared on each model, per-capability tier routing. ~3 focused days. **Build plan:** [`2026-05-28-unified-capabilities-config.md`](docs/superpowers/plans/2026-05-28-unified-capabilities-config.md)
- 🔧 [Unified cost tracking](docs/superpowers/specs/2026-04-16-unified-cost-tracking-note.md) — `BudgetTracker.record_tool_cost()` + `tool_costs` table (migration 013). Every paid tool call (Whisper STT, Kie.ai image, Kie.ai music) reports into the same daily/monthly cap the LLM calls already use. Activity page shows per-tool breakdown. **Build plan:** [`2026-05-28-unified-cost-tracking.md`](docs/superpowers/plans/2026-05-28-unified-cost-tracking.md) — ~1 focused day, ships independently or layered on top of the capabilities config.

## Pre-launch polish

- ⏭️ Rate limiting per-user at the API layer (messages/hour cap on
  `/api/message` so a runaway client can't exhaust the daily budget in
  a single minute)
- ⏭️ Graceful budget-hit UX copy review — current message is
  functional but not great ("spending limit for this period")
- ⏭️ Cross-agent cost aggregator script — each agent's `/api/budget` is
  per-instance; a small script summing across `data/odigos.db` files
  would give a fleet-wide bill estimate

## Auth unification — future levels

Level 1 SSO bridge (above) is shipped. Higher levels deferred until
multiple paying users exist:

- ⏭️ **Level 2 — linked accounts**: `platform_user_id` column on agent's
  `users` table, explicit "connect your odigos.one account" button.
- ⏭️ **Level 3 — full tenancy**: platform provisions agent instances on
  signup, subscription tier drives agent's `max_tool_turns` / budget /
  model allowlist. Multi-tenant or templated-instance model TBD.

## Active design questions

- 💭 Multi-modal model representation (separate `models:` entries vs
  `capabilities: [...]` list field) — covered in the capabilities
  spec; revisit when first real multi-modal use case lands
- 💭 Per-capability sub-caps in budget (`image_monthly_cap_usd`) —
  YAGNI until a Pro user asks, or a test shows tier separation is
  needed

## Future / nice-to-have

- ⏭️ Comment threads on notebooks (Workspace Phase 2)
- ⏭️ Unified document editing surface across all file types
  (Workspace Phase 3)
- ⏭️ Agent-to-agent mesh over NetBird (foundation shipped, broader
  integration patterns TBD)
- ⏭️ Public feed publisher (foundation shipped, discovery patterns TBD)

---

## Durability notes

- **`ROADMAP.md` (this file)** is the source of truth in-repo — version
  controlled, visible to anyone who clones the repo
- **`docs/superpowers/specs/`** holds design docs; each pre-launch
  blocker links here
- **`docs/superpowers/plans/`** holds implementation plans once a spec
  is ready to build
- **`~/odigos-vps-archive/MANIFEST.md`** (local-only) catalogs the
  salvage tarballs in case the VPS dies
