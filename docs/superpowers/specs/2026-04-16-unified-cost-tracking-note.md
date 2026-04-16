# Unified cost tracking — voice, image, music

**Status:** note / future consideration
**Date:** 2026-04-16
**Motivation:** hosted-tier safety + possible product feature

## Problem

`BudgetTracker` currently only sees LLM token costs (from `LLMResponse.cost_usd`).
External-service tool spend — Groq Whisper STT, Kie.ai image gen, Kie.ai music
gen — bypasses the budget system entirely. A user could burn $75 on Suno
music generations while the daily/monthly `budget` caps read $0.00 spent.

For personal / self-hosted installs this is an edge case. For **hosted
multi-tenant tiers** (Starter $15/mo, Pro $35/mo) this is a real revenue
risk — the pricing math only holds if every dollar the agent spends is
tracked against the user's cap.

## Current untracked surface

| Tool | Provider | Unit cost (2026-04) | Tracked today? |
|---|---|---|---|
| `VoiceSTTTool` (Whisper) | Groq | ~$0.04 / audio-minute | ❌ |
| `GenerateImageTool` | Kie.ai (Z-Image) | ~$0.01-0.05 / image (resolution-dep) | ❌ |
| `GenerateMusicTool` | Kie.ai (Suno V5_5) | ~$0.10-0.20 / track | ❌ |
| `EdgeTTSProvider` | Microsoft Edge (free, rate-limited) | — | n/a |
| LLM calls | Groq / OpenRouter / NVIDIA / OpenAI / Anthropic | varies | ✅ |

## Design sketch

Minimal changes, ~1 day of work, no new dependencies:

1. **`BudgetTracker.record_tool_cost(cost_usd: float, *, source: str, conversation_id: str | None)`**
   — tools call this after a successful billable action. Writes to a new
   `tool_costs` table and adds to the running daily/monthly totals.

2. **New `tool_costs` table** (migration `013_tool_costs.sql`):
   ```sql
   CREATE TABLE tool_costs (
       id TEXT PRIMARY KEY,
       conversation_id TEXT,
       source TEXT NOT NULL,  -- 'whisper', 'kie_image', 'kie_music', etc.
       tool_name TEXT,
       cost_usd REAL NOT NULL,
       metadata_json TEXT,
       created_at TEXT DEFAULT (datetime('now'))
   );
   CREATE INDEX idx_tool_costs_created ON tool_costs(created_at DESC);
   ```

3. **Per-tool cost reporters**:
   - `VoiceSTTTool._cost()` returns `audio_seconds / 60 * 0.04`
   - `GenerateImageTool._cost()` returns `0.03` (or a lookup by aspect ratio)
   - `GenerateMusicTool._cost()` returns `0.15` (per generation)
   - Each tool calls `budget_tracker.record_tool_cost(...)` on success.
   - Failure path: no cost recorded (matches how LLM failures are free today).

4. **Executor pre-call check expanded**: `status.within_budget` aggregates
   LLM cost + tool cost. Same degradation tiers — warn at 80%, hard refuse
   at 100%.

5. **Optional per-capability sub-caps** in `config.yaml`:
   ```yaml
   budget:
     daily_limit_usd: 2.00         # total across everything
     monthly_limit_usd: 15.00
     image_monthly_cap_usd: 3.00   # OPTIONAL — sub-cap within total
     music_monthly_cap_usd: 5.00
     voice_daily_minutes: 30
   ```
   Pro tier could ship with larger image/music caps; Starter leans on
   just the combined total.

6. **Activity page surfacing**: breakdown panel on the cost widget showing
   `LLM $12.40 / Images $2.10 / Music $0.45 / Voice $0.05` so operators
   and users can see where spend actually goes.

## Open questions

- **Is this a real product feature or testing scaffolding?**
  If image/music stay permanently available on Pro tier, cost tracking is
  mandatory. If they're only for demos / testing, rate-limiting alone may
  be sufficient. User's current stance: lean toward real feature IF
  integration is clean and spend is visible.

- **How to price fairly?** Kie.ai and Groq prices will drift. Hardcoding
  rates in the tool class means we need a `scripts/refresh-tool-prices.sh`
  or similar to keep them current. Alternative: the tool asks its provider
  for the actual billed cost from the response (Kie.ai does return
  `credits_used` in their API response — translate to USD).

- **How does this interact with "bring your own Kie.ai key"?**
  If the user supplies their own Kie.ai / Groq key via the dashboard Services
  panel, they're paying the provider directly. Budget tracking becomes
  informational ("you used $X of kie.ai credits") rather than a hard gate.
  Similar pattern to the BYOK LLM flow — host-provided keys have caps,
  user-provided keys are unlimited.

## Relation to existing work

- Follows the same pattern as the recent provider/model refactor: BYOK-
  friendly, per-capability configuration, sensible defaults baked into
  `install.sh` / `fresh-install.sh`.
- Aligns with the Starter / Pro / BYOK tier structure documented in
  `README.md` — Pro tier's "image + music on" claim only holds reliably
  once costs are tracked.

## Disposition

Not blocking HomeRun or the other testers. Revisit before opening hosted
signups to paying customers — that's when untracked tool spend becomes
real money risk. Tag: `cost-safety`, `hosted-readiness`.
