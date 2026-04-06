# Prompt Assembly Redesign

**Date:** 2026-04-06
**Status:** Approved
**Goal:** Replace the dump-everything prompt builder with a planner-driven assembler that builds minimal, query-specific system prompts.

## Problem

The current system prompt is 13,626 chars for every request regardless of what the user asks. Skills catalogs, image guides, and meta-instructions are injected into every turn. The `always_include` flag was dead code. Context rot degrades tool calling — the model ignores `find_tools` because it's buried in noise.

Research confirms: model performance degrades as system prompt grows, especially for tool calling. Anthropic's tool_search approach uses minimal prompts + deferred tool loading.

## Architecture

### 1. Query Planner (enhanced classifier)

The existing classifier already makes a cheap LLM call per request. Enhance its output from a classification string to a full assembly plan.

**Classifier input:** The current user message PLUS the last 2-3 turns from the WebSocket session (not from the database — no DB call needed). This gives the classifier conversational context so "Change the color" or "Do it again" can be correctly planned.

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
- `response_style`: "brief", "detailed", "step_by_step" — controls conciseness. Injected as the LAST system content (right before user message) for maximum adherence.
- `complexity`: "single_tool", "multi_step", "conversation" — informs budget allocation

**Tool catalog in classifier prompt:** The classifier sees a lightweight index of all registered tools (~50 tokens): tool name + one-line description. Built from the registry at startup and cached. When the tool count exceeds ~75, switch to category-based catalog (e.g., "media_gen: image/music/audio generation tools") with primary tools listed per category.

Example catalog:
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

**Implicit dependencies:** When `needs.rag` is true, the assembler also loads the last 2 turns for entity resolution (pronouns like "he", "that document"). This is a dependency of RAG, not a separate flag — the planner doesn't need to know about it.

### 2. Prompt Assembler (rewritten build())

The assembler is a budget-filling executor. It reads the planner output and only loads what's needed.

**Always loaded (~300 chars, non-negotiable):**
- Identity: "You are {name}. {personality}." (~100 chars)
- Tool instruction: "You can manage workspaces, generate media, execute code, and more. Use find_tools to discover specific capabilities. Call it when asked to do something. Do not say 'I can't' without checking." (~200 chars). Includes high-level domain hints so the model knows what to search for when tool_hint fails.

**Loaded only when `plan.needs` flags true:**
- `rag`: calls `memory_manager.recall(search_queries or message)`. Also loads last 2 turns for entity resolution.
- `user_profile`: loads structured user profile
- `user_facts`: loads explicit facts
- `history`: loads full conversation history / summaries
- `experiences`: loads XSkill tactical lessons (filtered by tool_hint if available)

**Budget enforcement:** Total system prompt capped at configurable limit (default 2000 tokens). Sections loaded in priority order: identity → tool instruction → experiences → user_facts → user_profile → RAG → history. If budget runs out, remaining sections skipped.

**Response style:** `plan.response_style` is injected as the LAST content in the system prompt, right before the user message. This position gets highest model attention.

**No parallel loading of everything.** Only load what the plan says. No pruning step — nothing unnecessary was loaded in the first place.

```python
async def build(self, conversation_id, message, plan, recent_turns=None):
    parts = []
    budget = self.max_prompt_tokens  # default 2000
    
    # Always: identity + tool instruction
    parts.append(self.identity)
    parts.append(self.tool_instruction)
    budget -= estimate_tokens(parts)
    
    # Only what the planner says
    if plan.needs.experiences and budget > 0:
        exp = await self._load_experiences(plan.tool_hint)
        parts.append(truncate_to_budget(exp, budget))
        budget -= estimate_tokens(exp)
    
    if plan.needs.user_facts and budget > 0:
        facts = await self._load_user_facts()
        parts.append(truncate_to_budget(facts, budget))
        budget -= estimate_tokens(facts)
    
    if plan.needs.user_profile and budget > 0:
        profile = await self._load_user_profile()
        parts.append(truncate_to_budget(profile, budget))
        budget -= estimate_tokens(profile)
    
    if plan.needs.rag and budget > 0:
        rag = await self.memory_manager.recall(plan.search_queries or [message])
        parts.append(truncate_to_budget(rag, budget))
        budget -= estimate_tokens(rag)
        # Implicit dependency: load last 2 turns for entity resolution
        if recent_turns:
            parts.append(format_recent_turns(recent_turns[-2:]))
    
    if plan.needs.history and budget > 0:
        history = await self._load_history(conversation_id)
        parts.append(truncate_to_budget(history, budget))
        budget -= estimate_tokens(history)
    
    # Response style as last instruction (highest attention position)
    if plan.response_style == "brief":
        parts.append("Be concise. Lead with the answer.")
    elif plan.response_style == "step_by_step":
        parts.append("Think step by step. Show your reasoning.")
    
    # Build tool list
    tools = [self.find_tools_schema]
    if plan.tool_hint:
        hinted = self.tool_registry.get(plan.tool_hint)
        if hinted:
            tools.append(self.tool_registry._tool_to_def(hinted))
    
    system_prompt = "\n\n".join(parts)
    return [{"role": "system", "content": system_prompt}, ...], tools
```

