# Budget Enforcement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enforce budget limits inside the executor's tool-turn loop with token-count cost estimates, and surface budget warnings to the user.

**Architecture:** Add `budget_tracker` to `Executor`. Before each LLM call in the loop, check `db_spend + run_estimate`. After each call, accumulate a conservative token-based cost estimate. Surface warnings at 80% threshold via response text.

**Tech Stack:** Python 3.12, pytest, AsyncMock

---

### Task 1: Add `extra_cost` parameter to BudgetTracker.check_budget()

**Files:**
- Modify: `odigos/core/budget.py:50-81`
- Test: `tests/test_budget.py`

**Step 1: Write the failing test**

Append to `tests/test_budget.py`:

```python
class TestBudgetExtraCost:
    async def test_extra_cost_added_to_daily(self, db: Database):
        """extra_cost is added to DB spend when checking limits."""
        tracker = BudgetTracker(db=db, daily_limit=0.10, monthly_limit=20.00)
        await _insert_message(db, 0.05)
        # DB has $0.05, extra_cost=$0.06 => total $0.11 > $0.10 limit
        status = await tracker.check_budget(extra_cost=0.06)
        assert status.within_budget is False
        assert abs(status.daily_spend - 0.11) < 1e-9

    async def test_extra_cost_zero_default(self, db: Database):
        """Default extra_cost=0 preserves existing behavior."""
        tracker = BudgetTracker(db=db, daily_limit=1.00, monthly_limit=20.00)
        status = await tracker.check_budget()
        assert status.within_budget is True
        assert status.daily_spend == 0.0

    async def test_extra_cost_triggers_warning(self, db: Database):
        """extra_cost can push spend past warning threshold."""
        tracker = BudgetTracker(db=db, daily_limit=1.00, monthly_limit=20.00)
        # DB has $0, extra_cost=$0.85 => 85% of $1.00 => warning
        status = await tracker.check_budget(extra_cost=0.85)
        assert status.within_budget is True
        assert status.warning is True
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_budget.py::TestBudgetExtraCost -v`
Expected: FAIL — `check_budget()` does not accept `extra_cost` parameter.

**Step 3: Write minimal implementation**

In `odigos/core/budget.py`, change `check_budget` signature and add `extra_cost` to the spend totals:

```python
    async def check_budget(self, extra_cost: float = 0.0) -> BudgetStatus:
        daily = await self.get_daily_spend() + extra_cost
        monthly = await self.get_monthly_spend() + extra_cost
```

The rest of the method stays identical — it already compares `daily` and `monthly` against limits.

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_budget.py -v`
Expected: All budget tests PASS (existing + 3 new).

**Step 5: Commit**

```bash
git add odigos/core/budget.py tests/test_budget.py
git commit -m "feat: add extra_cost parameter to BudgetTracker.check_budget()"
```

---

### Task 2: Add budget check and cost estimation to Executor

**Files:**
- Modify: `odigos/core/executor.py:37-146`
- Test: `tests/test_react_loop.py`

**Step 1: Write the failing tests**

Append to `tests/test_react_loop.py`:

```python
from odigos.core.budget import BudgetTracker, BudgetStatus


