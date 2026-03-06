# Skill Integration Design

**Goal:** Wire the existing SkillRegistry into the ReAct loop so the LLM sees available skills and can activate them on demand.

## Approach

Three-level progressive disclosure, aligned with the architecture doc:

1. **Level 1: Catalog** (always in context) — Skill names + descriptions injected into the system prompt. ~100 tokens for 3 skills, scales linearly. The LLM sees what's available on every turn.

2. **Level 2: Body** (on demand) — New `activate_skill` tool. When the LLM decides it needs a skill's detailed instructions, it calls `activate_skill(name="research-deep-dive")`. The executor injects the full SKILL.md body as a **system message** (not a tool result) so the LLM treats it as instructions, not data.

3. **Level 3: Bundled resources** — Future work (Phase 3). Scripts and references loaded from within skill execution.

## Assembly Order

`ContextAssembler.build()` produces:

```
[system prompt + skill catalog] + [conversation summaries] + [recent history] + [current message]
```

The skill catalog is appended to the system prompt as a new section in the prompt builder.

## activate_skill Tool

- Registered like any other tool in the `ToolRegistry`
- Takes `name: str` parameter
- Validates skill exists, returns confirmation message as tool result
- Executor detects `activate_skill` success and also injects a system message:
  `[Active skill instructions]:\n\n<full SKILL.md body>`
- The system message is appended after all tool results in that turn

## Active Skill Tracking

The executor tracks:
- `_active_skill_name: str | None` — set when `activate_skill` succeeds
- `_active_skill_tools: set[str]` — the skill's declared tool list
- Reset at the start of each `execute()` call

## Tool Mismatch Logging

When a tool is called during an active skill:
- If the tool name is NOT in the skill's declared `tools` list, log a mismatch to `action_log`
- Advisory only — the tool still executes normally
- `action_log.details_json` includes `{"skill_mismatch": true, "active_skill": "...", "expected_tools": [...]}`
- Useful signal for future enforcement

## Cost Tagging

When a skill is active:
- All `action_log` entries include `{"active_skill": "research-deep-dive"}` in details_json
- Enables cost-by-skill queries: `SELECT active_skill, COUNT(*) FROM action_log GROUP BY active_skill`
- No new tables or columns needed

## Files

- `odigos/personality/prompt_builder.py` — add skill catalog section
- `odigos/tools/skill_tool.py` — new `ActivateSkillTool`
- `odigos/core/executor.py` — active skill tracking, system message injection, mismatch logging
- `odigos/core/context.py` — pass skill catalog to prompt builder
- `odigos/core/agent.py` — pass skill_registry to context assembler
- `odigos/main.py` — register ActivateSkillTool

## Not Doing

- Tool restriction enforcement (advisory only)
- Auto-skill-detection / classifier
- Bundled scripts (Level 3)
- Agent self-skill-creation (Phase 3)
- Separate cost_log table (action_log is sufficient)
