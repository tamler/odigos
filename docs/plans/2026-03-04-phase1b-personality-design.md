# Phase 1b Design: Personality

**Date:** 2026-03-04
**Status:** Approved
**Milestone:** "It sounds like my assistant" -- agent has a configurable voice driven by personality.yaml

---

## Scope

Voice and tone only. A `data/personality.yaml` file controls how the agent speaks. A structured prompt builder composes the system prompt from personality traits, memories, and entity extraction instructions. Hot reload on every message (re-read YAML, no restart needed).

Deferred to later phases: initiative levels, permission boundaries, daily rhythm/DND schedules, proactive behavior.

### Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Scope | Voice & tone only | Get personality working and visible before adding behavioral complexity. |
| Config location | `data/personality.yaml` | Separate from deployment config. Agent identity, not infra settings. |
| Prompt assembly | Structured prompt builder | Composable sections, reusable pattern for future prompt needs (tools, corrections, etc). |
| Hot reload | Yes, re-read on every message | Trivial cost (one small YAML read), immediate feedback when editing personality. |
| Default personality | Ships with sensible defaults | Works out of the box even without personality.yaml. |

---

## personality.yaml Format

```yaml
name: "Odigos"

voice:
  tone: "direct, warm, slightly informal"
  verbosity: "concise by default, detailed when asked"
  humor: "dry, occasional, never forced"
  formality: "casual with owner, professional with others"

identity:
  role: "personal assistant and research partner"
  relationship: "trusted aide — not a servant, not a peer"
  first_person: true
  expresses_uncertainty: true
  expresses_opinions: true
```

All fields have defaults. Missing file or missing fields fall back gracefully.

---

## New Modules

```
odigos/
  personality/
    __init__.py
    loader.py           # Reads personality.yaml, returns Personality dataclass
    prompt_builder.py   # Composes system prompt from sections
```

---

## Personality Loader (personality/loader.py)

- `load(path) -> Personality`: Read YAML file, return a `Personality` dataclass
- If file doesn't exist, return defaults
- If fields are missing, fill with defaults
- Called on every message (hot reload), no caching needed
- `Personality` dataclass has: name, voice (tone, verbosity, humor, formality), identity (role, relationship, first_person, expresses_uncertainty, expresses_opinions)

---

## Prompt Builder (personality/prompt_builder.py)

Structured prompt composition. Takes personality + optional memory context and returns a complete system prompt string.

Sections composed in order:
1. **Identity** -- who the agent is, its name, role, relationship
2. **Voice guidelines** -- tone, verbosity, humor, formality directives
3. **Memory context** -- injected from memory_manager.recall() (if any)
4. **Entity extraction instruction** -- the `<!--entities-->` block instruction

Each section is a function that returns a string (or empty string if not applicable). The builder joins non-empty sections with double newlines.

This replaces the hardcoded `SYSTEM_PROMPT_TEMPLATE` in context.py.

---

## Integration Points

- **context.py**: Imports prompt builder. Instead of formatting a hardcoded template, calls `prompt_builder.build_system_prompt(personality, memory_context)`. Loads personality via `loader.load(path)` on each `build()` call.
- **config.yaml**: Add `personality: path: "data/personality.yaml"` setting with default.
- **config.py**: Add `PersonalityConfig` with `path` field.
- **data/personality.yaml**: Default personality file created as part of the project.

What does NOT change: memory manager, reflector, agent.py, main.py, executor.py.
