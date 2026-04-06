# Prompt Assembly Redesign

**Date:** 2026-04-06
**Status:** Approved
**Goal:** Replace the dump-everything prompt builder with a planner-driven assembler that builds minimal, query-specific system prompts.

## Problem

The current system prompt is 13,626 chars for every request regardless of what the user asks. Skills catalogs, image guides, and meta-instructions are injected into every turn. The `always_include` flag was dead code. Context rot degrades tool calling — the model ignores `find_tools` because it's buried in noise.

Research confirms: model performance degrades as system prompt grows, especially for tool calling. Anthropic's tool_search approach uses minimal prompts + deferred tool loading.

## Architecture

### 1. Query Planner (enhanced classifier)

The existing classifier already makes a cheap LLM call per request. Enhance its output from a classification string to a full assembly plan:

**Current output:**
```json
{"classification": "standard", "confidence": 0.9, "entities": [], "search_queries": []}
```

**New output:**
```json
{
  "classification": "creative",
  "confidence": 0.9,
  "intent": "generate_music",
  "tool_hint": "generate_music",
  "needs": {
    "rag": false,
    "user_profile": false,
    "user_facts": false,
    "history": false,
    "experiences": true
  },
  "search_queries": [],
  "response_style": "brief",
  "complexity": "single_tool"
}
```

**Fields:**
- `intent`: what the user wants to happen — maps to a tool or action
- `tool_hint`: the most likely tool name. The assembler pre-loads its schema alongside find_tools, eliminating the discovery round trip.
- `needs`: which context sections to load. The assembler only loads what's flagged true.
- `response_style`: "brief", "detailed", "step_by_step" — controls conciseness
- `complexity`: "single_tool", "multi_step", "conversation" — informs budget allocation

**Tool catalog in classifier prompt:** The classifier sees a lightweight index of all registered tools (~50 tokens): tool name + one-line description. This is how it produces accurate `tool_hint` values. The catalog is built from the registry at startup and cached.

Example catalog (included in classifier prompt):
```
generate_music: create music from lyrics/description
generate_image: create image from text description  
run_code: execute python/shell code
manage_files: read/write/list files
send_notification: send notification to user
create_artifact: create downloadable file
search_workspace: search notebooks/boards/conversations
activate_skill: load a skill's instructions
...
```

### 2. Prompt Assembler (rewritten build())

The assembler is a budget-filling executor. It reads the planner output and only loads what's needed.

**Always loaded (~250 chars, non-negotiable):**
- Identity: "You are {name}. {personality}." (~100 chars)
- Tool instruction: "Use find_tools to discover capabilities. Call it first when asked to do something. Do not say 'I can't' without checking." (~150 chars)

**Loaded only when `plan.needs` flags true:**
- `rag`: calls `memory_manager.recall(search_queries or message)` 
- `user_profile`: loads structured user profile
- `user_facts`: loads explicit facts
- `history`: loads conversation history / summaries
- `experiences`: loads XSkill tactical lessons (filtered by tool_hint if available)

**Budget enforcement:** Total system prompt capped at configurable limit (default 2000 tokens). Sections loaded in priority order: identity → tool instruction → experiences → user_facts → user_profile → RAG → history. If budget runs out, remaining sections skipped.

**No parallel loading of everything.** Only load what the plan says. No pruning step — nothing unnecessary was loaded in the first place.

```python
async def build(self, conversation_id, message, plan):
    parts = []
    budget = self.max_prompt_tokens  # default 2000
    
    # Always: identity + tool instruction
    parts.append(self.identity)
    parts.append(self.tool_instruction)
    budget -= estimate_tokens(parts)
    
    # Only what the planner says
    if plan.needs.rag and budget > 0:
        rag = await self.memory_manager.recall(plan.search_queries or [message])
        parts.append(truncate_to_budget(rag, budget))
        budget -= estimate_tokens(rag)
    
    if plan.needs.user_profile and budget > 0:
        profile = await self._load_user_profile()
        parts.append(truncate_to_budget(profile, budget))
        budget -= estimate_tokens(profile)
    
    # ... same pattern for user_facts, history, experiences
    
    # Build tool list
    tools = [self.find_tools_schema]
    if plan.tool_hint:
        hinted = self.tool_registry.get(plan.tool_hint)
        if hinted:
            tools.append(self.tool_registry._tool_to_def(hinted))
    
    system_prompt = build_system_prompt(parts)
    return [{"role": "system", "content": system_prompt}, ...], tools
```

### 3. Tool List Assembly

**Always included:** `find_tools` — the discovery mechanism

