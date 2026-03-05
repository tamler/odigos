# Infrastructure Phase Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add cost tracking, model router (free pool), context budgeting, and skills system to Odigos.

**Architecture:** Bottom-up build: cost tracking first (OpenRouter provider upgrade + budget tracker), then model router (wraps provider, implements LLMProvider), then context budgeting (token estimation + trimming in ContextAssembler), then skills system (SKILL.md templates + registry + planner/executor integration). Each layer depends on the one below.

**Tech Stack:** Python 3.12, asyncio, httpx, pydantic, pytest, aiosqlite

---

### Task 1: Add `generation_id` to `LLMResponse` and extract it from OpenRouter

**Files:**
- Modify: `odigos/providers/base.py:5-11`
- Modify: `odigos/providers/openrouter.py:55-78`
- Test: `tests/test_openrouter.py` (create)

**Step 1: Write the failing test**

Create `tests/test_openrouter.py`:

```python
import httpx
import pytest
from unittest.mock import AsyncMock, patch

from odigos.providers.base import LLMResponse
from odigos.providers.openrouter import OpenRouterProvider


class TestOpenRouterGenerationId:
    @pytest.fixture
    def provider(self):
        return OpenRouterProvider(
            api_key="test-key",
            default_model="test/model",
            fallback_model="test/fallback",
        )

    async def test_extracts_generation_id(self, provider):
        """Provider extracts generation ID from response."""
        mock_response = httpx.Response(
            200,
            json={
                "id": "gen-abc123",
                "choices": [{"message": {"content": "Hello"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "model": "test/model",
            },
        )
        with patch.object(provider._client, "post", return_value=mock_response):
            result = await provider.complete([{"role": "user", "content": "Hi"}])

        assert result.generation_id == "gen-abc123"

    async def test_generation_id_none_when_missing(self, provider):
        """Provider sets generation_id to None when not in response."""
        mock_response = httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Hello"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
        with patch.object(provider._client, "post", return_value=mock_response):
            result = await provider.complete([{"role": "user", "content": "Hi"}])

        assert result.generation_id is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_openrouter.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'generation_id'` or `TypeError`

**Step 3: Write minimal implementation**

In `odigos/providers/base.py`, add `generation_id` field to `LLMResponse`:

```python
@dataclass
class LLMResponse:
    content: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    generation_id: str | None = None
```

In `odigos/providers/openrouter.py`, update `_call()` to extract `id`:

```python
async def _call(self, messages: list[dict], model: str, **kwargs) -> LLMResponse:
    """Make a single API call to OpenRouter."""
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": kwargs.get("max_tokens", self.max_tokens),
        "temperature": kwargs.get("temperature", self.temperature),
    }

    response = await self._client.post(OPENROUTER_API_URL, json=payload)

    if response.status_code != 200:
        raise RuntimeError(f"OpenRouter API error {response.status_code}: {response.text}")

    data = response.json()
    usage = data.get("usage", {})

    return LLMResponse(
        content=data["choices"][0]["message"]["content"],
        model=data.get("model", model),
        tokens_in=usage.get("prompt_tokens", 0),
        tokens_out=usage.get("completion_tokens", 0),
        cost_usd=0.0,
        generation_id=data.get("id"),
    )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_openrouter.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/providers/base.py odigos/providers/openrouter.py tests/test_openrouter.py
git commit -m "feat: extract generation_id from OpenRouter responses"
```

---

### Task 2: Create `BudgetTracker` (`core/budget.py`)

**Files:**
- Create: `odigos/core/budget.py`
- Test: `tests/test_budget.py` (create)

**Step 1: Write the failing test**

Create `tests/test_budget.py`:

```python
import uuid
from datetime import datetime, timezone

import pytest

from odigos.core.budget import BudgetStatus, BudgetTracker
from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


async def _insert_message(db: Database, cost: float, conv_id: str = "conv-1") -> None:
    """Insert a message with a specific cost for budget testing."""
    # Ensure conversation exists
    existing = await db.fetch_one(
        "SELECT id FROM conversations WHERE id = ?", (conv_id,)
    )
    if not existing:
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            (conv_id, "test"),
        )
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, cost_usd) "
        "VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), conv_id, "assistant", "test", cost),
    )


class TestBudgetTracker:
    async def test_daily_spend_empty(self, db: Database):
        tracker = BudgetTracker(db=db)
        spend = await tracker.get_daily_spend()
        assert spend == 0.0

    async def test_daily_spend_sums_today(self, db: Database):
        tracker = BudgetTracker(db=db)
        await _insert_message(db, 0.01)
        await _insert_message(db, 0.02)
        spend = await tracker.get_daily_spend()
        assert abs(spend - 0.03) < 1e-9

    async def test_monthly_spend_sums(self, db: Database):
        tracker = BudgetTracker(db=db)
        await _insert_message(db, 0.05)
        await _insert_message(db, 0.10)
        spend = await tracker.get_monthly_spend()
        assert abs(spend - 0.15) < 1e-9

    async def test_check_budget_within(self, db: Database):
        tracker = BudgetTracker(
            db=db, daily_limit=1.00, monthly_limit=20.00
        )
        status = await tracker.check_budget()
        assert status.within_budget is True
        assert status.daily_spend == 0.0

    async def test_check_budget_warns_at_80_pct(self, db: Database):
        tracker = BudgetTracker(
            db=db, daily_limit=0.10, monthly_limit=20.00
        )
        await _insert_message(db, 0.09)  # 90% of daily
        status = await tracker.check_budget()
        assert status.within_budget is False

    async def test_check_budget_monthly_warn(self, db: Database):
        tracker = BudgetTracker(
            db=db, daily_limit=100.00, monthly_limit=0.10
        )
        await _insert_message(db, 0.09)  # 90% of monthly
        status = await tracker.check_budget()
        assert status.within_budget is False
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_budget.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'odigos.core.budget'`

