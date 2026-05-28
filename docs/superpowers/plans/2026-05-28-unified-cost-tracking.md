# Unified Cost Tracking Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans`. Steps use `- [ ]` checkboxes.

**Goal:** Track per-call cost for every paid tool (Whisper STT, Kie.ai image, Kie.ai music) in the same `BudgetTracker` that already covers LLM spend, so daily/monthly caps actually cap and the Activity page can show per-tool breakdown.

**Architecture:** New `tool_costs` table (migration 013), `BudgetTracker.record_tool_cost()` extension method, per-tool `_cost()` reporters that call it on success. Executor's pre-call budget check aggregates LLM + tool spend.

**Tech Stack:** Python (existing `BudgetTracker`, aiosqlite), React (Activity page widget update)

**Spec:** [`docs/superpowers/specs/2026-04-16-unified-cost-tracking-note.md`](../specs/2026-04-16-unified-cost-tracking-note.md)

**Effort estimate:** ~1 focused day (per spec). Can ship without the larger capabilities-config refactor — they're complementary but independent.

---

## Chunk 1: Schema + tracker

### Task 1.1: Migration

**Files:**
- Create: `migrations/013_tool_costs.sql`

- [ ] Create the migration file (DDL from spec §3.2):
  ```sql
  CREATE TABLE IF NOT EXISTS tool_costs (
      id TEXT PRIMARY KEY,
      conversation_id TEXT,
      source TEXT NOT NULL,       -- 'whisper', 'kie_image', 'kie_music', etc.
      tool_name TEXT,
      cost_usd REAL NOT NULL,
      metadata_json TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_tool_costs_created ON tool_costs(created_at DESC);
  CREATE INDEX IF NOT EXISTS idx_tool_costs_source ON tool_costs(source);
  ```
- [ ] Verify: restart any agent; check `data/odigos.db` has the new table:
  `sqlite3 data/odigos.db ".schema tool_costs"`

### Task 1.2: Extend BudgetTracker

**Files:**
- Modify: `odigos/core/budget.py`

- [ ] Add `record_tool_cost(cost_usd, *, source, conversation_id=None, tool_name=None, metadata=None)` method that INSERTs into `tool_costs` and updates the in-memory daily/monthly running totals if they're cached.
- [ ] Extend `check_budget()` (the existing function — see `odigos/core/budget.py:53`) to SUM cost from `messages` (LLM) **and** `tool_costs`. Both contribute to `daily_spend` / `monthly_spend` in the returned `BudgetStatus`.
- [ ] Verify: write a test that records a tool cost and asserts `check_budget()` reflects it.

---

## Chunk 2: Tool reporters

For each tool, add a small cost calculation and call `budget_tracker.record_tool_cost(...)` on success path only.

### Task 2.1: VoiceSTTTool (Whisper)

**Files:**
- Modify: `odigos/providers/stt.py` (or wherever the Groq STT call lives)
- Modify: `odigos/tools/voice_stt.py` if separate

- [ ] After a successful Whisper response, compute `cost = audio_seconds / 60 * 0.04`
- [ ] Call `self.budget_tracker.record_tool_cost(cost, source="whisper", conversation_id=conv_id, tool_name="voice_stt", metadata={"audio_seconds": audio_seconds})`
- [ ] Failures (network error, rate limit) record nothing — matches LLM behavior.
- [ ] Verify: send a voice clip, check `tool_costs` row created with correct cost.

### Task 2.2: GenerateImageTool (Kie.ai)

**Files:**
- Modify: `odigos/tools/image_gen.py`

- [ ] After successful generation, compute `cost` (start with flat $0.03; later make aspect-ratio aware per `models.z-image.cost_per_unit` once capabilities-config lands).
- [ ] Call `record_tool_cost(cost, source="kie_image", tool_name="generate_image", metadata={"aspect_ratio": aspect_ratio, "kie_credits_used": kie_response.get("credits_used")})`.
- [ ] Kie.ai's response includes `credits_used` — capture it in metadata for future reconciliation.
- [ ] Verify: generate an image, check `tool_costs` shows $0.03 row.

### Task 2.3: GenerateMusicTool (Kie.ai Suno)

**Files:**
- Modify: `odigos/tools/music_gen.py`

- [ ] After successful generation, record `cost = 0.15` (per-track flat for now).
- [ ] `source="kie_music"`, `tool_name="generate_music"`, metadata includes `model`, `kie_credits_used`.
- [ ] Verify: generate music, check row.

---

## Chunk 3: Budget enforcement integration

### Task 3.1: Executor pre-call check

**Files:**
- Modify: `odigos/core/executor.py` (the place that calls `budget_tracker.check_budget()` before LLM calls)

- [ ] No code change needed if Chunk 1.2 already made `check_budget()` aggregate both sources — the existing call sites will now see combined spend.
- [ ] Verify the same `within_budget=False` branch fires when tool costs alone push past the cap (test by lowering cap to $0.01 and generating one image).

### Task 3.2: Optional per-capability sub-caps

**Files:**
- Modify: `odigos/config.py` — `BudgetConfig`

- [ ] Add optional fields: `image_monthly_cap_usd`, `music_monthly_cap_usd`, `voice_daily_minutes` (all default 0 = no sub-cap).
- [ ] In `check_budget()`, if a sub-cap is set, also check the per-source aggregate from `tool_costs` and refuse with a sub-cap-specific message.
- [ ] Verify: set `image_monthly_cap_usd: 0.01`, generate one image, attempt another → blocked.

**Status check:** Sub-caps are a nice-to-have. Ship Chunks 1–3.1 first; do 3.2 only if a tier actually needs it.

---

## Chunk 4: Dashboard surfacing

### Task 4.1: Activity page breakdown

**Files:**
- Modify: `odigos/api/budget.py` — `/api/budget` endpoint
- Modify: `dashboard/src/components/activity/HeroSection.tsx` (the BudgetCard inside)

- [ ] Extend the `BudgetStatus` dataclass with optional `by_source: dict[str, float]` populated from a `SELECT source, SUM(cost_usd) FROM tool_costs WHERE created_at >= today GROUP BY source`. LLM goes in `by_source["llm"]`.
- [ ] Frontend: under the existing `$daily_spend / $daily_limit` line, render a tiny breakdown chip per source (e.g. `LLM $0.40 · Image $0.03 · Music $0.15`).
- [ ] Verify: hit Activity page, see breakdown populated.

---

## Chunk 5: Docs + release

### Task 5.1: README + config example

**Files:**
- Modify: `config.yaml.example` — add a `# Optional sub-caps` comment block under `budget:`
- Modify: `README.md` — short paragraph in the "Budget" section about per-tool tracking

### Task 5.2: Roadmap update

**Files:**
- Modify: `ROADMAP.md`

- [ ] Move "Unified cost tracking" from `🔧 in design` → `✅ shipped` section with the date.

---

## Sequencing

1. Chunk 1 → 2.1 → 2.2 → 2.3 → 3.1 → 4 → 5
2. Chunk 3.2 (sub-caps) only if requested
3. Don't gate on the larger capabilities-config refactor — this is independent

## Rollback

Each chunk is reversible:
- Migration 013 only adds a table — drop it with `DROP TABLE tool_costs;`
- Tool reporters guard with `if self.budget_tracker:` so absent tracker = no-op
- Dashboard breakdown degrades gracefully if backend doesn't return `by_source`
