# Unified capabilities config — design

**Status:** design / pre-implementation
**Date:** 2026-04-16
**Related:** [`2026-04-16-unified-cost-tracking-note.md`](./2026-04-16-unified-cost-tracking-note.md)
**Motivation:** extend the BYOK + routing pattern from LLMs to every billable
capability (image, music, voice STT/TTS, embeddings, future universal models)

---

## 1. Problem

The LLM layer has a clean three-tier config shape:

- `providers` — named endpoints (base_url + api_key with `${VAR}` interpolation)
- `models` — named model entries (id + provider + costs + capabilities)
- `llm` — intelligence-tier routing (fast / smart / background / fallback)

Every other billable capability — **image generation, music generation,
voice STT, voice TTS** — is special-cased in its own hardcoded config
block. Operators can't mix providers per capability without code changes,
BYOK UI doesn't support them, and when a multi-modal model (e.g. Gemini
2.5 handling text + image + audio from one endpoint) arrives, the config
shape can't represent it.

**This design unifies the LLM pattern across every capability.** One
providers registry. One models registry. One routing table per capability.
One UI pattern. One cost-tracking path.

---

## 2. Current state — what's hardcoded

| Capability | Where it lives today | Issue |
|---|---|---|
| LLM | `providers:` + `models:` + `llm:` (good) | ✅ |
| Image generation | `image_generation:` block, `services.kie_ai` for key, provider hardcoded to Kie.ai Z-Image in `tools/image_gen.py` | Can't BYOK for images, can't swap model, no cost tracking |
| Music generation | `music_generation:` block, shares `services.kie_ai`, provider hardcoded to Kie.ai Suno in `tools/music_gen.py` | Same |
| Voice STT | `voice.stt_provider: groq`, `voice.groq_model: whisper-large-v3-turbo`, provider union logic in `providers/stt.py` | Partially configurable, but not via BYOK UI |
| Voice TTS | `voice.tts_provider: edge`, `voice.tts_voice: ...` | Same |
| Embeddings | `embeddings.mode: auto/local/remote`, `embeddings.remote_url: ...` | No provider registry, no cost model |

---

## 3. Proposed shape

```yaml
# One registry of providers — any capability can reference any of these
providers:
  openrouter:
    kind: openai_compatible
    base_url: "https://openrouter.ai/api/v1"
    api_key: "${OPENROUTER_API_KEY}"
  groq:
    kind: openai_compatible
    base_url: "https://api.groq.com/openai/v1"
    api_key: "${GROQ_API_KEY}"
  kie_ai:
    kind: kie_ai                  # provider-specific client
    base_url: "https://api.kie.ai/v1"
    api_key: "${KIE_AI_API_KEY}"
  edge:
    kind: edge_tts                # free, no key
  local_embeddings:
    kind: local                   # in-process, no network
    module: "sentence_transformers"

# One registry of models — each declares WHICH capabilities it serves
models:
  # LLM tier
  scout-17b:
    provider: groq
    capability: llm
    id: "meta-llama/llama-4-scout-17b-16e-instruct"
    cost_in_per_mtok: 0.11
    cost_out_per_mtok: 0.34
    vision: true
    context_window: 131072
  minimax-m2.7:
    provider: openrouter
    capability: llm
    id: "minimax/minimax-m2.7"
    cost_in_per_mtok: 0.30
    cost_out_per_mtok: 1.20
    context_window: 196608
    notes: "Reasoning model — chain-of-thought"

  # Image
  z-image:
    provider: kie_ai
    capability: image
    id: "z-image-v1"
    cost_per_unit: 0.03
    unit: image
    aspect_ratios: ["1:1", "16:9", "9:16", "4:3", "3:4"]
    nsfw_filter: true
  nano-banana:
    provider: kie_ai
    capability: image
    id: "nano-banana"
    cost_per_unit: 0.02
    unit: image

  # Music
  suno-v5:
    provider: kie_ai
    capability: music
    id: "suno-v5.5"
    cost_per_unit: 0.15
    unit: track
    max_duration_seconds: 120

  # Voice STT
  whisper-large:
    provider: groq
    capability: stt
    id: "whisper-large-v3-turbo"
    cost_per_unit: 0.04
    unit: audio_minute
  whisper-local:
    provider: local_stt           # (define local_stt under providers if used)
    capability: stt
    id: "moonshine-base"
    cost_per_unit: 0.0
    unit: audio_minute

  # Voice TTS
  edge-aria:
    provider: edge
    capability: tts
    id: "en-US-AriaNeural"
    cost_per_unit: 0.0
    unit: character
  local-tts:
    provider: local_tts
    capability: tts
    id: "pocket-tts"
    cost_per_unit: 0.0
    unit: character

  # Embeddings
  nomic-embed:
    provider: local_embeddings
    capability: embedding
    id: "nomic-ai/nomic-embed-text-v1.5"
    cost_per_unit: 0.0
    unit: mtok

# Per-capability routing — each picks the tiering that fits
capabilities:
  llm:
    fast: scout-17b
    smart: minimax-m2.7
    background: scout-17b
    fallback: scout-17b
    auto_route: true
  image:
    default: z-image
    quick: nano-banana            # optional second tier — "cheap and fast"
  music:
    default: suno-v5
  stt:
    default: whisper-large
    local: whisper-local          # optional — use locally if network-offline
  tts:
    default: edge-aria
  embedding:
    default: nomic-embed
```

