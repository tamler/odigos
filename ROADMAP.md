# Odigos Roadmap

Durable tracking of what's shipped, what's in design, and what's coming.
Keep this file short — one line per item, link out to specs/PRs for detail.

Legend: ✅ shipped · 🔧 in design · ⏭️ planned · 💭 open question

---

## Current fleet (verified on-box 2026-08-12)

Single OVH VPS at `51.81.82.221` (Tailscale-only SSH at `100.80.26.2`, public 80/443 for Caddy).

| Service | Path | Domain | Port | Backend |
|---------|------|--------|------|---------|
| Honey (tester) | `/opt/odigos-honey` | `honey.odigos.one` | 8002 | `deployment.mode=hosted` · fast=`qwen/qwen3.7-flash` (vision) · smart=`~deepseek/deepseek-v4-flash-latest` · voice=groq STT + edge TTS · kie.ai image/music |
| Site (marketing + auth UI) | `/opt/odigos-site` | `odigos.one` | 3000 | Node/Express/SSR React |
| Platform API | `/opt/odigos-platform` | `odigos.one/api/v1/*` | 8080 | FastAPI + Postgres ([repo](https://github.com/tamler/odigos-platform), private) |
| Postgres | docker `odigos-postgres` | (internal, 127.0.0.1:5432) | 5432 | postgres:16-alpine |
| SearXNG | docker `searxng-searxng-1` | (internal) | 8083 | search backend for agents |

**Bob and Jessica are not currently installed.** The earlier version of this table listed them at
`/opt/odigos` and `/opt/odigos-jessica`; neither directory nor service exists on the box. The Unix
users `odigos_jacob` and `odigos_jessica` survive with no home dirs. Rebuild them as rows in
`deploy.sh`'s `INSTALLS` table, each with its own `odigos_<name>` user.

Honey (2026-08-12) is the first install provisioned under the C0 isolation checklist: dedicated
`odigos_honey` user, `0700` root, hardened systemd unit, `deployment.mode=hosted`, verified
`isolation=bwrap`. Use it as the template for the rest of the fleet.

Retired during 2026-05-27 migration: Rachel, HomeRun (odigos.one bare-metal); old Bob (data wiped);
Jessica Docker on uxrls.com. Retired 2026-05-28: Sales (public chat widget) — replaced with static
FAQ; unit is disabled but `/opt/odigos-sales` is retained as the FAQ content source.

> ⚠️ **Production is running an unmerged branch.** `odigos-honey` tracks
> `security/hardening-hosted-launch` (~40 commits ahead of `main`), not `main`. It has to: the
> `deployment.mode=hosted` gate, `DeploymentConfig`, and the bwrap startup enforcement exist only
> on that branch. `deploy.sh` pins the branch per install for this reason. The branch has not had
> a review pass. Until it merges, `main` is not deployable to a hosted install and hotfixes must
> go to the branch.

---

## Recently shipped

### Hosted launch: Honey + C0 isolation (2026-08-12)
- ✅ First C0-compliant hosted install (`honey.odigos.one`): own `odigos_honey` user, `0700` root,
  `0600` secrets, hardened unit, `UMask=0077`. Cross-install read denial verified both directions.
  Unit template: [`docs/deployment/odigos-hosted.service.example`](docs/deployment/odigos-hosted.service.example).
- 🔴 **The bwrap sandbox was never actually active on Linux.** The probe in `sandbox.py` omitted
  `--symlink /usr/lib64 /lib64`, which the real exec path always had. On x86_64 the ELF loader lives
  there, so every binary inside the probe namespace failed with ENOENT, detection fell through to
  the ulimit tier, and installs ran with **no filesystem isolation** while bubblewrap sat installed
  and apparently fine. Compounding it, `_enforce_hosted_security` gated on `shutil.which("bwrap")`
  — binary on PATH, not binary works — so hosted mode booted happily at `isolation=ulimit`.
  Both fixed; the gate now checks the resolved tier and was negative-tested. **Any earlier claim
  that agent-run code was sandboxed on a Linux deploy was wrong** — re-verify `isolation=bwrap`
  on every install as it comes back.
- ✅ `RestrictAddressFamilies` must include `AF_NETLINK` or `bwrap --unshare-all` cannot bring up
  loopback and the sandbox silently degrades. The checklist previously prescribed a value that
  breaks bwrap.
- ✅ `deploy.sh` retargeted: it pointed at two dead hosts with no entry for the live VPS, and ran
  four installs as one shared `odigos_agent` user. Now one user per install, enforced by preflight
  and `tests/test_deploy_install_table.py`, with a post-deploy conformance gate on
  `mode=hosted isolation=bwrap`.
- ✅ `fresh-install.sh` emitted two top-level `agent:` keys; YAML last-wins silently discarded
  `name:`, so every fresh install booted as "Odigos". Also wrote secrets `0644` and put `api_key`
  in the operator-edited `config.yaml`.
- ✅ `uv.lock` was missing `pyjwt` despite `pyproject.toml` declaring it — a clean clone left
  `import jwt` unsatisfied.

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

- 🔴 **Review + merge `security/hardening-hosted-launch`** — it is in production on Honey unreviewed
  (see the warning above). Nothing else should ship to a hosted install until this lands.
- 🔧 **Modality-aware model routing** — `ModelConfig.vision` is declared in `config.py:64` and read
  by *nothing*. Routing is purely by classification tier (`executor.py:396-407`): a request carrying
  an image is not steered to a vision-capable model. The practical consequence is that a vision model
  is unreachable unless it occupies a routing tier, which is why Honey has `qwen3.7-flash` on `fast`
  rather than as a dedicated vision entry. Either honour `vision` when the payload has an image, or
  drop the field so it stops implying behaviour it does not have.
- ⏭️ **Migrations re-add existing columns on a fresh DB** — a brand-new install logs
  `duplicate column name` warnings for migrations 005, 007, 008, 009, 010, 011, 012, 014 and 015.
  Benign (the schema evolves correctly) but it makes real migration failures easy to miss in a
  noisy boot log. `schema.sql` and the migration set overlap; pick one as the source of truth.
- ⏭️ **Repo-wide lint debt** — `ruff check odigos/ tests/` reports 205 errors on `main`, 159
  auto-fixable. Not introduced by recent work; worth a single sweep commit so new violations are
  visible.
- ⏭️ **Honey's account email is the placeholder `honey@odigos.one`** — direct login is unaffected,
  but SSO from the platform with her real address would auto-provision a *second* user instead of
  matching this one. Fix before she is pointed at the "Open my agent" button.

- 🔧 **Brittleness audit + robustness plan** ([spec](docs/superpowers/specs/2026-05-28-brittleness-audit-and-robustness.md)) — Today's session found 8 instances of the same pattern: "simplifications" that backfired against real LLM behavior (truncated IDs the model copied as values, sparse find_tools output, missing skill tool-blocks, missing kanban_create_board tool, opaque FK errors, identity-only persona loading, aggressive context pruning). All 8 fixed live. The spec catalogs the pattern, codifies operating principles ("LLM-facing output is contract, not display"), and lays out a 3-phase plan: audit + remaining fixes → robustness infrastructure (blank-slate smoke tests, skill validation, find_tools coverage, stable prefix order) → ongoing behavioral telemetry.
- ⏭️ **Old VPS wipes** — `82.25.91.86` (old odigos.one bare-metal) and `100.89.147.103` (uxrls.com Jessica Docker) are dead as of 2026-08-12. `deploy.sh` no longer targets either, and `tests/test_deploy_install_table.py` fails if they reappear. Remaining work is registrar/contract cleanup and removing the stale `odigos-old` / uxrls entries from `~/.ssh/config`.
- ⏭️ **Admin dashboard — dedicated Waitlist view** — Today the dashboard shows waitlist signups as duplicate generic rows (one in Recent Inquiries with name "Unknown" + "Waitlist signup for managed-hosting", one in Contacts with empty name + status badge). Replace with: (a) a top-level "Waitlist" section listing email + product (notes field) + signup date + mailto link; (b) stop the double-write in `/api/v1/waitlist` (skip the inquiry insert for waitlist source); (c) sort by recency, optional filter by product. Touches `src/pages/Dashboard.tsx`, `server/routes/pages.js` (apiFetch), and `platform/app/api/contacts.py`.
- ⏭️ **OVH schema drift fix** — On 2026-05-28 we patched live OVH Postgres with `idx_contacts_email`, `idx_users_email`, and `idx_users_chosen_subdomain` UNIQUE indexes that the platform-team migration didn't carry over. Migration 001 declares these via `email TEXT UNIQUE NOT NULL` but the OVH dump lost them. Either add a `006_index_repair.sql` migration that recreates them idempotently, or add a CI check that compares live schema vs `pg_dump --schema-only` of the migrations folder.

---

## Decided against

- 🚫 **Sales agent / public chat widget** (2026-05-28) — Replaced with a static FAQ at `odigos.one/faq`. Open-weights LLMs couldn't reliably stay on-script for product Q&A; a curated FAQ is more trustworthy and faster. Resolved the prior in-flight items "Sales identity drift" and "Site/proxy decoupling claim was wrong" in one move. `odigos-sales` systemd unit stopped + disabled, `agent-proxy.js` middleware deleted, WebSocket upgrade handler removed from `server.js`, Caddy `/api/sales/*` + `/api/agent` routes dropped. `/opt/odigos-sales/data/agent/*.md` retained on disk as the FAQ content source.

- 🚫 **Trading product on odigos.one** (2026-05-28) — Trading project spun into a standalone tool. Removed from odigos.one: `src/pages/Trading.tsx`, `platform/app/api/trading.py`, the Dashboard "Trading Overview" section, `trading_api_key` setting, `trading.odigos.one` from `product_subdomains`. Migration `006_drop_trading.sql` drops `trading_positions` and `trading_performance` tables. `TRADING_API_KEY` removed from `odigos-site.service` and `PLATFORM_TRADING_API_KEY` removed from `platform.env`. The `trading.odigos.one` DNS record at the registrar still exists — remove there if desired (Caddy has no handler for it, so it currently 404s).

---

## Pre-launch blockers (before hosted paid signups)

- 🔧 [Unified capabilities config](docs/superpowers/specs/2026-04-16-unified-capabilities-config-design.md) — Extend the `providers` + `models` + routing pattern to image, music, voice STT/TTS, embeddings. One BYOK UI for everything, cost-per-unit declared on each model, per-capability tier routing. ~3 focused days. **Build plan:** [`2026-05-28-unified-capabilities-config.md`](docs/superpowers/plans/2026-05-28-unified-capabilities-config.md). Cost tracking (the spec's pair) already shipped — this refactor will move per-call costs from hardcoded constants to `ModelConfig.cost_per_unit`.

### Cost tracking (2026-05-28) — shipped

- ✅ Migration 013 adds `tool_costs` table; `schema.sql` updated for fresh installs.
- ✅ `BudgetTracker.record_tool_cost(cost_usd, *, source, conversation_id, tool_name, metadata)` records paid-tool spend; `check_budget()` aggregates LLM + tool spend into the same daily/monthly cap.
- ✅ Per-tool reporters wired: `GenerateImageTool` ($0.03/img, Kie.ai), `GenerateMusicTool` ($0.15/track, Kie.ai), `GroqSTT` ($0.04/audio-min, Whisper). Failures don't record.
- ✅ `/api/budget` returns a new `by_source: {llm, whisper, kie_image, kie_music, ...}` map; Activity page renders it as wrapped chips under the Remaining line.
- ✅ Bootstrap reorder: BudgetTracker now constructs before STT/image/music so tools can be wired with it at registration time.
- ⏭️ Per-capability sub-caps (`image_monthly_cap_usd: 3.00`) — design stub in `config.yaml.example`; not implemented. YAGNI until a Pro user asks.

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