**Step 3: Write minimal implementation**

Create `odigos/core/budget.py`:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass

from odigos.db import Database

logger = logging.getLogger(__name__)


@dataclass
class BudgetStatus:
    within_budget: bool
    daily_spend: float
    monthly_spend: float
    daily_limit: float
    monthly_limit: float


class BudgetTracker:
    """Tracks LLM spending by querying stored message costs."""

    def __init__(
        self,
        db: Database,
        daily_limit: float = 1.00,
        monthly_limit: float = 20.00,
        warn_threshold: float = 0.80,
    ) -> None:
        self.db = db
        self.daily_limit = daily_limit
        self.monthly_limit = monthly_limit
        self.warn_threshold = warn_threshold

    async def get_daily_spend(self) -> float:
        row = await self.db.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total "
            "FROM messages WHERE date(timestamp) = date('now')"
        )
        return row["total"] if row else 0.0

    async def get_monthly_spend(self) -> float:
        row = await self.db.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total "
            "FROM messages WHERE strftime('%Y-%m', timestamp) = strftime('%Y-%m', 'now')"
        )
        return row["total"] if row else 0.0

    async def check_budget(self) -> BudgetStatus:
        daily = await self.get_daily_spend()
        monthly = await self.get_monthly_spend()

        within = (
            daily < self.daily_limit * self.warn_threshold
            and monthly < self.monthly_limit * self.warn_threshold
        )

        if not within:
            logger.warning(
                "Budget warning: daily=$%.4f/%s (%.0f%%), monthly=$%.4f/%s (%.0f%%)",
                daily, self.daily_limit, (daily / self.daily_limit * 100) if self.daily_limit else 0,
                monthly, self.monthly_limit, (monthly / self.monthly_limit * 100) if self.monthly_limit else 0,
            )

        return BudgetStatus(
            within_budget=within,
            daily_spend=daily,
            monthly_spend=monthly,
            daily_limit=self.daily_limit,
            monthly_limit=self.monthly_limit,
        )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_budget.py -v`
Expected: PASS (6/6)

**Step 5: Commit**

```bash
git add odigos/core/budget.py tests/test_budget.py
git commit -m "feat: add BudgetTracker for daily/monthly spend tracking"
```

---

### Task 3: Add budget and router config sections

**Files:**
- Modify: `odigos/config.py`
- Test: `tests/test_config.py` (create or extend)

**Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
from odigos.config import (
    BudgetConfig,
    ContextConfig,
    RouterConfig,
    Settings,
    SkillsConfig,
)


class TestNewConfigSections:
    def test_budget_config_defaults(self):
        cfg = BudgetConfig()
        assert cfg.daily_limit_usd == 1.00
        assert cfg.monthly_limit_usd == 20.00

    def test_router_config_defaults(self):
        cfg = RouterConfig()
        assert len(cfg.free_pool) > 0
        assert cfg.rate_limit_rpm == 20

    def test_context_config_defaults(self):
        cfg = ContextConfig()
        assert cfg.max_tokens == 12000

    def test_skills_config_defaults(self):
        cfg = SkillsConfig()
        assert cfg.path == "skills"

    def test_settings_includes_new_sections(self):
        settings = Settings(
            telegram_bot_token="test",
            openrouter_api_key="test",
        )
        assert settings.budget.daily_limit_usd == 1.00
        assert settings.router.free_pool is not None
        assert settings.context.max_tokens == 12000
        assert settings.skills.path == "skills"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'BudgetConfig'`

**Step 3: Write minimal implementation**

Add to `odigos/config.py` (after existing config classes, before `Settings`):

```python
class BudgetConfig(BaseModel):
    daily_limit_usd: float = 1.00
    monthly_limit_usd: float = 20.00


class RouterConfig(BaseModel):
    free_pool: list[str] = [
        "meta-llama/llama-4-scout:free",
        "google/gemma-3-27b-it:free",
        "mistralai/mistral-small-3.2-24b-instruct:free",
    ]
    rate_limit_rpm: int = 20


class ContextConfig(BaseModel):
    max_tokens: int = 12000


class SkillsConfig(BaseModel):
    path: str = "skills"
```

Add to `Settings` class body:

```python
    budget: BudgetConfig = BudgetConfig()
    router: RouterConfig = RouterConfig()
    context: ContextConfig = ContextConfig()
    skills: SkillsConfig = SkillsConfig()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (5/5)

**Step 5: Run full test suite to check nothing broke**

Run: `uv run pytest -x -q`
Expected: All pass (existing `test_settings` fixture in conftest.py should still work since new fields have defaults)

**Step 6: Commit**

```bash
git add odigos/config.py tests/test_config.py
git commit -m "feat: add BudgetConfig, RouterConfig, ContextConfig, SkillsConfig"
```

---

### Task 4: Create `ModelRouter` (`core/router.py`)

**Files:**
- Create: `odigos/core/router.py`
- Test: `tests/test_router.py` (create)

**Step 1: Write the failing test**

Create `tests/test_router.py`:

```python
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

import pytest

