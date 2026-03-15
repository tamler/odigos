# Phase 5 Completion — Design

**Goal:** Finish Phase 5 (Voice & Polish) by automating voice plugin installation and extracting all hardcoded prompts into editable files with a clean directory structure.

---

## Part 1: Voice Install Script

### `install-voice.sh` (standalone)

```bash
#!/usr/bin/env bash
# Installs TTS/STT dependencies and enables voice in config.
# Can be run during initial install or anytime after.
```

**What it does:**
1. Detects environment: Docker (no venv) or bare metal (`.venv/` exists)
2. Installs packages: `pip install moonshine-voice pocket-tts scipy`
   - In Docker: `pip install` directly
   - Bare metal: `.venv/bin/pip install`
3. Downloads Moonshine English model: `python -m moonshine_voice.download --language en`
4. Updates `config.yaml`: sets `stt.enabled: true`, `tts.enabled: true`
5. Prints success message with available voice options

### Install script integration

**`install.sh`** — after LLM provider setup, before Docker build:
```
Enable voice (text-to-speech and speech-to-text)? [y/N]
```
If yes, runs `./install-voice.sh`.

**`install-bare.sh`** — same prompt, same call.

---

## Part 2: Prompt File Reorganization

### New directory structure

```
data/
  agent/                         # Agent identity and behavior (main system prompt)
    identity.md                  # Who the agent is (from prompt_sections/identity.md)
    voice.md                     # Communication style (from prompt_sections/voice.md)
    meta.md                      # Self-improvement (from prompt_sections/meta.md)
    entity_extraction.md         # NEW — from ENTITY_EXTRACTION_INSTRUCTION constant
    correction_detection.md      # NEW — from CORRECTION_DETECTION_INSTRUCTION constant
    skill_creation.md            # NEW — from SKILL_CREATION_INSTRUCTION constant
  prompts/                       # Internal infrastructure prompts (used by subsystems)
    summarizer.md                # NEW — from STRUCTURED_COMPACTION_PROMPT
    evaluator_rubric.md          # NEW — from evaluator._get_or_generate_rubric prompt
    evaluator_scoring.md         # NEW — from evaluator._score_against_rubric prompt
    strategist.md                # NEW — from strategist._build_analysis_prompt
    heartbeat_idle.md            # NEW — from heartbeat idle think prompt
    subagent.md                  # NEW — from subagent system prompt
    spawner_adapt.md             # NEW — from spawner._adapt_template prompt
```

All files in `data/agent/` use YAML frontmatter (priority, always_include) for the checkpoint/trial system. Files in `data/prompts/` are plain text with optional `{variable}` placeholders.

### What gets deleted

| File/Code | Reason |
|-----------|--------|
| `data/personality.yaml` | Redundant — identity.md and voice.md are the source of truth |
| `data/prompt_sections/` | Moved to `data/agent/` |
| `odigos/personality/loader.py` | `Personality` dataclass, `VoiceConfig`, `IdentityConfig`, `load_personality()` — all unused once prompt_builder simplified |
| `odigos/config.py` `PersonalityConfig` | No longer needed (`path: str` field) |
| `prompt_builder.py` `_build_identity_section()` | Replaced by identity.md file |
| `prompt_builder.py` `_build_voice_section()` | Replaced by voice.md file |
| `prompt_builder.py` 3 `*_INSTRUCTION` constants | Moved to files |
| `prompt_builder.py` legacy `else` branch | No more fallback — sections always come from files |

### What gets modified

**`odigos/personality/prompt_builder.py`** — simplified to:
```python
def build_system_prompt(
    sections: list[PromptSection],
    memory_context: str = "",
    skill_catalog: str = "",
    corrections_context: str = "",
    agent_name: str = "",
) -> str:
    parts = []
    for section in sorted(sections, key=lambda s: s.priority):
        content = section.content.replace("{name}", agent_name)
        parts.append(content)

    if memory_context:
        parts.append(memory_context)
    if skill_catalog:
        parts.append(skill_catalog)
    if corrections_context:
        parts.append(corrections_context)

    return "\n\n".join(parts)
```

No more `personality` parameter. No more constants. No more legacy branch.

**`odigos/core/context.py` (ContextAssembler)**:
- Remove `personality_path` parameter
- Remove `load_personality()` call
- Always load sections via checkpoint_manager (which uses SectionRegistry)
- If no checkpoint_manager, create a standalone SectionRegistry for `data/agent/`
- Pass `agent_name` from config to `build_system_prompt()`

**`odigos/personality/section_registry.py`**:
- Update default path references from `data/prompt_sections` to `data/agent`

**`odigos/core/checkpoint.py`**:
- Update `sections_dir` default to `data/agent`
- Remove `personality_path` parameter and personality snapshotting (or snapshot agent dir instead)

**`odigos/core/agent.py`**:
- Remove `personality_path` parameter, pass through to ContextAssembler without it