**Included when hinted:** The tool from `plan.tool_hint`. If the classifier identifies `generate_music`, its full schema is included alongside find_tools. The model can call it immediately without a discovery round trip.

**Dynamic expansion preserved:** After find_tools returns results, the executor still expands discovered tool schemas in the same turn (existing behavior, unchanged).

**Fallback:** If tool_hint is wrong, the model has find_tools and discovers the right tool. Cost: ~100 wasted tokens for the wrong schema. Acceptable.

### 4. What Happens to Existing Sections

| Current | Disposition |
|---------|------------|
| `identity.md` | Stays — the one permanent section |
| `capabilities.md` | Replaced by hardcoded tool instruction constant |
| `voice.md` | Loaded conditionally when voice mode active |
| `meta.md` | Removed from prompt — heartbeat/evolution concern |
| `query handling.md` | Removed — planner handles routing |
| `skill_creation.md` | Removed — evolution engine concern |
| `classification_rules.md` | Already excluded |
| `routing_rules.md` | Already excluded. Replaced by planner needs flags |
| Skills catalog (5K) | Already removed. Discoverable via find_tools |
| Image prompt guide (3K) | Already removed. Injected by tool when activated |
| Error hints | Loaded when `needs.experiences` true |
| Corrections context | Loaded when `needs.user_profile` true |
| Page context | Loaded when request comes from specific page (detected by assembler) |

### 5. Fallback Behavior

**Classifier fails/times out:** Default plan: identity + tool instruction + find_tools. No context sections. The agent can still discover tools and respond.

**tool_hint wrong:** Agent has find_tools, calls it. Hinted tool unused. ~100 wasted tokens.

**Budget exceeded:** Sections loaded in priority order, stopped when budget runs out. Agent still functions with less context.

**New tool added:** Tool catalog in classifier prompt updates automatically from registry on restart. No manual maintenance.

### 6. Example: "Make me a song about cats"

**Classifier returns:**
```json
{
  "classification": "creative",
  "intent": "generate_music",
  "tool_hint": "generate_music",
  "needs": {"rag": false, "user_profile": false, "user_facts": false, "history": false, "experiences": true},
  "response_style": "brief",
  "complexity": "single_tool"
}
```

**Assembler builds:**
```
System prompt: "You are Bob. You're helpful and direct.
Use find_tools to discover capabilities. Call it when asked to do something."
+ XSkill experience for generate_music (if any)
```
~300 chars system prompt.

**Tool list:** `[find_tools, generate_music]`

**Result:** Model sees generate_music in its tool list, calls it immediately. No find_tools needed. No 13K of noise.

### 7. Example: "What did I say about Python yesterday?"

**Classifier returns:**
```json
{
  "classification": "document_query",
  "intent": "recall_conversation",
  "tool_hint": "search_workspace",
  "needs": {"rag": true, "user_profile": false, "user_facts": false, "history": true, "experiences": false},
  "search_queries": ["Python", "yesterday"],
  "response_style": "detailed",
  "complexity": "conversation"
}
```

**Assembler builds:**
```
System prompt: identity + tool instruction + RAG results for "Python yesterday" + recent conversation history
```
~1500 chars system prompt.

**Tool list:** `[find_tools, search_workspace]`

## File Changes

| File | Change |
|------|--------|
| `odigos/core/classifier.py` | Enhanced output schema. Tool catalog in classifier prompt. |
| `odigos/core/context.py` | Rewrite `build()` — planner-driven, budget-enforced. Remove parallel-everything pattern. Remove pruning. |
| `odigos/core/executor.py` | Pass planner output to assembler. Build tool list from tool_hint + find_tools. |
| `odigos/personality/prompt_builder.py` | Simplify — concatenate identity + tool instruction + selected sections. |
| `odigos/personality/section_registry.py` | Simplified — loads identity only. Remove always_include flag. |
| `data/agent/capabilities.md` | Remove — replaced by constant |
| `data/agent/meta.md` | Remove from prompt pipeline |
| `data/agent/query handling.md` | Remove from prompt pipeline |
| `data/agent/skill_creation.md` | Remove from prompt pipeline |
| `data/prompts/classifier.md` | Updated with tool catalog and new output schema |
| `odigos/core/relevance.py` | Remove — no more post-hoc pruning |

## What Doesn't Change

- Tool registry, find_tools, tool execution
- Memory manager (RAG recall) — called conditionally
- XSkill experience store — loaded when planner flags it
- Heartbeat, background tasks, backgroundable tools
- Frontend
- Database schema
- Callback system
