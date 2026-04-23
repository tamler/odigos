# Odigos Roadmap

Durable tracking of what's shipped, what's in design, and what's coming.
Keep this file short — one line per item, link out to specs/PRs for detail.

Legend: ✅ shipped · 🔧 in design · ⏭️ planned · 💭 open question

---

## Recently shipped

Last updated: 2026-04-16.

### Multi-provider + BYOK + intelligence routing (2026-04-14)
- ✅ Provider registry + model registry + `llm:` tier routing (`providers` / `models` / `llm`) — one yaml block per provider, costs travel with each model, four intelligence tiers (fast / smart / background / fallback), classifier auto-routing
- ✅ `${ENV_VAR}` interpolation in `config.yaml` so secrets stay in `.env`
- ✅ Dashboard BYOK panel — add/edit/delete providers + models + tier routing from the UI with masked-key handling, replace semantics on save
- ✅ `install.sh` + `install-bare.sh` + `scripts/fresh-install.sh` emit the new shape with per-provider templates (OpenRouter, OpenAI, Ollama, LM Studio, Custom) + Starter-tier defaults ($0.50/day, $10/mo, `max_tool_turns: 15`, `max_tokens: 2048`, proactive off)
- ✅ Prompt caching wiring — stable prefix ordering in `context.build_planned()`, cache_control helper for Anthropic models, per-turn cache hit logging via `tracer.emit("cache_hit", ...)` and `logger.info("LLM cache: ...")`
- ✅ `deploy.sh --fresh` flag for multi-agent reset + key-rotation across the fleet

### Account creation + operator pre-provisioning (2026-04-15)
- ✅ `/api/auth/setup` requires and stores email (migration `012_user_email.sql`)
- ✅ Dashboard Create Account form collects username + email + password with client-side regex validation
- ✅ `scripts/seed-account.sh` — operator one-liner pre-provisions `data/seed_user.json`; bootstrap consumes on first boot with `must_change_password: true` forcing change on first login
- ✅ `/api/auth/change-password` now verifies current password (was a real vulnerability — session-stealer could rotate without knowing the old password)

### Fleet deployed on odigos.one + uxrls.com (2026-04-14 → 04-16)
- ✅ Bob, Rachel, Sales, Honey, HomeRun on odigos.one; Odigos-main + Florence + Jessica on uxrls.com
- ✅ Sales on Groq dual-tier (Llama-4-Scout-17B fast, Llama-3.3-70B-versatile smart), identity + README + ARCHITECTURE + FAQ ingested, `max_tool_turns: 3` — ~1s on simple Q, ~5s on complex
- ✅ HomeRun on Groq Scout-17B (vision) + OpenRouter minimax-m2.7 (smart reasoning), `/api/message` verified with both tiers auto-routing, clean install, $15/mo cap
- ✅ `homerun.odigos.one` Caddy + Let's Encrypt cert provisioned

---

## Pre-launch blockers (before hosted paid signups)

These two land together — share the budget-tracker extension, and Pro tier's
image+music story only works reliably with both.

- 🔧 [Unified capabilities config](docs/superpowers/specs/2026-04-16-unified-capabilities-config-design.md)
  Extend the `providers` + `models` + routing pattern to image, music,
  voice STT/TTS, embeddings. One BYOK UI for everything, cost-per-unit
  declared on each model, per-capability tier routing. ~3 focused days.
- 🔧 [Unified cost tracking](docs/superpowers/specs/2026-04-16-unified-cost-tracking-note.md)
  `BudgetTracker.record_tool_cost()` + `tool_costs` table (migration 013).
  Every paid tool call (Whisper STT, Kie.ai image, Kie.ai music) reports
  into the same daily/monthly cap the LLM calls already use. Activity
  page shows per-tool breakdown. Pairs with capabilities config.

## Pre-launch polish

- ✅ Sales `api_key` / Express coupling (2026-04-23) — Express now reads
  Sales's `api_key` directly from `/opt/odigos-sales/config.yaml` at
  startup (no more `ODIGOS_AGENT_KEY` env var). `deploy.sh --fresh`
  auto-restarts `odigos-site` so the new key takes effect in one pass.
- ⏭️ Rate limiting per-user at the API layer (messages/hour cap on
  `/api/message` so a runaway client can't exhaust the daily budget in
  a single minute)
- ⏭️ Graceful budget-hit UX copy review — current message is
  functional but not great ("spending limit for this period")

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
  is ready to build — currently empty for these two specs; will
  populate when implementation starts
- Memory tracking (`~/.claude/projects/.../memory/project_next_updates.md`)
  mirrors this file — session-to-session continuity for the Claude
  working with Jacob
