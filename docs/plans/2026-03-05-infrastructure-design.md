# Infrastructure Phase Design: Router, Cost Tracking, Context Budget, Skills

**Date:** 2026-03-05
**Status:** Approved
**Milestone:** "It's smart about resources" -- the agent pools free models, tracks costs, manages context budgets, and selects skills based on intent.

---

## Scope

Four interdependent components built bottom-up: cost tracking, model router, context budget, skills system. Only the free model tier is actively routed this phase. Cost tracking is log + warn (no hard cap). Skills are prompt templates (SKILL.md), not pipelines.

Deferred: paid model tiers (Tier 2/3), hard budget caps, pipeline-style skills, local model integration (Tier 0).

### Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Router scope | Free tier pool only | Cheapest path to value. Infrastructure supports all tiers but only free pool is active. |
| Cost source | OpenRouter generation endpoint | `GET /api/v1/generation?id=<id>` returns `total_cost`. Async fire-and-forget after each call. |
| Budget enforcement | Log + warn at 80% | Visibility without risk of broken behavior. Hard cap in a future phase. |
| Skills format | SKILL.md prompt templates | Simple, extensible. Planner selects skill, executor applies prompt. |
| Context estimation | chars / 4 | Good enough, no tokenizer dependency. |
| Build order | Cost -> Router -> Context -> Skills | Each layer depends on the one below. |

---

## Component 1: Cost Tracking

### OpenRouter Provider Upgrade (`providers/openrouter.py`)

The chat completions response includes an `id` field (generation ID). After each successful call, fire-and-forget an async task to fetch actual cost from `GET /api/v1/generation?id=<id>` and update the stored message cost.

For immediate use, calculate an estimate from token counts using per-model pricing (the router will know model prices). Store the estimate in `LLMResponse.cost_usd` immediately; the async lookup corrects it later.

Changes to `_call()`:
- Extract `id` from response JSON
- Store `id` in `LLMResponse` (add `generation_id: str | None` field)
- Calculate estimated cost from tokens + model pricing
- Return immediately with estimate

### Budget Tracker (`core/budget.py`)

Simple query-based tracker:
- `get_daily_spend() -> float` -- sum of `cost_usd` from messages today
- `get_monthly_spend() -> float` -- sum of `cost_usd` from messages this month
- `check_budget() -> BudgetStatus` -- returns status with `within_budget`, `daily_spend`, `monthly_spend`, `daily_limit`, `monthly_limit`
- Logs warning at 80% of configured limit

No new tables needed -- queries against existing `messages.cost_usd` column.

### Config Addition

```yaml
budget:
  daily_limit_usd: 1.00   # warn at $0.80
  monthly_limit_usd: 20.00  # warn at $16.00
```

---

## Component 2: Model Router (`core/router.py`)

### Architecture

The `ModelRouter` sits between the agent and the OpenRouter provider. Instead of calling `provider.complete()` directly, all code calls `router.complete()`. The router:

1. Classifies request complexity from kwargs or explicit parameter
2. Selects the best available model from the free pool
3. Calls the provider with the selected model
4. Handles 429 (rate limit) by rotating to next model in pool
5. Tracks per-model rate limit state (requests remaining, reset time)

### Complexity Classification

Three tiers, passed as a kwarg or inferred:
- `"light"`: classification, yes/no, simple extraction (planner calls)
- `"standard"`: general conversation, Q&A, synthesis (most executor calls)
- `"complex"`: multi-step reasoning, creative writing (future, deferred)

For this phase, `"light"` and `"standard"` both route to the free pool. The distinction exists in the interface so paid tiers can use it later.

### Free Model Pool

The pool is a list of model IDs configured in YAML. The router maintains per-model state:
- `remaining_requests: int` (decremented on use, reset on timer)
- `reset_at: datetime` (when rate limit resets, typically 1 minute)
- `consecutive_failures: int` (model deprioritized after failures)

Model selection strategy: round-robin with skip on exhausted/failed models. When all models are exhausted, wait for the earliest reset.

### Rate Limit Handling

OpenRouter returns 429 with `Retry-After` header on rate limit. The router:
1. Marks the model as exhausted with the retry-after time
2. Tries the next model in the pool
3. If all exhausted, waits for the shortest `Retry-After` and retries

### Interface