**`odigos/main.py`**:
- Change `sections_dir="data/prompt_sections"` to `sections_dir="data/agent"`
- Remove `personality_path=settings.personality.path` references
- Remove `PersonalityConfig` from settings

**Infrastructure prompt loading** — each subsystem gets a simple loader:

```python
from pathlib import Path

def _load_prompt(name: str, fallback: str) -> str:
    """Load a prompt from data/prompts/{name}. Falls back to hardcoded default."""
    path = Path(f"data/prompts/{name}")
    if path.exists():
        return path.read_text().strip()
    return fallback
```

Modified files:
- `odigos/memory/summarizer.py` — `_load_prompt("summarizer.md", STRUCTURED_COMPACTION_PROMPT)`
- `odigos/core/evaluator.py` — `_load_prompt("evaluator_rubric.md", ...)` and `_load_prompt("evaluator_scoring.md", ...)`
- `odigos/core/strategist.py` — `_load_prompt("strategist.md", ...)` with `.format()` for template vars
- `odigos/core/heartbeat.py` — `_load_prompt("heartbeat_idle.md", ...)`
- `odigos/core/subagent.py` — `_load_prompt("subagent.md", ...)`
- `odigos/core/spawner.py` — `_load_prompt("spawner_adapt.md", ...)`

Constants remain in each file as fallback defaults for first-run before files exist.

### Shared prompt loader

To avoid duplicating the `_load_prompt` function in 6 files, create:

**`odigos/core/prompt_loader.py`**:
```python
"""Load editable prompt files from data/prompts/ with hardcoded fallbacks."""
from pathlib import Path

_cache: dict[str, tuple[float, str]] = {}

def load_prompt(name: str, fallback: str) -> str:
    """Load prompt from data/prompts/{name}. Cached by mtime. Falls back if missing."""
    path = Path(f"data/prompts/{name}")
    if not path.exists():
        return fallback
    mtime = path.stat().st_mtime
    cached = _cache.get(name)
    if cached and cached[0] == mtime:
        return cached[1]
    content = path.read_text().strip()
    _cache[name] = (mtime, content)
    return content
```

### API Endpoints

**`GET /api/prompts`** — list all prompt files from both directories:
```json
[
  {"name": "identity", "directory": "agent", "path": "data/agent/identity.md"},
  {"name": "summarizer", "directory": "prompts", "path": "data/prompts/summarizer.md"},
  ...
]
```

**`GET /api/prompts/{directory}/{name}`** — read a prompt file's content
**`PUT /api/prompts/{directory}/{name}`** — update a prompt file's content

No dashboard page for now — API-only. The agent can use these endpoints (or file tools) to modify its own prompts.

### Migration

On first startup after this change:
- If `data/prompt_sections/` exists and `data/agent/` does not, copy files over
- If `data/personality.yaml` exists, log a deprecation warning and ignore it
- The install scripts create `data/agent/` and `data/prompts/` with default content

---

## Files to Create/Modify

| File | Change |
|------|--------|
| `install-voice.sh` | New — voice dependency installer |
| `install.sh` | Modify — add voice prompt |
| `install-bare.sh` | Modify — add voice prompt |
| `data/agent/identity.md` | Move from prompt_sections |
| `data/agent/voice.md` | Move from prompt_sections |
| `data/agent/meta.md` | Move from prompt_sections |
| `data/agent/entity_extraction.md` | New from constant |
| `data/agent/correction_detection.md` | New from constant |
| `data/agent/skill_creation.md` | New from constant |
| `data/prompts/summarizer.md` | New from constant |
| `data/prompts/evaluator_rubric.md` | New from inline |
| `data/prompts/evaluator_scoring.md` | New from inline |
| `data/prompts/strategist.md` | New from inline |
| `data/prompts/heartbeat_idle.md` | New from inline |
| `data/prompts/subagent.md` | New from inline |
| `data/prompts/spawner_adapt.md` | New from inline |
| `odigos/core/prompt_loader.py` | New — shared loader |
| `odigos/personality/prompt_builder.py` | Simplify — remove constants, legacy, personality param |
| `odigos/personality/loader.py` | Delete |
| `odigos/personality/section_registry.py` | Update path default |
| `odigos/core/context.py` | Remove personality_path, always use sections |
| `odigos/core/agent.py` | Remove personality_path param |
| `odigos/core/checkpoint.py` | Update sections_dir, remove personality |
| `odigos/core/evaluator.py` | Use load_prompt |
| `odigos/core/strategist.py` | Use load_prompt |
| `odigos/core/heartbeat.py` | Use load_prompt |
| `odigos/core/subagent.py` | Use load_prompt |
| `odigos/core/spawner.py` | Use load_prompt |
| `odigos/memory/summarizer.py` | Use load_prompt |
| `odigos/config.py` | Remove PersonalityConfig |
| `odigos/main.py` | Update paths, remove personality refs |
| `odigos/api/prompts.py` | New — API for listing/reading/editing prompts |
| Tests | Update all tests referencing personality/prompt_sections |
