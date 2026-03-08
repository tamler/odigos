# Self-Skill-Building Design

**Date:** 2026-03-08
**Status:** Approved
**Phase:** 3, item #3

## Context

The agent has a working skill system: a registry loads `.md` files with YAML frontmatter, `ActivateSkillTool` loads skill bodies on demand, and the executor injects them as system messages. `SkillRegistry.create()` already exists for programmatic creation. What's missing is exposing skill creation and modification to the agent as tools so it can autonomously build skills over time.

## Decisions

1. **Trigger:** LLM-driven. The agent uses its existing memory (action_log, conversation summaries, corrections) and the heartbeat loop to notice recurring patterns and decide when to create skills. No separate pattern detection machinery.
2. **Activation:** Immediate. Newly created skills enter the live catalog right away. The agent mentions the creation in its response so the owner is aware.
3. **Mutations:** Create and update only. The agent cannot modify built-in skills (the 5 shipped with the system). Deletion can be added later if needed.
4. **Tool shape:** Single tool call with all fields -- `create_skill(name, description, instructions, tools?, complexity?)`. The agent can call `update_skill` later to refine.

## Components

### 1. Skill dataclass changes

Add `builtin: bool = False` to the `Skill` dataclass. `load_all()` sets `builtin=True` on every skill loaded at startup. `create()` sets `builtin=False`.

Store `skills_dir` as an instance attribute on `SkillRegistry` during `load_all()` so `create()` and `update()` don't need it passed each time.

### 2. SkillRegistry.update()

New method. Parameters: `name`, plus optional `description`, `instructions`, `tools`, `complexity`. Reads the existing skill, merges provided fields, rewrites the `.md` file on disk, updates the in-memory `_skills` dict. Raises error if skill doesn't exist or is built-in.

### 3. Tools

Two tools in `odigos/tools/skill_manage.py`:

**CreateSkillTool:**
- Parameters: `name` (str), `description` (str), `instructions` (str), `tools` (list[str], optional), `complexity` (str, default "standard")
- Calls `SkillRegistry.create()`
- Returns confirmation message with skill name

**UpdateSkillTool:**
- Parameters: `name` (str), `description` (str, optional), `instructions` (str, optional), `tools` (list[str], optional), `complexity` (str, optional)
- Calls `SkillRegistry.update()`
- Returns confirmation message
- Rejects updates to built-in skills

### 4. System prompt guidance

New constant `SKILL_CREATION_INSTRUCTION` in `prompt_builder.py`, always injected after the skill catalog section:

> You can create reusable skills for task types you encounter repeatedly. A skill is a set of instructions that guide your behavior for a specific kind of task. Create a skill when you notice you've handled the same type of request multiple times with similar steps. Use `update_skill` to refine a skill you created when you receive corrections or learn better approaches. When you create or update a skill, mention it briefly in your response so the user is aware.

### 5. Wiring in main.py

Import and register both tools alongside the existing `ActivateSkillTool`. Both receive the `skill_registry` instance.

## Testing

- **TestCreateSkillTool:** Creates skill on disk, registers in live catalog, `builtin=False`.
- **TestUpdateSkillTool:** Modifies file and in-memory registry. Rejects built-in skills. Handles partial updates.
- **TestSkillRegistryBuiltinFlag:** `load_all()` sets `builtin=True`, `create()` sets `builtin=False`.
- **TestSkillRegistryUpdate:** Unit tests for the new `.update()` method.

## Future optimization

Dynamic system prompt assembly -- classify instruction blocks as "always" vs "when relevant" and let ContextAssembler decide per-turn which to include. Captured in `docs/ROADMAP.md`.
