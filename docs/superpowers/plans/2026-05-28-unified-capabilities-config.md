# Unified Capabilities Config Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` or `superpowers:subagent-driven-development`. Steps use `- [ ]` checkboxes.

**Goal:** Extend the `providers` + `models` + tier-routing pattern (currently LLM-only) to image, music, voice STT/TTS, and embeddings. One BYOK UI for everything, cost-per-unit declared on each model, per-capability tier routing. Multi-modal model support via repeated entries sharing `provider` + `id`.

**Architecture:** New `CapabilityRegistry` (`odigos/providers/registry.py`) that resolves `(capability, tier) → ModelConfig + client`. `LLMClient` keeps tier-dispatch on top of the registry. Image/music/STT/TTS tools refactored to use the registry instead of hardcoded provider logic. New `kie_ai` and `edge_tts` provider client classes. Config-loader migration shim auto-converts legacy `image_generation:` / `music_generation:` / `voice:` blocks into the new shape.

**Tech Stack:** Python (pydantic, aiosqlite, edge-tts, existing tool framework), React (BYOK dashboard UI extension)

**Spec:** [`docs/superpowers/specs/2026-04-16-unified-capabilities-config-design.md`](../specs/2026-04-16-unified-capabilities-config-design.md)

**Pairs with:** [`2026-05-28-unified-cost-tracking.md`](./2026-05-28-unified-cost-tracking.md) — capabilities config ships first, cost tracking layers on top using the model's declared `cost_per_unit`.

**Effort estimate:** ~3 focused days end-to-end (per spec §8). Plan splits across 5 phases for clean checkpointing.

---

## Phase 1 — Schema + types (Day 1 morning)

### Task 1.1: Extend ProviderConfig

**Files:**
- Modify: `odigos/config.py`

- [ ] Add `kind: Literal["openai_compatible", "kie_ai", "edge_tts", "local", "local_stt", "local_tts"] = "openai_compatible"` to `ProviderConfig`.
- [ ] Backward-compat: existing provider blocks without `kind:` default to `openai_compatible` (no migration needed).
- [ ] Verify: `pytest tests/test_config.py` (or equivalent) — existing tests still pass.

### Task 1.2: Extend ModelConfig with capability + per-unit cost

**Files:**
- Modify: `odigos/config.py`

- [ ] Add `capability: Literal["llm", "image", "music", "stt", "tts", "embedding"] = "llm"` (default keeps existing model entries valid).
- [ ] Add `cost_per_unit: float = 0.0`, `unit: str = ""`.
- [ ] Add capability-specific optional fields: `aspect_ratios: list[str] = []`, `max_duration_seconds: int = 0`.
- [ ] Verify: load a config with existing-shape `models:` block → no errors; load with new `capability: image` model → validates.

### Task 1.3: Introduce CapabilitiesConfig + LLMRouting

**Files:**
- Modify: `odigos/config.py`

- [ ] Add `CapabilityRouting(BaseModel)` (allow extra tier names like `quick`).
- [ ] Add `LLMRouting(CapabilityRouting)` that merges existing `LLMConfig` fields (fast/smart/background/fallback/max_tokens/temperature/auto_route).
- [ ] Add `CapabilitiesConfig` with optional per-capability routing.
- [ ] Update `Settings` to expose `capabilities: CapabilitiesConfig` alongside the existing `llm:` block.

### Task 1.4: Migration shim in load_settings()

**Files:**
- Modify: `odigos/config.py::load_settings()`

- [ ] Add `_migrate_legacy_capabilities(yaml_config)` before `Settings(**yaml_config)` is called. Convert legacy blocks per spec §6:
  - `image_generation:` → provider `kie_ai` + model `z-image` + `capabilities.image.default = z-image`
  - `music_generation:` → provider `kie_ai` + model `suno-v5` + `capabilities.music.default = suno-v5`
  - `voice.stt_provider/groq_model` → provider `groq` (already exists) + model `whisper-large` + `capabilities.stt.default = whisper-large`
  - `voice.tts_provider/tts_voice` → provider `edge` + model `edge-<voice>` + `capabilities.tts.default = edge-<voice>`
  - `embeddings:` → provider `local_embeddings` + model `nomic-embed` + `capabilities.embedding.default = nomic-embed`
  - Top-level `llm:` block → `capabilities.llm` (keep existing keys)
- [ ] Log a one-time WARNING when migration runs: `"Auto-migrated legacy '{block}' config to unified capabilities shape; consider running install.sh or editing config.yaml to the new shape."`
- [ ] Verify: round-trip — load a legacy `config.yaml`, dump the migrated dict, reload it → identical Settings.

### Task 1.5: Config validator updates

**Files:**
- Modify: `odigos/config_validator.py`