```python
class ModelRouter:
    async def complete(
        self,
        messages: list[dict],
        complexity: str = "standard",
        **kwargs,
    ) -> LLMResponse: ...
```

The `ModelRouter` implements the `LLMProvider` interface so it's a drop-in replacement everywhere `provider` is used.

### Config Addition

```yaml
router:
  free_pool:
    - "arcee-ai/trinity-large-preview:free"
    - "z-ai/glm-4.5-air:free"
    - "google/gemma-3-27b-it:free"
    - "mistralai/mistral-small-3.2-24b-instruct:free"
    - "meta-llama/llama-4-scout:free"
  rate_limit_rpm: 20  # default per-model requests per minute
```

---

## Component 3: Context Budget (`core/context.py` upgrade)

### Token Estimation

Add a `estimate_tokens(text: str) -> int` function: `len(text) // 4`. Simple, no dependencies, ~75% accurate.

### Context Assembly Budget

`ContextAssembler.build()` gets a `max_tokens: int` parameter (default from config). Before returning, it checks total estimated tokens and trims if over budget:

1. Calculate: system_prompt + memory_context + tool_context + history + current_message
2. If over budget, trim history (oldest first) until under budget
3. If still over after removing all history, truncate memory_context
4. Log a warning when trimming occurs

The router passes the model's context limit to the executor, which passes it to the context assembler.

### Config Addition

```yaml
context:
  max_tokens: 12000  # conservative default for free models
```

---

## Component 4: Skills System

### SKILL.md Format

Skills live in `skills/` directory. Each is a markdown file with YAML frontmatter:

```markdown
---
name: research-deep-dive
description: In-depth research using web search and page reading
tools: [web_search, read_page]
complexity: standard
---
You are a thorough research assistant. When asked about a topic:
1. Search for relevant information
2. Read the most promising pages
3. Synthesize a comprehensive, well-sourced answer

Always cite your sources with URLs.
```

### Skill Registry (`skills/registry.py`)

Loads SKILL.md files at startup:
- `load_all(skills_dir: str) -> list[Skill]`
- `get(name: str) -> Skill | None`
- `list() -> list[Skill]`

`Skill` dataclass: `name`, `description`, `tools: list[str]`, `complexity: str`, `system_prompt: str`

### Planner Integration

The `CLASSIFY_PROMPT` gets updated to also select a skill when appropriate. The planner returns `Plan.skill: str | None` alongside `Plan.action`.

Updated classification output format:
```json
{"action": "search", "query": "...", "skill": "research-deep-dive"}
```

When no skill matches, `skill` is null and behavior is unchanged (current default prompt).

### Executor Integration

When `plan.skill` is set, the executor:
1. Loads the skill from the registry
2. Replaces the system prompt with the skill's prompt (personality sections still included)
3. Passes `skill.complexity` to the router for model selection
4. Executes with the skill's preferred tools

The hardcoded `_ACTION_TOOLS` map is replaced by skill-driven tool selection. The planner's action still drives which tool to call, but the skill provides the system prompt context.

### Built-in Skills (3-4 to start)

1. **`research-deep-dive`**: Search + scrape + synthesize. For factual questions requiring multiple sources.
2. **`summarize-page`**: Scrape + summarize. For "summarize this URL" requests.
3. **`general-chat`**: Default conversation skill. Current personality prompt, no tools.

More can be added by dropping SKILL.md files into the directory.

### Config

```yaml
skills:
  path: "skills"  # directory containing SKILL.md files
```

---

## Integration Points

- **`main.py`**: Initializes `ModelRouter` (wrapping `OpenRouterProvider`), `BudgetTracker`, `SkillRegistry`. Passes router as the provider to agent/planner/executor.
- **`core/agent.py`**: No changes (router is a drop-in for provider).
- **`core/planner.py`**: Updated classification prompt, returns `skill` in Plan.
- **`core/executor.py`**: Applies skill prompt, passes complexity to router.
- **`core/context.py`**: Token budgeting in `build()`.
- **`providers/openrouter.py`**: Extracts generation ID, calculates cost estimate.
- **`config.py`**: New `BudgetConfig`, `RouterConfig`, `ContextConfig`, `SkillsConfig` sections.

What does NOT change: reflector, memory manager, tool registry, search/scrape tools, database schema.