class TestBudgetEnforcement:
    async def test_executor_breaks_on_budget_exceeded(self, mock_provider, mock_assembler):
        """Executor stops the tool loop when budget is exceeded mid-run."""
        budget_tracker = AsyncMock(spec=BudgetTracker)
        # First check: within budget. Second check (after first LLM call): over budget.
        budget_tracker.check_budget = AsyncMock(side_effect=[
            BudgetStatus(within_budget=True, warning=False, daily_spend=0.5, monthly_spend=0.5, daily_limit=1.0, monthly_limit=20.0),
            BudgetStatus(within_budget=False, warning=False, daily_spend=1.1, monthly_spend=1.1, daily_limit=1.0, monthly_limit=20.0),
        ])

        # Provider returns tool call on first response (to keep the loop going)
        tool_call = ToolCall(id="tc1", name="test_tool", arguments={})
        mock_provider.complete = AsyncMock(side_effect=[
            LLMResponse(content="", model="test", tokens_in=100, tokens_out=50, cost_usd=0.0, tool_calls=[tool_call]),
        ])

        # Register a dummy tool
        tool_registry = ToolRegistry()
        dummy_tool = MagicMock(spec=BaseTool)
        dummy_tool.name = "test_tool"
        dummy_tool.execute = AsyncMock(return_value=ToolResult(success=True, data="ok"))
        tool_registry.register(dummy_tool)

        executor = Executor(
            provider=mock_provider,
            context_assembler=mock_assembler,
            tool_registry=tool_registry,
            budget_tracker=budget_tracker,
        )

        result = await executor.execute("conv-1", "Do something")

        # Should have called LLM only once (broke before second call)
        assert mock_provider.complete.call_count == 1
        # Response should mention budget
        assert "budget" in result.response.content.lower() or "spending" in result.response.content.lower()

    async def test_executor_accumulates_cost_estimate(self, mock_provider, mock_assembler):
        """Executor passes increasing extra_cost to budget check each turn."""
        budget_tracker = AsyncMock(spec=BudgetTracker)
        budget_tracker.check_budget = AsyncMock(return_value=BudgetStatus(
            within_budget=True, warning=False, daily_spend=0.0, monthly_spend=0.0, daily_limit=10.0, monthly_limit=100.0,
        ))

        # Two LLM calls: first returns tool call, second returns text
        tool_call = ToolCall(id="tc1", name="test_tool", arguments={})
        mock_provider.complete = AsyncMock(side_effect=[
            LLMResponse(content="", model="test", tokens_in=1000, tokens_out=500, cost_usd=0.0, tool_calls=[tool_call]),
            LLMResponse(content="Done", model="test", tokens_in=500, tokens_out=200, cost_usd=0.0),
        ])

        tool_registry = ToolRegistry()
        dummy_tool = MagicMock(spec=BaseTool)
        dummy_tool.name = "test_tool"
        dummy_tool.execute = AsyncMock(return_value=ToolResult(success=True, data="ok"))
        tool_registry.register(dummy_tool)

        executor = Executor(
            provider=mock_provider,
            context_assembler=mock_assembler,
            tool_registry=tool_registry,
            budget_tracker=budget_tracker,
        )

        await executor.execute("conv-1", "Do something")

        # First check: extra_cost=0 (before any LLM call)
        # Second check: extra_cost > 0 (after first LLM call estimated cost)
        calls = budget_tracker.check_budget.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs.get("extra_cost", 0) == 0.0
        assert calls[1].kwargs["extra_cost"] > 0

    async def test_budget_warning_appended_to_response(self, mock_provider, mock_assembler):
        """When budget warning is True, a note is appended to the response."""
        budget_tracker = AsyncMock(spec=BudgetTracker)
        budget_tracker.check_budget = AsyncMock(return_value=BudgetStatus(
            within_budget=True, warning=True, daily_spend=0.85, monthly_spend=0.85, daily_limit=1.0, monthly_limit=20.0,
        ))

        mock_provider.complete = AsyncMock(return_value=LLMResponse(
            content="Here is your answer.", model="test", tokens_in=100, tokens_out=50, cost_usd=0.0,
        ))

        executor = Executor(
            provider=mock_provider,
            context_assembler=mock_assembler,
            budget_tracker=budget_tracker,
        )

        result = await executor.execute("conv-1", "Hello")

        assert "budget" in result.response.content.lower()
        assert "85" in result.response.content  # spend percentage

    async def test_no_budget_tracker_skips_check(self, mock_provider, mock_assembler):
        """Executor with no budget_tracker runs without checking."""
        mock_provider.complete = AsyncMock(return_value=LLMResponse(
            content="Response", model="test", tokens_in=100, tokens_out=50, cost_usd=0.0,
        ))

        executor = Executor(
            provider=mock_provider,
            context_assembler=mock_assembler,
        )

        result = await executor.execute("conv-1", "Hello")
        assert result.response.content == "Response"
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_react_loop.py::TestBudgetEnforcement -v`
Expected: FAIL — `Executor.__init__()` does not accept `budget_tracker` parameter.

**Step 3: Write implementation**

In `odigos/core/executor.py`:

1. Add `budget_tracker` parameter to `__init__()`:

```python
    def __init__(
        self,
        provider: LLMProvider,
        context_assembler: ContextAssembler,
        tool_registry: ToolRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        db: Database | None = None,
        max_tool_turns: int = MAX_TOOL_TURNS,
        budget_tracker: BudgetTracker | None = None,
    ) -> None:
        self.provider = provider
        self.context_assembler = context_assembler
        self.tool_registry = tool_registry
        self.skill_registry = skill_registry
        self.db = db
        self._max_tool_turns = max_tool_turns
        self.budget_tracker = budget_tracker
```

2. Add TYPE_CHECKING import:

```python
if TYPE_CHECKING:
    from odigos.core.budget import BudgetTracker
    from odigos.skills.registry import SkillRegistry
    from odigos.tools.registry import ToolRegistry
```

3. Add `_estimate_cost` module-level function:

```python
# Conservative $/token rates for budget estimation (roughly Claude Sonnet pricing).
# Intentionally over-estimates for free/cheap models — fine for a safety cap.
_INPUT_RATE_PER_M = 3.0
_OUTPUT_RATE_PER_M = 15.0


def _estimate_cost(tokens_in: int, tokens_out: int) -> float:
    return (tokens_in * _INPUT_RATE_PER_M + tokens_out * _OUTPUT_RATE_PER_M) / 1_000_000