**Design choices worth calling out:**

1. **Each model declares exactly one `capability`.** Keeps the registry
   flat and the router simple. Multi-modal models are handled by creating
   multiple entries that share the same `provider` + `id` but differ in
   `capability`:
   ```yaml
   models:
     gemini-2.5-text:
       provider: google
       capability: llm
       id: "gemini-2.5-pro"
     gemini-2.5-image:
       provider: google
       capability: image
       id: "gemini-2.5-pro"
   ```
   This is easier than a `capabilities: [llm, image]` list field, which
   would force every capability to share the same cost/unit semantics.

2. **Tiering is per-capability.** LLM has `fast/smart/background/fallback`
   (four tiers, classifier-routed). Image has `default` + optional
   `quick`. Music has just `default`. Caps naturally to what each
   capability needs.

3. **`provider.kind` drives client selection.** Odigos already has an
   `LLMClient` for `openai_compatible`, `kie_ai` has its own REST shape,
   `edge_tts` uses the edge-tts library directly, local providers use
   in-process Python. The `kind` field tells the loader which client
   class to instantiate.

4. **Free/local providers are first-class.** `edge`, `local_embeddings`,
   `local_stt`, `local_tts` all fit the same schema — `cost_per_unit: 0.0`
   and a non-network `kind`. No special-casing.

---

## 4. Schema changes (code)

### `odigos/config.py`

Add new pydantic models alongside the existing `ProviderConfig` and
`ModelConfig`:

```python
class ProviderConfig(BaseModel):
    kind: Literal["openai_compatible", "kie_ai", "edge_tts",
                  "local", "local_stt", "local_tts"] = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    # Non-network providers may add extra fields (e.g. module path for local)

class ModelConfig(BaseModel):
    provider: str
    capability: Literal["llm", "image", "music", "stt", "tts", "embedding"]
    id: str
    # Cost model — LLM uses input/output split, others use per-unit
    cost_in_per_mtok: float = 0.0
    cost_out_per_mtok: float = 0.0
    cost_per_unit: float = 0.0
    unit: str = ""                # "mtok" / "image" / "track" / "audio_minute" / "character"
    # Capability-specific metadata — optional; tools consume what they need
    vision: bool = False
    context_window: int = 0
    aspect_ratios: list[str] = []
    max_duration_seconds: int = 0
    notes: str = ""

class CapabilityRouting(BaseModel):
    """Per-capability tier routing. Keys are tier names (fast/smart/default/etc)."""
    model_config = {"extra": "allow"}   # allow arbitrary tier names

class LLMRouting(CapabilityRouting):
    fast: str
    smart: str = ""
    background: str = ""
    fallback: str = ""
    auto_route: bool = True
    max_tokens: int = 2048
    temperature: float = 0.7
    # (merge in the existing LLMConfig fields)

class CapabilitiesConfig(BaseModel):
    llm: LLMRouting
    image: CapabilityRouting | None = None
    music: CapabilityRouting | None = None
    stt: CapabilityRouting | None = None
    tts: CapabilityRouting | None = None
    embedding: CapabilityRouting | None = None

class Settings(BaseSettings):
    # Existing fields unchanged
    providers: dict[str, ProviderConfig] = {}
    models: dict[str, ModelConfig] = {}
    capabilities: CapabilitiesConfig
    # ... rest unchanged
```

The existing `llm:` top-level block in config.yaml becomes
`capabilities.llm:`. Backwards-compat shim handles legacy flat `llm:`
during the migration window (see §7).

### `odigos/providers/registry.py` (new file)

A small registry that resolves `(capability, tier) → ModelConfig` and
instantiates the right client on demand. Replaces the ad-hoc provider
detection in each tool.