- [ ] Validate every `capabilities.<cap>.{tier}` reference points to an existing `models` entry with matching `capability`.
- [ ] Validate every `models.<m>.provider` references an existing `providers` entry.
- [ ] Test with a bogus reference → clear error message.

**Checkpoint 1:** All existing tests pass with both legacy and new-shape configs. Migration shim verified round-trip. Ship as a no-op for end users.

---

## Phase 2 — CapabilityRegistry + LLM refactor (Day 1 afternoon)

### Task 2.1: CapabilityRegistry

**Files:**
- Create: `odigos/providers/registry.py`

- [ ] Implement per spec §4:
  ```python
  class CapabilityRegistry:
      def __init__(self, providers, models, routing): ...
      def resolve(self, capability: str, tier: str = "default") -> tuple[ModelConfig, Any]: ...
      def list_models_for(self, capability: str) -> list[ModelConfig]: ...
  ```
- [ ] `_clients_by_kind` map points to client classes (initially: `openai_compatible` → existing `LLMClient`-compatible HTTP wrapper).
- [ ] Verify: unit test resolve("llm", "fast") on a config with the existing scout model — returns matching model + a working client.

### Task 2.2: Refactor LLMClient to use registry

**Files:**
- Modify: `odigos/providers/llm.py`

- [ ] `LLMClient.__init__` takes `registry: CapabilityRegistry` instead of (or alongside) the existing `providers` + `models` dicts.
- [ ] `LLMClient.resolve(tier)` → `registry.resolve("llm", tier)`. Keep intelligence-tier classifier on top.
- [ ] All existing call sites that construct an `LLMClient` get the registry instead of raw dicts.
- [ ] Verify: full agent chat flow still works (Bob/Jessica/Sales — already-deployed agents).

**Checkpoint 2:** LLM behavior unchanged for end users; capabilities config is now wired through the registry. No image/music/voice changes yet.

---

## Phase 3 — Tool refactors (Day 2)

### Task 3.1: Kie.ai unified client

**Files:**
- Create: `odigos/providers/kie_ai.py`

- [ ] Extract Kie.ai HTTP + polling logic from `tools/image_gen.py` and `tools/music_gen.py` into a single `KieAIClient` class.
- [ ] Methods: `async def generate_image(model_id, prompt, aspect_ratio, **opts) -> bytes`, `async def generate_music(model_id, prompt, **opts) -> bytes`.
- [ ] Returns the raw bytes + a `metadata` dict including `credits_used` (Kie.ai surfaces this in their responses).

### Task 3.2: Refactor ImageGenTool

**Files:**
- Modify: `odigos/tools/image_gen.py`

- [ ] Constructor takes `registry: CapabilityRegistry` instead of direct Kie.ai client setup.
- [ ] `execute()`: `model, client = self.registry.resolve("image", params.get("tier", "default"))`.
- [ ] Pass `model.id`, `model.aspect_ratios` to client.
- [ ] Verify: image gen still works through Bob/Jessica.

### Task 3.3: Refactor MusicGenTool

**Files:**
- Modify: `odigos/tools/music_gen.py`

- [ ] Same pattern as 3.2 but `capability="music"`.
- [ ] Verify: music gen still works.

### Task 3.4: Edge TTS client + STT/TTS refactor

**Files:**
- Create: `odigos/providers/edge_tts.py`
- Modify: `odigos/providers/stt.py`
- Modify: wherever TTS lives (probably `odigos/providers/tts.py` or inline in voice flow)

- [ ] `EdgeTTSClient` wraps the `edge-tts` library, returns audio bytes.
- [ ] STT provider checks `registry.resolve("stt", "default")` to get the model (Whisper via Groq, or local Moonshine if configured).
- [ ] TTS provider same: `registry.resolve("tts", "default")` returns the configured voice.
- [ ] Verify: voice STT round-trip works; TTS generates a clip with the configured voice.

### Task 3.5: Embeddings refactor (optional v1, behind feature flag)

**Files:**
- Modify: `odigos/providers/embeddings.py`

- [ ] If `capabilities.embedding` is configured, use registry; else fall back to existing logic.
- [ ] Note in spec §9: embedding-index rebuild may be expensive — feature flag prevents accidental switches.

**Checkpoint 3:** All five capabilities run through the registry. End-user experience unchanged but every tool now has a swap-the-model path.

---

## Phase 4 — Cost tracking integration (Day 2 evening, ~2 hrs)

Pairs with [`2026-05-28-unified-cost-tracking.md`](./2026-05-28-unified-cost-tracking.md). Now that every tool resolves its model via the registry, the model carries its own `cost_per_unit` — the tool can record cost without hardcoding rates.

### Task 4.1: Apply cost-tracking plan, Chunks 1–3