```

4. In `execute()`, add budget check before the LLM call inside the loop, and accumulate estimate after:

```python
        # Track estimated cost for this run
        run_estimated_cost = 0.0
        budget_warning: BudgetStatus | None = None

        for turn in range(self._max_tool_turns):
            # Check abort flag
            if abort_event and abort_event.is_set():
                logger.info("Run aborted at turn %d", turn)
                break

            # Budget check with running estimate
            if self.budget_tracker:
                status = await self.budget_tracker.check_budget(extra_cost=run_estimated_cost)
                if not status.within_budget:
                    logger.warning("Budget exceeded mid-run at turn %d", turn)
                    if last_response is None:
                        last_response = LLMResponse(
                            content="I've hit my spending limit mid-task. Here's what I have so far.",
                            model="system", tokens_in=0, tokens_out=0, cost_usd=0.0,
                        )
                    break
                if status.warning:
                    budget_warning = status

            # Call LLM
            response = await self.provider.complete(messages, tools=tools)
            total_tokens_in += response.tokens_in
            total_tokens_out += response.tokens_out
            total_cost += response.cost_usd
            run_estimated_cost += _estimate_cost(response.tokens_in, response.tokens_out)
            last_response = response

            # ... rest of loop unchanged ...
```

5. After the loop, before returning, append budget warning to response if applicable:

```python
        # Append budget warning to response if triggered
        if budget_warning and last_response and last_response.content:
            pct = max(
                budget_warning.daily_spend / budget_warning.daily_limit * 100 if budget_warning.daily_limit > 0 else 0,
                budget_warning.monthly_spend / budget_warning.monthly_limit * 100 if budget_warning.monthly_limit > 0 else 0,
            )
            last_response = LLMResponse(
                content=f"{last_response.content}\n\n---\nNote: I've used {pct:.0f}% of my budget for this period (${budget_warning.daily_spend:.2f}/${budget_warning.daily_limit:.2f} daily).",
                model=last_response.model,
                tokens_in=last_response.tokens_in,
                tokens_out=last_response.tokens_out,
                cost_usd=last_response.cost_usd,
                generation_id=last_response.generation_id,
                tool_calls=last_response.tool_calls,
            )
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_react_loop.py -v`
Expected: All tests PASS (existing + 4 new).

**Step 5: Commit**

```bash
git add odigos/core/executor.py tests/test_react_loop.py
git commit -m "feat: enforce budget inside executor tool-turn loop"
```

---

### Task 3: Wire budget_tracker into Executor via Agent and main.py

**Files:**
- Modify: `odigos/core/agent.py:46-60`
- Modify: `odigos/main.py`

**Step 1: Pass budget_tracker to Executor in Agent.__init__()**

In `odigos/core/agent.py`, find where `Executor` is constructed. Add `budget_tracker=budget_tracker`:

```python
        self.executor = Executor(
            provider=provider,
            context_assembler=self.context_assembler,
            tool_registry=tool_registry,
            skill_registry=skill_registry,
            db=db,
            max_tool_turns=max_tool_turns,
            budget_tracker=budget_tracker,
        )
```

**Step 2: Add warn_threshold to BudgetConfig**

In `odigos/config.py`, add to `BudgetConfig`:

```python
class BudgetConfig(BaseModel):
    daily_limit_usd: float = 1.00
    monthly_limit_usd: float = 20.00
    warn_threshold: float = 0.80
```

In `main.py`, pass it when constructing BudgetTracker:

```python
    budget_tracker = BudgetTracker(
        db=_db,
        daily_limit=settings.budget.daily_limit_usd,
        monthly_limit=settings.budget.monthly_limit_usd,
        warn_threshold=settings.budget.warn_threshold,
    )
```

**Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS (283+ tests).

**Step 4: Commit**

```bash
git add odigos/core/agent.py odigos/config.py odigos/main.py
git commit -m "feat: wire budget_tracker into Executor, make warn_threshold configurable"
```

---

### Task 4: Test _estimate_cost and edge cases

**Files:**
- Modify: `tests/test_react_loop.py`

**Step 1: Write edge case tests**

Append to `tests/test_react_loop.py`:

```python
from odigos.core.executor import _estimate_cost


class TestEstimateCost:
    def test_zero_tokens(self):
        assert _estimate_cost(0, 0) == 0.0

    def test_input_only(self):
        # 1M input tokens at $3/M = $3.00
        cost = _estimate_cost(1_000_000, 0)
        assert abs(cost - 3.0) < 1e-9

    def test_output_only(self):
        # 1M output tokens at $15/M = $15.00
        cost = _estimate_cost(0, 1_000_000)
        assert abs(cost - 15.0) < 1e-9

    def test_typical_call(self):
        # 1000 input + 500 output
        # (1000 * 3 + 500 * 15) / 1M = (3000 + 7500) / 1M = 0.0105
        cost = _estimate_cost(1000, 500)
        assert abs(cost - 0.0105) < 1e-9
```

**Step 2: Run tests**

Run: `.venv/bin/python -m pytest tests/test_react_loop.py::TestEstimateCost -v`
Expected: All 4 PASS.

**Step 3: Run full suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS.

**Step 4: Commit**

```bash
git add tests/test_react_loop.py
git commit -m "test: add _estimate_cost unit tests and budget edge cases"
```