```python
class CapabilityRegistry:
    def __init__(self, providers, models, routing):
        self._providers = providers
        self._models = models
        self._routing = routing
        self._clients_by_kind = {
            "openai_compatible": OpenAICompatibleClient,
            "kie_ai": KieAIClient,
            "edge_tts": EdgeTTSClient,
            "local": LocalPythonClient,
            # ...
        }

    def resolve(self, capability: str, tier: str = "default") -> tuple[ModelConfig, Any]:
        routing = self._routing.get(capability)
        if not routing:
            raise RuntimeError(f"No routing configured for capability '{capability}'")
        alias = getattr(routing, tier, None) or routing.get("default")
        if not alias:
            raise RuntimeError(f"No '{tier}' tier configured for capability '{capability}'")
        model = self._models[alias]
        provider = self._providers[model.provider]
        client = self._clients_by_kind[provider.kind](provider)
        return model, client
```

`LLMClient` keeps its own resolution path (it has tier-dispatch +
intelligence routing on top of this). Image/music/stt/tts tools use
`CapabilityRegistry.resolve()` directly.

---

## 5. Tool refactor

For each tool that today has hardcoded provider logic:

### `odigos/tools/image_gen.py`

**Before:** constructs a Kie.ai HTTP client directly using
`settings.service_key("kie_ai")` and `settings.image_generation.*` fields.

**After:** constructor takes a `CapabilityRegistry`. On each call:
```python
tier = params.get("tier", "default")
model, client = self.registry.resolve("image", tier)
result = await client.generate_image(
    model_id=model.id,
    prompt=prompt,
    aspect_ratio=params.get("aspect_ratio", "1:1"),
    ...
)
# Report cost into BudgetTracker (dovetails with cost-tracking note)
await self.budget_tracker.record_tool_cost(
    cost_usd=model.cost_per_unit,
    source="image",
    conversation_id=...
)
```

Same pattern for `music_gen.py`, STT provider, TTS provider.

### `odigos/providers/kie_ai.py` (new)

Unified Kie.ai client for both image and music (Kie uses the same API
for both — `kie_ai_task` + polling). Replaces the separate image/music
client classes.

### `odigos/providers/edge_tts.py` (new)

Thin wrapper over `edge-tts` library. Synthesizes to WAV/MP3, returns
audio bytes.

### Dashboard (`dashboard/src/pages/settings/GeneralSettings.tsx`)

Today: Providers + Models + Routing sections, all LLM-scoped.

**After:** Providers section shows all providers regardless of what
capability they serve. Models section gains a **capability filter
dropdown** at the top (All / LLM / Image / Music / STT / TTS). Routing
section becomes **accordion of per-capability tier dropdowns** — LLM
gets fast/smart/background/fallback dropdowns, Image gets default/quick,
Music gets default, etc.

Same add/edit/delete/masked-key UX throughout. No new component patterns,
just extending the existing BYOK UI.

---

## 6. Migration strategy

Existing installs have the old shape. Two options:

### A. Auto-migrate on load (preferred)

In `odigos/config.py::load_settings()`, detect the legacy shape
(`image_generation:` or `music_generation:` or `voice:` at top level)
and auto-convert to the new shape before instantiating `Settings`:

```python
def _migrate_legacy_capabilities(yaml_config: dict) -> dict:
    # If already new-shape, no-op
    if "capabilities" in yaml_config:
        return yaml_config

    # Convert old blocks into providers + models + capabilities entries
    if "image_generation" in yaml_config:
        yaml_config.setdefault("providers", {}).setdefault("kie_ai", {
            "kind": "kie_ai",
            "base_url": "https://api.kie.ai/v1",
            "api_key": "${KIE_AI_API_KEY}",
        })
        yaml_config.setdefault("models", {})["z-image"] = {
            "provider": "kie_ai",
            "capability": "image",
            "id": "z-image-v1",
            "cost_per_unit": 0.03,
            "unit": "image",
            "aspect_ratios": yaml_config["image_generation"].get("aspect_ratios", ["1:1"]),
        }
        yaml_config.setdefault("capabilities", {}).setdefault("image", {})["default"] = "z-image"
        del yaml_config["image_generation"]
    # Similar for music_generation, voice.stt, voice.tts, embeddings
    return yaml_config
```

