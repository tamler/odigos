# Budget Enforcement Design

## Goal

Prevent runaway costs by enforcing budget limits inside the executor's tool-turn loop (not just at the entry gate), using token-count estimates to compensate for async cost backfill delay.

## Current State

- `BudgetTracker` queries `messages.cost_usd` and reports `within_budget` / `warning`
- Hard gate in `Agent._run()` checks budget before calling executor
- Real cost backfilled async (2s delay via OpenRouter generation API)
- No check inside the executor's tool-turn loop (25 turns can run unchecked)
- `cost_usd` reads as `$0.00` for recent turns until backfill completes

## Changes

### 1. Budget check inside executor loop (`executor.py`)

Before each `provider.complete()` call, check `BudgetTracker.check_budget(extra_cost=run_estimate)`. If over limit, break with a budget-exceeded message. Executor receives `BudgetTracker` via constructor.

### 2. Token-count running estimate (`executor.py`)

After each LLM response, accumulate estimated cost:

```python
_estimate_cost(tokens_in, tokens_out) = (tokens_in * 3 + tokens_out * 15) / 1_000_000
```

Rate: $3/M input, $15/M output (conservative, roughly Claude Sonnet pricing). Over-estimates for free/cheap models, which is desirable for a safety cap.

### 3. BudgetTracker.check_budget() accepts extra_cost (`budget.py`)

Optional `extra_cost: float = 0.0` parameter added to DB-queried spend before comparing against limits.

### 4. User-facing budget warning

When `status.warning` is True (80% threshold), append a note to the response with current spend percentage.

### 5. Config: make warn_threshold configurable

Add `warn_threshold: float = 0.80` to `BudgetConfig`. Thread through to `BudgetTracker`.

## Data Flow

```
Agent._run()
  -> BudgetTracker.check_budget() [existing gate]
  -> Executor.execute()
      -> [each tool turn]
          -> check_budget(extra_cost=run_estimate) [NEW]
          -> if over: break with budget message
          -> provider.complete()
          -> run_estimate += _estimate_cost(tokens) [NEW]
      -> return ExecuteResult (may include warning)
  -> Reflector.reflect() [unchanged]
```

## What's NOT in scope

- Model downgrade at 70% (deferred to multi-tenancy)
- Emergency reserve (single user, not needed yet)
- Hot-reloadable budget.yaml (YAGNI)
- Per-task cost attribution (YAGNI)

## Testing

- Executor breaks loop when budget exceeded mid-run
- `_estimate_cost()` math correctness
- `check_budget(extra_cost=X)` adds X to DB spend
- Warning message included at 80% threshold