- [ ] Follow [`2026-05-28-unified-cost-tracking.md`](./2026-05-28-unified-cost-tracking.md). Per-tool reporters use `model.cost_per_unit` instead of hardcoded $0.03 / $0.15 / etc.
- [ ] `record_tool_cost(cost_usd=model.cost_per_unit, source=model.capability, ...)`

**Checkpoint 4:** Per-call cost recorded for image/music/voice STT calls; daily/monthly cap aggregates correctly.

---

## Phase 5 — Dashboard UI + install scripts + tests (Day 3)

### Task 5.1: Dashboard BYOK UI extension

**Files:**
- Modify: `dashboard/src/pages/settings/GeneralSettings.tsx` (or wherever the existing Providers/Models/Routing panel lives)

- [ ] **Providers section** — no functional change; just remove any LLM-specific copy/labels.
- [ ] **Models section** — add a capability filter dropdown at the top (All / LLM / Image / Music / STT / TTS / Embedding). Models display their `capability` badge.
- [ ] **Routing section** — refactor into an accordion: one panel per configured capability. LLM panel shows fast/smart/background/fallback dropdowns (current UI). Image panel shows default/quick. Music shows default. Etc.
- [ ] Same masked-key UX and replace-on-save semantics as the LLM-only version.
- [ ] Verify: from the dashboard, add a new image provider + model + set it as the default — restart agent, generate image, confirm it used the new one.

### Task 5.2: Install scripts

**Files:**
- Modify: `install.sh`, `install-bare.sh`, `scripts/fresh-install.sh`
- Modify: `config.yaml.example`

- [ ] All emit the new `providers:` + `models:` + `capabilities:` shape.
- [ ] Per-provider templates updated: Kie.ai entry now lives under `providers.kie_ai` (with `kind: kie_ai`), default Z-Image and Suno V5 models in `models:`, and `capabilities.image.default = z-image` / `capabilities.music.default = suno-v5`.
- [ ] Starter-tier defaults preserved (`max_tool_turns: 15`, `max_tokens: 8192`, image gen on, music gen on but cap-protected, proactive off).

### Task 5.3: Tests

**Files:**
- Create: `tests/test_capability_registry.py`
- Create: `tests/test_config_migration.py`
- Modify: existing tool tests to use the registry

- [ ] Registry tests: resolve all 6 capabilities on a sample config; missing tier returns clear error; bogus model id returns clear error.
- [ ] Migration tests: load each legacy block shape, assert it converts to expected new shape.
- [ ] Tool integration tests: image_gen / music_gen / stt / tts hit the registry path.

### Task 5.4: Staging verification

**Files:** (none — verification only)

- [ ] On a fresh `install-bare.sh`, generate an image + music track + voice clip. Check `tool_costs` table populated.
- [ ] On an existing install with legacy config, restart → migration shim runs once → `config.yaml` still works → image gen still works.
- [ ] Dashboard add-an-image-provider flow end-to-end.

### Task 5.5: Deprecation log + roadmap update

**Files:**
- Modify: `odigos/config.py` — change the migration log from WARNING to a one-shot INFO with "removal in 2 releases" note.
- Modify: `ROADMAP.md` — move "Unified capabilities config" + "Unified cost tracking" from `🔧 in design` → `✅ shipped`.

---

## Sequencing

Phases run mostly in order. Within a phase, tasks can parallelize where files don't overlap.

- **Day 1:** Phase 1 (schema + migration shim) → Phase 2 (registry + LLM refactor). Checkpoint: nothing user-facing changed.
- **Day 2:** Phase 3 (tool refactors) → Phase 4 (cost tracking integration). Checkpoint: per-tool spend visible, BYOK pathway exists in code.
- **Day 3:** Phase 5 (UI + install + tests + staging). Ship.

Don't ship Phase 3 without Phase 2. Don't ship Phase 4 without Phase 3. Phase 5 can interleave with Phase 4.

## Rollback per phase

- Phase 1: revert pydantic changes — no on-disk migration so nothing to undo.
- Phase 2: registry refactor is internal — keep both `LLMClient` constructors during transition if needed.
- Phase 3: tool refactors are isolated per tool — can revert one without affecting others.
- Phase 4: see cost-tracking rollback section.
- Phase 5: UI is additive (the capability filter is opt-in); install scripts can be reverted to emit old shape (the loader migrates either way).

## Open questions (decide before starting)

- **Multi-modal Gemini 2.5** — separate `models:` entries per capability vs `capabilities: [list]` field. Spec §9 recommends separate entries. Lock this in before Phase 1.
- **BYOK STT specifically** — OpenAI Whisper via `openai_compatible` provider — confirm endpoint shape during Phase 3.
- **Embedding routing v1** — feature-flagged in Phase 3.5 to avoid breaking existing indexes.
- **Per-capability sub-caps in budget** — covered in the cost-tracking plan; do NOT add to v1 of this refactor.