Operators see a one-time log warning ("Auto-migrated legacy
`image_generation:` block to unified capabilities config. Consider
running `install.sh` or editing `config.yaml` to the new shape.") Next
edit via dashboard writes it back in the new shape.

### B. Require `install.sh` re-run

Simpler but more disruptive — we'd have to tell every existing install
to `bash install.sh` again. Rejected.

Going with (A). Shim lives for 2 releases then gets removed.

---

## 7. Interaction with unified cost tracking

This spec and [`2026-04-16-unified-cost-tracking-note.md`](./2026-04-16-unified-cost-tracking-note.md)
share the same budget-tracker extension. Ship them together:

- Cost tracking adds `record_tool_cost()` + `tool_costs` table
- Capabilities config gives every paid tool a consistent way to emit
  cost (it knows the model's `cost_per_unit` + `unit`)
- Per-capability sub-caps (`image_monthly_cap_usd: 3.00`) naturally
  live in the `capabilities:` block

Order of implementation: capabilities config first (schema + registry
+ tool refactor), then cost tracking on top (tools call
`record_tool_cost()` with the model's declared cost). Trying to ship
cost tracking first would require threading capability-awareness through
existing tool classes twice.

---

## 8. Implementation order

1. **Schema + types** (`odigos/config.py`) — new pydantic models, loader
   migration shim, validator
2. **CapabilityRegistry** (`odigos/providers/registry.py`) — resolution
   + client instantiation
3. **Refactor existing LLMClient** to consume the registry for its
   routing (instead of its own `_providers` / `_models` dicts). Keep
   intelligence-tier routing logic.
4. **Kie.ai provider client** (`odigos/providers/kie_ai.py`) — shared
   image + music HTTP client with polling
5. **Refactor `ImageGenTool` + `MusicGenTool`** to use registry
6. **Refactor STT + TTS providers** to use registry
7. **Cost tracking** (`BudgetTracker.record_tool_cost()`, migration 013,
   per-tool cost reporters)
8. **Dashboard UI** — capability filter on models table, accordion on
   routing section
9. **Install scripts** — `install.sh`, `install-bare.sh`,
   `fresh-install.sh`, `config.yaml.example` — all emit the new shape
10. **Tests** — unit tests on registry resolution, migration shim,
    per-capability routing; integration tests for image + music + voice
    calls through the new path
11. **Deprecation log** — warn on legacy shape, plan removal in `+2`
    releases

Estimated: ~3 focused days end-to-end. Day 1: schema + registry + LLM
refactor. Day 2: tool refactors + Kie.ai client + cost tracking. Day 3:
dashboard UI + install scripts + tests + migration verification on a
staging install.

---

## 9. Open questions

- **Multi-modal model representation.** Gemini 2.5 handles text + image
  + audio through one endpoint. My proposal is to model this as three
  separate `models:` entries sharing a `provider` and `id`. Alternative:
  one entry with `capabilities: [llm, image, audio]` list. The list
  form is more compact but forces every capability to share cost fields
  (cost_in_per_mtok vs cost_per_unit — incompatible units). **Going
  with separate entries** unless a concrete multi-modal use case
  requires otherwise.

- **Should `BudgetTracker` support per-capability sub-caps?** Config
  field `capabilities.image.monthly_cap_usd: 3.00` would let Pro tier
  cap image gen separately from the overall budget. Adds complexity;
  maybe YAGNI until someone asks. **Initial version: just total budget,
  revisit if tiers demand separation.**

- **BYOK for voice STT / TTS specifically.** If a user brings their own
  OpenAI key and wants to use `whisper-1` for STT, we need to route
  through an `openai_compatible` STT endpoint. Does OpenAI's STT use
  the same `/v1/audio/transcriptions` path under an `openai_compatible`
  provider? **Probably yes** — confirm during implementation.

- **Edge TTS voice catalog** — today `voice.tts_voice` is a free-form
  string. Under the new schema it's the model's `id`. Do we need a
  selectable voice picker in the dashboard? Edge has hundreds of
  voices. **Initial version: free-form text input, revisit with a
  dropdown + preview if users complain.**

- **Embeddings routing.** Less critical — most users run nomic-embed
  locally. But BYOK embeddings (OpenAI ada-002, Cohere embed, etc.)
  would fit the same schema. **Include in v1 but ship behind a feature
  flag** if it turns out the embedding-index rebuild cost makes
  switching providers impractical for existing installs.

---

## 10. Disposition

Not blocking current testers (HomeRun, Sales, Honey, etc). Ship together
with unified cost tracking before opening hosted Starter/Pro/BYOK
signups to paying customers — this is the pair of changes that makes
Pro tier genuinely defensible ("image and music work and are tracked
against your budget") and makes BYOK a truly universal story ("bring
your own anything").

Tags: `hosted-readiness`, `byok`, `refactor`, `pre-launch`.