from odigos.core.router import ModelRouter
from odigos.providers.base import LLMResponse


def _make_response(model: str = "model-a") -> LLMResponse:
    return LLMResponse(
        content="ok",
        model=model,
        tokens_in=10,
        tokens_out=5,
        cost_usd=0.0,
    )


class TestModelRouter:
    @pytest.fixture
    def mock_provider(self):
        provider = AsyncMock()
        provider.complete.return_value = _make_response("model-a:free")
        return provider

    async def test_routes_to_free_pool(self, mock_provider):
        """Router passes a model from the free pool to the provider."""
        router = ModelRouter(
            provider=mock_provider,
            free_pool=["model-a:free", "model-b:free"],
            rate_limit_rpm=20,
        )
        result = await router.complete([{"role": "user", "content": "hi"}])

        assert result.content == "ok"
        call_kwargs = mock_provider.complete.call_args
        assert call_kwargs.kwargs.get("model") in ["model-a:free", "model-b:free"]

    async def test_round_robins(self, mock_provider):
        """Router cycles through models."""
        router = ModelRouter(
            provider=mock_provider,
            free_pool=["model-a:free", "model-b:free"],
            rate_limit_rpm=20,
        )
        models_used = []
        for _ in range(4):
            await router.complete([{"role": "user", "content": "hi"}])
            model = mock_provider.complete.call_args.kwargs.get("model")
            models_used.append(model)

        # Should alternate (or at least use both)
        assert "model-a:free" in models_used
        assert "model-b:free" in models_used

    async def test_rotates_on_rate_limit(self, mock_provider):
        """Router tries next model when current model returns 429."""
        call_count = 0

        async def side_effect(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("OpenRouter API error 429: Rate limited")
            return _make_response(kwargs.get("model", "model-b:free"))

        mock_provider.complete.side_effect = side_effect

        router = ModelRouter(
            provider=mock_provider,
            free_pool=["model-a:free", "model-b:free"],
            rate_limit_rpm=20,
        )
        result = await router.complete([{"role": "user", "content": "hi"}])

        assert result.content == "ok"
        assert mock_provider.complete.call_count == 2

    async def test_all_exhausted_raises(self, mock_provider):
        """Router raises when all models are exhausted."""
        mock_provider.complete.side_effect = RuntimeError("429: Rate limited")

        router = ModelRouter(
            provider=mock_provider,
            free_pool=["model-a:free"],
            rate_limit_rpm=20,
        )
        with pytest.raises(RuntimeError, match="All models exhausted"):
            await router.complete([{"role": "user", "content": "hi"}])

    async def test_passes_complexity_through(self, mock_provider):
        """Router accepts complexity kwarg without error."""
        router = ModelRouter(
            provider=mock_provider,
            free_pool=["model-a:free"],
            rate_limit_rpm=20,
        )
        result = await router.complete(
            [{"role": "user", "content": "hi"}],
            complexity="light",
        )
        assert result.content == "ok"

    async def test_implements_llm_provider(self):
        """ModelRouter is a subclass of LLMProvider."""
        from odigos.providers.base import LLMProvider
        assert issubclass(ModelRouter, LLMProvider)

    async def test_close_delegates(self, mock_provider):
        """Router close delegates to underlying provider."""
        router = ModelRouter(
            provider=mock_provider,
            free_pool=["model-a:free"],
            rate_limit_rpm=20,
        )
        await router.close()
        mock_provider.close.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'odigos.core.router'`

**Step 3: Write minimal implementation**

Create `odigos/core/router.py`:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from odigos.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


@dataclass
class _ModelState:
    model_id: str
    remaining_requests: int = 20
    reset_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    consecutive_failures: int = 0


class ModelRouter(LLMProvider):
    """Routes requests across a pool of free models with rate-limit awareness.

    Implements LLMProvider so it's a drop-in replacement for the raw provider.
    """

    def __init__(
        self,
        provider: LLMProvider,
        free_pool: list[str],
        rate_limit_rpm: int = 20,
    ) -> None:
        self._provider = provider
        self._rate_limit_rpm = rate_limit_rpm
        self._pool = [
            _ModelState(model_id=m, remaining_requests=rate_limit_rpm)
            for m in free_pool
        ]
        self._index = 0

    async def complete(self, messages: list[dict], **kwargs) -> LLMResponse:
        complexity = kwargs.pop("complexity", "standard")
        _ = complexity  # stored for future tier routing

        tried = 0
        last_error: Exception | None = None

        while tried < len(self._pool):
            state = self._pool[self._index]
            self._index = (self._index + 1) % len(self._pool)

            # Skip exhausted models whose reset hasn't arrived
            now = datetime.now(timezone.utc)
            if state.remaining_requests <= 0 and now < state.reset_at:
                tried += 1
                continue

            # Reset if past the reset window
            if now >= state.reset_at:
                state.remaining_requests = self._rate_limit_rpm
                state.consecutive_failures = 0

            try:
                result = await self._provider.complete(
                    messages, model=state.model_id, **kwargs
                )
                state.remaining_requests -= 1
                state.consecutive_failures = 0
                return result
            except RuntimeError as e:
                error_msg = str(e)
                if "429" in error_msg:
                    state.remaining_requests = 0
                    state.reset_at = now + timedelta(seconds=60)
                    logger.warning(
                        "Rate limited on %s, rotating to next model",
                        state.model_id,
                    )
                else:
                    state.consecutive_failures += 1
                    logger.warning(
                        "Model %s failed: %s", state.model_id, e
                    )
                last_error = e
                tried += 1

        raise RuntimeError(
            f"All models exhausted in free pool. Last error: {last_error}"
        )

    async def close(self) -> None:
        await self._provider.close()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_router.py -v`
Expected: PASS (7/7)

**Step 5: Commit**

```bash
git add odigos/core/router.py tests/test_router.py
git commit -m "feat: add ModelRouter with free pool round-robin and rate limit rotation"
```

---

### Task 5: Add token estimation and context budgeting to `ContextAssembler`

**Files:**
- Modify: `odigos/core/context.py`
- Test: `tests/test_core.py` (extend `TestContextAssembler`)

**Step 1: Write the failing test**

Add to `tests/test_core.py`:

```python
class TestContextBudget:
    async def test_estimate_tokens(self, db: Database):
        from odigos.core.context import estimate_tokens
        assert estimate_tokens("hello world") == len("hello world") // 4

    async def test_trims_history_when_over_budget(self, db: Database):
        """Context assembler trims oldest history when over token budget."""
        assembler = ContextAssembler(
            db=db,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
        )

        # Insert a conversation with several long messages
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-budget", "test"),
        )
        for i in range(10):
            role = "user" if i % 2 == 0 else "assistant"
            await db.execute(
                "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
                (f"msg-{i}", "conv-budget", role, f"Message {i} " + "x" * 200),
            )

        # Build with a tight budget -- should trim some history
        messages = await assembler.build(
            "conv-budget", "New message", max_tokens=500
        )

        # Should have fewer history messages than the 10 we inserted
        # (system + some history + current)
        history_count = len(messages) - 2  # minus system and current
        assert history_count < 10

    async def test_no_trimming_within_budget(self, db: Database):
        """No trimming when within budget."""
        assembler = ContextAssembler(
            db=db,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
        )

        messages = await assembler.build(
            "conv-notrim", "Short message", max_tokens=12000
        )

        # system + current (no history in this conv)
        assert len(messages) == 2
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestContextBudget -v`
Expected: FAIL with `ImportError` or `TypeError` (build() doesn't accept `max_tokens`)

**Step 3: Write minimal implementation**

In `odigos/core/context.py`, add `estimate_tokens` function and update `build()`:

```python
import logging

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Estimate token count from text. Rough: ~4 chars per token."""
    return len(text) // 4
```

Update the `build()` method signature and body:

```python
    async def build(
        self,
        conversation_id: str,
        current_message: str,
        tool_context: str = "",
        max_tokens: int = 0,
    ) -> list[dict]:
        """Assemble the full messages list: system + history + current.

        If max_tokens > 0, trims history (oldest first) to stay within budget.
        """
        messages: list[dict] = []

        # Load personality (hot reload -- re-read on every call)
        personality = load_personality(self.personality_path)

        # Get memory context if available
        memory_context = ""
        if self.memory_manager:
            memory_context = await self.memory_manager.recall(current_message)

        # Build system prompt via structured prompt builder
        system_prompt = build_system_prompt(
            personality=personality,
            memory_context=memory_context,
            tool_context=tool_context,
        )

        messages.append({"role": "system", "content": system_prompt})

        # Conversation history
        history = await self.db.fetch_all(
            "SELECT role, content FROM messages "
            "WHERE conversation_id = ? "
            "ORDER BY timestamp ASC "
            "LIMIT ?",
            (conversation_id, self.history_limit),
        )
        for row in history:
            messages.append({"role": row["role"], "content": row["content"]})

        # Current message
        messages.append({"role": "user", "content": current_message})

        # Trim if over budget
        if max_tokens > 0:
            messages = self._trim_to_budget(messages, max_tokens)

        return messages

    def _trim_to_budget(
        self, messages: list[dict], max_tokens: int
    ) -> list[dict]:
        """Trim history messages (oldest first) to fit within token budget."""
        total = sum(estimate_tokens(m["content"]) for m in messages)

        if total <= max_tokens:
            return messages

        # messages[0] = system, messages[-1] = current, middle = history
        # Remove oldest history first (index 1, 2, ...)
        while total > max_tokens and len(messages) > 2:
            removed = messages.pop(1)
            total -= estimate_tokens(removed["content"])
            logger.debug("Trimmed history message to fit context budget")

        if total > max_tokens:
            logger.warning(
                "Context still over budget after trimming all history "
                "(%d > %d tokens)", total, max_tokens,
            )

        return messages
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core.py::TestContextBudget -v`
Expected: PASS (3/3)

**Step 5: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All pass (existing tests use `build()` without `max_tokens`, which defaults to 0 = no trimming)

**Step 6: Commit**

```bash
git add odigos/core/context.py tests/test_core.py
git commit -m "feat: add token estimation and context budget trimming"
```

---

### Task 6: Create `SkillRegistry` and `Skill` dataclass (`skills/registry.py`)

**Files:**
- Create: `odigos/skills/__init__.py`
- Create: `odigos/skills/registry.py`
- Test: `tests/test_skills.py` (create)

**Step 1: Write the failing test**

Create `tests/test_skills.py`:

```python
import pytest

from odigos.skills.registry import Skill, SkillRegistry


@pytest.fixture
def skills_dir(tmp_path):
    """Create a temp directory with SKILL.md files."""
    skill1 = tmp_path / "research-deep-dive.md"
    skill1.write_text(
        "---\n"
        "name: research-deep-dive\n"
        "description: In-depth research using web search\n"
        "tools: [web_search, read_page]\n"
        "complexity: standard\n"
        "---\n"
        "You are a thorough research assistant.\n"
        "Search and synthesize.\n"
    )

    skill2 = tmp_path / "general-chat.md"
    skill2.write_text(
        "---\n"
        "name: general-chat\n"
        "description: Default conversation\n"
        "tools: []\n"
        "complexity: light\n"
        "---\n"
        "You are a helpful assistant.\n"
    )

    # A non-skill file to ensure it's ignored
    (tmp_path / "README.md").write_text("This is not a skill.")

    return tmp_path


class TestSkillDataclass:
    def test_skill_fields(self):
        skill = Skill(
            name="test",
            description="A test skill",
            tools=["web_search"],
            complexity="standard",
            system_prompt="You are a test.",
        )
        assert skill.name == "test"
        assert skill.tools == ["web_search"]


class TestSkillRegistry:
    def test_load_all(self, skills_dir):
        registry = SkillRegistry()
        registry.load_all(str(skills_dir))
        assert len(registry.list()) == 2

    def test_get_by_name(self, skills_dir):
        registry = SkillRegistry()
        registry.load_all(str(skills_dir))
        skill = registry.get("research-deep-dive")
        assert skill is not None
        assert skill.description == "In-depth research using web search"
        assert "web_search" in skill.tools
        assert "thorough research assistant" in skill.system_prompt

    def test_get_missing_returns_none(self, skills_dir):
        registry = SkillRegistry()
        registry.load_all(str(skills_dir))
        assert registry.get("nonexistent") is None

    def test_ignores_non_skill_files(self, skills_dir):
        """Files without valid YAML frontmatter are ignored."""
        registry = SkillRegistry()
        registry.load_all(str(skills_dir))
        names = [s.name for s in registry.list()]
        assert "README" not in names

    def test_empty_dir(self, tmp_path):
        registry = SkillRegistry()
        registry.load_all(str(tmp_path))
        assert len(registry.list()) == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_skills.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'odigos.skills'`

**Step 3: Write minimal implementation**

Create `odigos/skills/__init__.py` (empty).

Create `odigos/skills/registry.py`:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    name: str
    description: str
    tools: list[str]
    complexity: str
    system_prompt: str


class SkillRegistry:
    """Loads and stores SKILL.md prompt templates."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def load_all(self, skills_dir: str) -> None:
        """Load all .md files with valid YAML frontmatter from the directory."""
        path = Path(skills_dir)
        if not path.is_dir():
            logger.warning("Skills directory not found: %s", skills_dir)
            return

        for md_file in sorted(path.glob("*.md")):
            skill = self._parse_skill(md_file)
            if skill:
                self._skills[skill.name] = skill
                logger.info("Loaded skill: %s", skill.name)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list(self) -> list[Skill]:
        return list(self._skills.values())

    def _parse_skill(self, path: Path) -> Skill | None:
        """Parse a SKILL.md file into a Skill dataclass."""
        text = path.read_text()

        # Extract YAML frontmatter between --- delimiters
        if not text.startswith("---"):
            return None

        parts = text.split("---", 2)
        if len(parts) < 3:
            return None

        try:
            meta = yaml.safe_load(parts[1])
        except yaml.YAMLError:
            logger.warning("Failed to parse YAML frontmatter in %s", path)
            return None

        if not isinstance(meta, dict) or "name" not in meta:
            return None

        system_prompt = parts[2].strip()

        return Skill(
            name=meta["name"],
            description=meta.get("description", ""),
            tools=meta.get("tools", []),
            complexity=meta.get("complexity", "standard"),
            system_prompt=system_prompt,
        )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_skills.py -v`
Expected: PASS (6/6)

**Step 5: Commit**

```bash
git add odigos/skills/__init__.py odigos/skills/registry.py tests/test_skills.py
git commit -m "feat: add SkillRegistry with SKILL.md frontmatter parsing"
```

---

### Task 7: Create built-in SKILL.md files

**Files:**
- Create: `skills/research-deep-dive.md`
- Create: `skills/summarize-page.md`
- Create: `skills/general-chat.md`

**Step 1: Create skill files**

Create `skills/research-deep-dive.md`:

```markdown
---
name: research-deep-dive
description: In-depth research using web search and page reading
tools: [web_search, read_page]
complexity: standard
---
You are a thorough research assistant. When asked about a topic:
1. Search for relevant information using web search
2. Read the most promising pages for detailed information
3. Synthesize a comprehensive, well-sourced answer

Always cite your sources with URLs. If information conflicts between sources, note the discrepancy. Prefer recent sources over older ones.
```

Create `skills/summarize-page.md`:

```markdown
---
name: summarize-page
description: Read and summarize a web page
tools: [read_page]
complexity: light
---
You are a concise summarizer. When given a URL:
1. Read the page content
2. Identify the key points and main argument
3. Provide a clear, structured summary

Keep summaries focused and under 300 words unless the user asks for more detail.
```

Create `skills/general-chat.md`:

```markdown
---
name: general-chat
description: Default conversation without tools
tools: []
complexity: light
---
You are a helpful, knowledgeable assistant. Engage naturally in conversation, answer questions from your knowledge, and be direct and concise. If you don't know something, say so honestly rather than guessing.
```

**Step 2: Verify skills load**

Run (quick smoke test):

```bash
uv run python -c "
from odigos.skills.registry import SkillRegistry
r = SkillRegistry()
r.load_all('skills')
for s in r.list():
    print(f'{s.name}: {s.description} (tools={s.tools})')
"
```

Expected output:
```
general-chat: Default conversation without tools (tools=[])
research-deep-dive: In-depth research using web search and page reading (tools=['web_search', 'read_page'])
summarize-page: Read and summarize a web page (tools=['read_page'])
```

**Step 3: Commit**

```bash
git add skills/
git commit -m "feat: add built-in skill templates (research, summarize, general-chat)"
```

---

### Task 8: Update Planner to select skills

**Files:**
- Modify: `odigos/core/planner.py`
- Modify: `tests/test_core.py` (extend `TestPlanner`)

**Step 1: Write the failing test**

Add to `tests/test_core.py` in `TestPlanner`:

```python
    async def test_classify_with_skill(self, mock_classify_provider):
        """Planner returns skill name when LLM selects one."""
        mock_classify_provider.complete.return_value = LLMResponse(
            content='{"action": "search", "query": "AI news 2026", "skill": "research-deep-dive"}',
            model="test/model",
            tokens_in=10,
            tokens_out=15,
            cost_usd=0.0,
        )
        planner = Planner(provider=mock_classify_provider)
        plan = await planner.plan("What's the latest AI news?")

        assert plan.action == "search"
        assert plan.skill == "research-deep-dive"

    async def test_classify_no_skill(self, mock_classify_provider):
        """Planner returns skill=None when LLM doesn't select one."""
        mock_classify_provider.complete.return_value = LLMResponse(
            content='{"action": "respond"}',
            model="test/model",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.0,
        )
        planner = Planner(provider=mock_classify_provider)
        plan = await planner.plan("Hello")

        assert plan.skill is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestPlanner::test_classify_with_skill tests/test_core.py::TestPlanner::test_classify_no_skill -v`
Expected: FAIL with `AttributeError: 'Plan' has no attribute 'skill'`

**Step 3: Write minimal implementation**

In `odigos/core/planner.py`:

Add `skill` field to `Plan` dataclass:

```python
@dataclass
class Plan:
    action: str  # "respond", "search", or "scrape"
    requires_tools: bool = False
    tool_params: dict = field(default_factory=dict)
    skill: str | None = None
```

Update `CLASSIFY_PROMPT` to include skill selection. Add after the existing prompt text:

```python
CLASSIFY_PROMPT = """You are an intent classifier. Given the user's message, decide if the assistant needs to search the web or read a specific page to answer well.

Respond with ONLY a JSON object (no markdown, no explanation):
- If web search is needed: {"action": "search", "query": "<optimized search query>", "skill": "<skill or null>"}
- If reading a specific URL is needed: {"action": "scrape", "url": "<the URL>", "skill": "<skill or null>"}
- If no tools are needed: {"action": "respond", "skill": "<skill or null>"}

Available skills (use the name or null if none fits):
- "research-deep-dive": For questions requiring thorough research with multiple sources
- "summarize-page": For reading and summarizing a specific URL
- "general-chat": For casual conversation, opinions, greetings (default)

Search IS needed for: current events, factual questions, looking things up, "find me", "what is", recent news, prices, weather, technical questions the assistant might not know.
Scrape IS needed for: when the user shares a URL and wants to know what it says, "read this", "summarize this page", "what does this link say", any message containing a URL that the user wants analyzed.
Neither is needed for: greetings, personal questions, opinions, creative writing, math, conversation about things already discussed."""
```

Update `plan()` method to extract skill from result:

In the `plan()` method, after extracting `action`, add skill extraction to each return path:

```python
    async def plan(self, message_content: str) -> Plan:
        try:
            response = await self.provider.complete(
                [
                    {"role": "system", "content": CLASSIFY_PROMPT},
                    {"role": "user", "content": message_content},
                ],
                max_tokens=100,
                temperature=0.0,
            )
            result = _parse_json(response.content)
            action = result.get("action", "respond")
            skill = result.get("skill") or None

            if action == "search":
                query = result.get("query", message_content)
                return Plan(
                    action="search", requires_tools=True,
                    tool_params={"query": query}, skill=skill,
                )

            if action == "scrape":
                url = result.get("url", "")
                if url:
                    return Plan(
                        action="scrape", requires_tools=True,
                        tool_params={"url": url}, skill=skill,
                    )

            return Plan(action="respond", skill=skill)

        except (json.JSONDecodeError, KeyError, RuntimeError):
            logger.warning("Intent classification failed, falling back to respond")
            return Plan(action="respond")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core.py::TestPlanner -v`
Expected: PASS (all planner tests including new ones)

**Step 5: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All pass (existing tests don't check `plan.skill`, so backward-compatible)

**Step 6: Commit**

```bash
git add odigos/core/planner.py tests/test_core.py
git commit -m "feat: planner selects skill alongside action in classification"
```

---

### Task 9: Update Executor to apply skill prompts

**Files:**
- Modify: `odigos/core/executor.py`
- Modify: `tests/test_core.py` (extend `TestExecutor`)

**Step 1: Write the failing test**

Add to `tests/test_core.py`:

```python
class TestExecutorWithSkill:
    async def test_applies_skill_system_prompt(self, db: Database, mock_provider: AsyncMock):
        """Executor replaces system prompt when skill is set on plan."""
        from odigos.skills.registry import Skill, SkillRegistry

        skill = Skill(
            name="research-deep-dive",
            description="Research",
            tools=["web_search"],
            complexity="standard",
            system_prompt="You are a thorough research assistant.",
        )
        skill_registry = SkillRegistry()
        skill_registry._skills["research-deep-dive"] = skill

        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20, personality_path="/nonexistent"
        )

        mock_tool = AsyncMock()
        mock_tool.name = "web_search"
        mock_tool.execute.return_value = ToolResult(success=True, data="## Results\n1. Found it")

        tool_registry = ToolRegistry()
        tool_registry.register(mock_tool)

        executor = Executor(
            provider=mock_provider,
            context_assembler=assembler,
            tool_registry=tool_registry,
            skill_registry=skill_registry,
        )
        plan = Plan(
            action="search", requires_tools=True,
            tool_params={"query": "test"}, skill="research-deep-dive",
        )

        await executor.execute("conv-skill", "research this", plan=plan)

        call_messages = mock_provider.complete.call_args[0][0]
        system_content = call_messages[0]["content"]
        assert "thorough research assistant" in system_content

    async def test_no_skill_uses_default_prompt(self, db: Database, mock_provider: AsyncMock):
        """Executor uses default personality prompt when no skill is set."""
        from odigos.skills.registry import SkillRegistry

        skill_registry = SkillRegistry()

        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20, personality_path="/nonexistent"
        )
        executor = Executor(
            provider=mock_provider,
            context_assembler=assembler,
            skill_registry=skill_registry,
        )
        plan = Plan(action="respond")

        await executor.execute("conv-noskill", "Hello", plan=plan)

        call_messages = mock_provider.complete.call_args[0][0]
        system_content = call_messages[0]["content"]
        # Should contain default personality, not a skill prompt
        assert "Odigos" in system_content
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestExecutorWithSkill -v`
Expected: FAIL with `TypeError: Executor.__init__() got an unexpected keyword argument 'skill_registry'`

**Step 3: Write minimal implementation**

Update `odigos/core/executor.py`:

Add import and update `__init__` and `execute`:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from odigos.core.context import ContextAssembler
from odigos.core.planner import Plan
from odigos.providers.base import LLMProvider, LLMResponse

if TYPE_CHECKING:
    from odigos.skills.registry import SkillRegistry
    from odigos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class ExecuteResult:
    """Result from executor: LLM response + optional metadata from tool execution."""

    response: LLMResponse
    scrape_metadata: dict | None = None


class Executor:
    """Runs the plan -- calls tools then LLM with results in context."""

    def __init__(
        self,
        provider: LLMProvider,
        context_assembler: ContextAssembler,
        tool_registry: ToolRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self.provider = provider
        self.context_assembler = context_assembler
        self.tool_registry = tool_registry
        self.skill_registry = skill_registry

    async def execute(
        self,
        conversation_id: str,
        message_content: str,
        plan: Plan | None = None,
    ) -> ExecuteResult:
        if plan is None:
            plan = Plan(action="respond")

        tool_context = ""
        scrape_metadata = None

        # Map plan actions to tool names
        _ACTION_TOOLS = {
            "search": "web_search",
            "scrape": "read_page",
        }

        tool_name = _ACTION_TOOLS.get(plan.action)
        if tool_name and self.tool_registry:
            tool = self.tool_registry.get(tool_name)
            if tool:
                try:
                    result = await tool.execute(plan.tool_params)
                    if result.success:
                        tool_context = result.data
                        if plan.action == "scrape":
                            scrape_metadata = {
                                "url": plan.tool_params.get("url", ""),
                                "title": "",
                                "content": tool_context,
                            }
                    else:
                        logger.warning("Tool %s failed: %s", tool_name, result.error)
                except Exception:
                    logger.exception("Tool %s raised an exception", tool_name)

        messages = await self.context_assembler.build(
            conversation_id, message_content, tool_context=tool_context
        )

        # Apply skill system prompt if a skill is selected
        if plan.skill and self.skill_registry:
            skill = self.skill_registry.get(plan.skill)
            if skill:
                messages[0]["content"] = skill.system_prompt

        response = await self.provider.complete(messages)
        return ExecuteResult(response=response, scrape_metadata=scrape_metadata)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core.py::TestExecutorWithSkill -v`