### 3. Tool List Assembly

**Always included:** `find_tools` — the discovery mechanism

**Included when hinted:** The tool from `plan.tool_hint`. If the classifier identifies `generate_music`, its full schema is included alongside find_tools. The model can call it immediately without a discovery round trip.

**Dynamic expansion preserved:** After find_tools returns results, the executor still expands discovered tool schemas in the same turn (existing behavior, unchanged). The 2000-token budget applies to the system prompt only. Tool schemas are in the `tools` API parameter — a different token pool.

**Fallback:** If tool_hint is wrong, the model has find_tools and discovers the right tool. Cost: ~100 wasted tokens for the wrong schema.

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

**New tool added:** Tool catalog in classifier prompt updates automatically from registry on restart. No manual maintenance. When tool count exceeds ~75, switch to category-based catalog.

**Multi-turn follow-ups:** Classifier receives last 2-3 turns from the WebSocket session as input context. "Do it again" and "Change the color" are correctly interpreted because the classifier sees what came before.

### 6. Headless Mode Integration

`build_headless()` uses the same planner-driven approach with a pre-built plan:
```python
headless_plan = Plan(
    needs=Needs(rag=True, experiences=True, history=False, user_profile=False, user_facts=False),
    tool_hint=None,
    response_style="brief",
    complexity="single_tool",
)
```
Background tasks get the same minimal, targeted prompts. No separate code path that might accidentally load 13K of context.

### 7. Example: "Make me a song about cats"

**Classifier input:** "Make me a song about cats" + tool catalog
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
You are Bob. You're helpful and direct.

You can manage workspaces, generate media, execute code, and more.
Use find_tools to discover specific capabilities. Call it when asked
to do something. Do not say "I can't" without checking.

[XSkill experience for generate_music, if any]

Be concise. Lead with the answer.
```
~400 chars system prompt.

**Tool list:** `[find_tools, generate_music]`

**Result:** Model sees generate_music in its tool list, calls it immediately. No 13K of noise.

### 8. Example: "What did I say about Python yesterday?"

**Classifier input:** "What did I say about Python yesterday?" + tool catalog
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
[identity + tool instruction]
[RAG results for "Python yesterday"]
[last 2 turns for entity resolution]
[conversation history]
```
~1500 chars system prompt.

**Tool list:** `[find_tools, search_workspace]`

### 9. Example: Multi-turn "Do it again but in jazz"

**Classifier input:** "Do it again but in jazz" + last 2 turns showing a previous music generation request
**Classifier returns:**
```json
{
  "classification": "creative",
  "intent": "generate_music",
  "tool_hint": "generate_music",
  "needs": {"rag": false, "user_profile": false, "user_facts": false, "history": true, "experiences": true},
  "response_style": "brief",
  "complexity": "single_tool"
}
```

The classifier saw the previous turns, understood "it" refers to a song, set `tool_hint: generate_music` and `history: true` so the model can reference the previous request's details.

## File Changes

| File | Change |
|------|--------|
| `odigos/core/classifier.py` | Enhanced output schema. Tool catalog in classifier prompt. Receives last 2-3 turns as input. |
| `odigos/core/context.py` | Rewrite `build()` — planner-driven, budget-enforced. Receives `recent_turns` from caller. Remove parallel-everything pattern. Remove pruning. Consolidate `build_headless()` to use same planner. |
| `odigos/core/executor.py` | Pass planner output to assembler. Build tool list from tool_hint + find_tools. Pass recent_turns to assembler. |
| `odigos/core/agent.py` | Pass recent_turns from WebSocket session to executor/classifier. |
| `odigos/api/ws.py` | Track last 3 turns in the WebSocket session. Pass to agent.handle_message(). |
| `odigos/personality/prompt_builder.py` | Simplify — concatenate identity + tool instruction + selected sections. |
| `odigos/personality/section_registry.py` | Simplified — loads identity only. Remove always_include flag. |
| `data/agent/capabilities.md` | Remove — replaced by constant |
| `data/agent/meta.md` | Remove from prompt pipeline |
| `data/agent/query handling.md` | Remove from prompt pipeline |
| `data/agent/skill_creation.md` | Remove from prompt pipeline |
| `data/prompts/classifier.md` | Updated with tool catalog, recent turns, and new output schema |
| `odigos/core/relevance.py` | Remove — no more post-hoc pruning |

## What Doesn't Change

- Tool registry, find_tools, tool execution, dynamic expansion
- Memory manager (RAG recall) — called conditionally
- XSkill experience store — loaded when planner flags it
- Heartbeat, background tasks, backgroundable tools, callback system
- Frontend
- Database schema