Expected: PASS (2/2)

**Step 5: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All pass (existing Executor tests don't pass `skill_registry`, which defaults to None)

**Step 6: Commit**

```bash
git add odigos/core/executor.py tests/test_core.py
git commit -m "feat: executor applies skill system prompt when plan.skill is set"
```

---

### Task 10: Wire everything into `main.py` and `Agent`

**Files:**
- Modify: `odigos/main.py`
- Modify: `odigos/core/agent.py`

**Step 1: Update `Agent.__init__` to accept and pass through new components**

In `odigos/core/agent.py`, add `skill_registry` parameter:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from odigos.channels.base import UniversalMessage
from odigos.core.context import ContextAssembler
from odigos.core.executor import Executor
from odigos.core.planner import Planner
from odigos.core.reflector import Reflector
from odigos.db import Database
from odigos.providers.base import LLMProvider

if TYPE_CHECKING:
    from odigos.memory.manager import MemoryManager
    from odigos.skills.registry import SkillRegistry
    from odigos.tools.registry import ToolRegistry


class Agent:
    """Main agent: receives messages, runs plan->execute->reflect loop."""

    def __init__(
        self,
        db: Database,
        provider: LLMProvider,
        agent_name: str = "Odigos",
        history_limit: int = 20,
        memory_manager: MemoryManager | None = None,
        personality_path: str = "data/personality.yaml",
        planner_provider: LLMProvider | None = None,
        tool_registry: ToolRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self.db = db
        self.planner = Planner(provider=planner_provider or provider)
        self.context_assembler = ContextAssembler(
            db,
            agent_name,
            history_limit,
            memory_manager=memory_manager,
            personality_path=personality_path,
        )
        self.executor = Executor(
            provider,
            self.context_assembler,
            tool_registry=tool_registry,
            skill_registry=skill_registry,
        )
        self.reflector = Reflector(db, memory_manager=memory_manager)
```

The rest of Agent stays the same.

**Step 2: Update `main.py` to initialize router, budget tracker, and skill registry**

```python
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from odigos.channels.telegram import TelegramChannel
from odigos.config import load_settings
from odigos.core.agent import Agent
from odigos.core.budget import BudgetTracker
from odigos.core.router import ModelRouter
from odigos.db import Database
from odigos.memory.graph import EntityGraph
from odigos.memory.manager import MemoryManager
from odigos.memory.resolver import EntityResolver
from odigos.memory.summarizer import ConversationSummarizer
from odigos.memory.vectors import VectorMemory
from odigos.providers.embeddings import EmbeddingProvider
from odigos.providers.openrouter import OpenRouterProvider
from odigos.skills.registry import SkillRegistry

# ... (logging setup same as before) ...

# Module-level references for cleanup
_db: Database | None = None
_provider: OpenRouterProvider | None = None
_embedder: EmbeddingProvider | None = None
_telegram: TelegramChannel | None = None
_searxng = None
_scraper = None
_router: ModelRouter | None = None
```

In the `lifespan` function, after initializing `_provider`, add:

```python
    # Initialize model router (wraps provider for free model pool)
    _router = ModelRouter(
        provider=_provider,
        free_pool=settings.router.free_pool,
        rate_limit_rpm=settings.router.rate_limit_rpm,
    )
    logger.info(
        "Model router initialized with %d free models",
        len(settings.router.free_pool),
    )

    # Initialize budget tracker
    budget_tracker = BudgetTracker(
        db=_db,
        daily_limit=settings.budget.daily_limit_usd,
        monthly_limit=settings.budget.monthly_limit_usd,
    )
    logger.info("Budget tracker initialized")
```

After the tool registry setup, add skill registry initialization:

```python
    # Initialize skill registry
    skill_registry = SkillRegistry()
    skill_registry.load_all(settings.skills.path)
    logger.info("Loaded %d skills", len(skill_registry.list()))
```

Update Agent initialization to use `_router` and pass `skill_registry`:

```python
    agent = Agent(
        db=_db,
        provider=_router,           # router instead of raw provider
        agent_name=settings.agent.name,
        memory_manager=memory_manager,
        personality_path=settings.personality.path,
        planner_provider=_router,    # router for planner too
        tool_registry=tool_registry,
        skill_registry=skill_registry,
    )
```

In shutdown, add router cleanup before provider:

```python
    if _router:
        await _router.close()
```

Remove the separate `_provider.close()` since router.close() delegates to provider.

**Step 3: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All pass

**Step 4: Lint and format**

Run: `uv run ruff check --fix && uv run ruff format`

**Step 5: Commit**

```bash
git add odigos/core/agent.py odigos/main.py
git commit -m "feat: wire router, budget tracker, and skill registry into main"
```

---

### Task 11: Final verification -- all tests, lint, smoke test

**Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass

**Step 2: Run lint**

Run: `uv run ruff check && uv run ruff format --check`
Expected: Clean

**Step 3: Quick smoke test that imports work**

Run:
```bash
uv run python -c "
from odigos.core.router import ModelRouter
from odigos.core.budget import BudgetTracker, BudgetStatus
from odigos.skills.registry import SkillRegistry, Skill
from odigos.core.context import estimate_tokens
from odigos.providers.base import LLMResponse
print('All imports OK')
print(f'LLMResponse fields: {[f.name for f in LLMResponse.__dataclass_fields__.values()]}')
print(f'estimate_tokens(\"hello world\") = {estimate_tokens(\"hello world\")}')
"
```

Expected:
```
All imports OK
LLMResponse fields: ['content', 'model', 'tokens_in', 'tokens_out', 'cost_usd', 'generation_id']
estimate_tokens("hello world") = 2
```

**Step 4: Commit any final fixes if needed**

---

## Summary

| Task | Component | What it does |
|------|-----------|-------------|
| 1 | Cost Tracking | Add `generation_id` to `LLMResponse`, extract from OpenRouter response |
| 2 | Cost Tracking | Create `BudgetTracker` with daily/monthly spend queries, warn at 80% |
| 3 | Config | Add `BudgetConfig`, `RouterConfig`, `ContextConfig`, `SkillsConfig` |
| 4 | Router | Create `ModelRouter` with free pool round-robin + rate limit rotation |
| 5 | Context | Add `estimate_tokens()` and token budget trimming to `ContextAssembler` |
| 6 | Skills | Create `SkillRegistry` and `Skill` dataclass with YAML frontmatter parsing |
| 7 | Skills | Create 3 built-in SKILL.md templates |
| 8 | Skills | Update Planner to select skills in classification |
| 9 | Skills | Update Executor to apply skill system prompts |
| 10 | Integration | Wire router, budget, skills into `main.py` and `Agent` |
| 11 | Verification | Full test suite, lint, smoke test |
