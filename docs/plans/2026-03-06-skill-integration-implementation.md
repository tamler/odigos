# Skill Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire the existing SkillRegistry into the ReAct loop: skill catalog in system prompt, activate_skill tool, cost tagging via action_log.

**Architecture:** Three-level progressive disclosure. Level 1: compact catalog (name + description) always in the system prompt. Level 2: `activate_skill` tool loads full SKILL.md body as a system message in context. Executor tracks active skill for cost tagging and logs tool mismatches.

**Tech Stack:** Python 3.12, asyncio, aiosqlite

---

### Task 1: Add skill catalog to system prompt

**Files:**
- Modify: `odigos/personality/prompt_builder.py`
- Modify: `odigos/core/context.py`
- Test: `tests/test_core.py`

**Step 1: Write the failing tests**

Add to `tests/test_core.py`:

```python
from odigos.skills.registry import SkillRegistry, Skill


class TestSkillCatalogInContext:
    async def test_skill_catalog_in_system_prompt(self, db: Database):
        """Skill catalog appears in system prompt when skills are loaded."""
        skill_registry = SkillRegistry()
        skill_registry._skills = {
            "research": Skill(
                name="research",
                description="In-depth web research",
                tools=["web_search"],
                complexity="standard",
                system_prompt="Do research.",
            ),
            "chat": Skill(
                name="chat",
                description="General conversation",
                tools=[],
                complexity="light",
                system_prompt="Chat naturally.",
            ),
        }

        assembler = ContextAssembler(
            db=db,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
            skill_registry=skill_registry,
        )

        messages = await assembler.build("conv-1", "Hello")

        system_content = messages[0]["content"]
        assert "Available skills" in system_content
        assert "research" in system_content
        assert "In-depth web research" in system_content
        assert "chat" in system_content
        assert "General conversation" in system_content
        # Full body should NOT be in catalog
        assert "Do research." not in system_content

    async def test_no_skill_registry_still_works(self, db: Database):
        """Without skill_registry, context assembler works as before."""
        assembler = ContextAssembler(
            db=db,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
        )

        messages = await assembler.build("conv-1", "Hello")
        system_content = messages[0]["content"]
        assert "Available skills" not in system_content

    async def test_empty_skill_registry_no_catalog(self, db: Database):
        """Empty skill registry doesn't add catalog section."""
        skill_registry = SkillRegistry()

        assembler = ContextAssembler(
            db=db,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
            skill_registry=skill_registry,
        )

        messages = await assembler.build("conv-1", "Hello")
        system_content = messages[0]["content"]
        assert "Available skills" not in system_content
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_core.py::TestSkillCatalogInContext -v`
Expected: FAIL (ContextAssembler doesn't accept `skill_registry` yet)

**Step 3: Implement skill catalog**

Modify `odigos/personality/prompt_builder.py` — add `skill_catalog` parameter to `build_system_prompt`:

```python
def build_system_prompt(
    personality: Personality,
    memory_context: str = "",
    tool_context: str = "",
    skill_catalog: str = "",
) -> str:
    sections = []
    sections.append(_build_identity_section(personality))
    sections.append(_build_voice_section(personality))

    if memory_context:
        sections.append(memory_context)

    if tool_context:
        sections.append(tool_context)

    if skill_catalog:
        sections.append(skill_catalog)

    sections.append(ENTITY_EXTRACTION_INSTRUCTION)
    return "\n\n".join(sections)
```

Modify `odigos/core/context.py` — add `skill_registry` parameter and build catalog:

1. Add `skill_registry` parameter to `__init__` (optional, defaults to `None`)
2. Add TYPE_CHECKING import for `SkillRegistry`
3. In `build()`, build catalog string from skill_registry and pass to `build_system_prompt`

```python
# In TYPE_CHECKING block:
from odigos.skills.registry import SkillRegistry

# In __init__:
skill_registry: SkillRegistry | None = None,
# ...
self.skill_registry = skill_registry

# In build(), before building system prompt:
skill_catalog = ""
if self.skill_registry:
    skills = self.skill_registry.list()
    if skills:
        lines = ["## Available skills",
                 "Use activate_skill to load a skill's full instructions before starting the task."]
        for s in skills:
            lines.append(f"- **{s.name}**: {s.description}")
        skill_catalog = "\n".join(lines)

# Pass to build_system_prompt:
system_prompt = build_system_prompt(
    personality=personality,
    memory_context=memory_context,
    tool_context=tool_context,
    skill_catalog=skill_catalog,
)
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_core.py::TestSkillCatalogInContext -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest -v --tb=short`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add odigos/personality/prompt_builder.py odigos/core/context.py tests/test_core.py
git commit -m "feat: inject skill catalog into system prompt"
```

---

### Task 2: Create ActivateSkillTool

**Files:**
- Create: `odigos/tools/skill_tool.py`
- Test: `tests/test_skill_tool.py`

**Step 1: Write the failing tests**

Create `tests/test_skill_tool.py`:

```python
import pytest
from odigos.skills.registry import SkillRegistry, Skill
from odigos.tools.skill_tool import ActivateSkillTool


@pytest.fixture
def skill_registry():
    registry = SkillRegistry()
    registry._skills = {
        "research": Skill(
            name="research",
            description="In-depth research",
            tools=["web_search", "read_page"],
            complexity="standard",
            system_prompt="You are a thorough research assistant.\n1. Search\n2. Read\n3. Synthesize",
        ),
    }
    return registry


class TestActivateSkillTool:
    async def test_activate_existing_skill(self, skill_registry):
        tool = ActivateSkillTool(skill_registry=skill_registry)
        result = await tool.execute({"name": "research"})

        assert result.success is True
        assert "research" in result.data
        assert "activated" in result.data.lower()

    async def test_activate_nonexistent_skill(self, skill_registry):
        tool = ActivateSkillTool(skill_registry=skill_registry)
        result = await tool.execute({"name": "nonexistent"})

        assert result.success is False
        assert "not found" in result.error.lower()

    async def test_activate_missing_name(self, skill_registry):
        tool = ActivateSkillTool(skill_registry=skill_registry)
        result = await tool.execute({})

        assert result.success is False

    async def test_tool_metadata(self, skill_registry):
        tool = ActivateSkillTool(skill_registry=skill_registry)

        assert tool.name == "activate_skill"
        assert "skill" in tool.description.lower()
        assert "name" in tool.parameters_schema["properties"]

    async def test_last_activated_skill(self, skill_registry):
        """After activation, tool exposes the activated skill info."""
        tool = ActivateSkillTool(skill_registry=skill_registry)
        await tool.execute({"name": "research"})

        assert tool.last_activated_name == "research"
        assert tool.last_activated_prompt == "You are a thorough research assistant.\n1. Search\n2. Read\n3. Synthesize"
        assert tool.last_activated_tools == ["web_search", "read_page"]

    async def test_last_activated_cleared_on_new_call(self, skill_registry):
        """Each call resets the last activated info."""
        tool = ActivateSkillTool(skill_registry=skill_registry)
        await tool.execute({"name": "research"})
        await tool.execute({"name": "nonexistent"})

        assert tool.last_activated_name is None
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_skill_tool.py -v`
Expected: FAIL (module doesn't exist)

**Step 3: Implement ActivateSkillTool**

Create `odigos/tools/skill_tool.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.skills.registry import SkillRegistry


class ActivateSkillTool(BaseTool):
    """Tool that activates a skill by loading its full instructions."""

    name = "activate_skill"
    description = (
        "Load a skill's detailed instructions for the current task. "
        "Call this before starting a task that matches a skill in the catalog. "
        "The skill's instructions will be injected as context."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The name of the skill to activate (from the skill catalog).",
            },
        },
        "required": ["name"],
    }

    def __init__(self, skill_registry: SkillRegistry) -> None:
        self._registry = skill_registry
        self.last_activated_name: str | None = None
        self.last_activated_prompt: str | None = None
        self.last_activated_tools: list[str] | None = None

    async def execute(self, params: dict) -> ToolResult:
        # Reset state
        self.last_activated_name = None
        self.last_activated_prompt = None
        self.last_activated_tools = None

        name = params.get("name")
        if not name:
            return ToolResult(success=False, data="", error="Missing required parameter: name")

        skill = self._registry.get(name)
        if not skill:
            available = [s.name for s in self._registry.list()]
            return ToolResult(
                success=False,
                data="",
                error=f"Skill '{name}' not found. Available: {', '.join(available)}",
            )

        self.last_activated_name = skill.name
        self.last_activated_prompt = skill.system_prompt
        self.last_activated_tools = skill.tools

        return ToolResult(
            success=True,
            data=f"Skill '{name}' activated. Follow the instructions that will appear in context.",
        )
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_skill_tool.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/tools/skill_tool.py tests/test_skill_tool.py
git commit -m "feat: create ActivateSkillTool for on-demand skill loading"
```

---

### Task 3: Handle skill activation in Executor

**Files:**
- Modify: `odigos/core/executor.py`
- Test: `tests/test_react_loop.py`

**Step 1: Write the failing tests**

Add to `tests/test_react_loop.py`:

```python
from odigos.skills.registry import SkillRegistry, Skill
from odigos.tools.skill_tool import ActivateSkillTool


class TestSkillActivation:
    @pytest.fixture
    def skill_registry(self):
        registry = SkillRegistry()
        registry._skills = {
            "research": Skill(
                name="research",
                description="In-depth research",
                tools=["web_search", "read_page"],
                complexity="standard",
                system_prompt="You are a thorough research assistant.",
            ),
        }
        return registry

    @pytest.mark.asyncio
    async def test_skill_activation_injects_system_message(self, mock_provider, mock_assembler, skill_registry):
        """Activating a skill injects its body as a system message."""
        activate_tool = ActivateSkillTool(skill_registry=skill_registry)
        registry = ToolRegistry()
        registry.register(activate_tool)

        mock_provider.complete.side_effect = [
            LLMResponse(
                content="", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="activate_skill", arguments={"name": "research"})],
            ),
            LLMResponse(
                content="Research complete.", model="test",
                tokens_in=20, tokens_out=10, cost_usd=0.002,
            ),
        ]

        executor = Executor(
            provider=mock_provider,
            context_assembler=mock_assembler,
            tool_registry=registry,
            skill_registry=skill_registry,
        )
        result = await executor.execute("conv-1", "Research AI trends")

        assert result.response.content == "Research complete."
        # Verify second LLM call received system message with skill body
        second_call_messages = mock_provider.complete.call_args_list[1][0][0]
        system_msgs = [m for m in second_call_messages if m.get("role") == "system"
                       and "Active skill" in m.get("content", "")]
        assert len(system_msgs) == 1
        assert "thorough research assistant" in system_msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_tool_mismatch_logged(self, mock_provider, mock_assembler, skill_registry):
        """Using a tool not in the skill's tools list logs a mismatch."""
        activate_tool = ActivateSkillTool(skill_registry=skill_registry)
        mock_other_tool = AsyncMock(spec=BaseTool)
        mock_other_tool.name = "send_email"
        mock_other_tool.description = "Send email"
        mock_other_tool.parameters_schema = {"type": "object", "properties": {}}
        mock_other_tool.execute.return_value = ToolResult(success=True, data="Sent")

        registry = ToolRegistry()
        registry.register(activate_tool)
        registry.register(mock_other_tool)

        mock_provider.complete.side_effect = [
            LLMResponse(
                content="", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="activate_skill", arguments={"name": "research"})],
            ),
            LLMResponse(
                content="", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_2", name="send_email", arguments={"to": "a@b.com"})],
            ),
            LLMResponse(
                content="Done.", model="test",
                tokens_in=20, tokens_out=10, cost_usd=0.002,
            ),
        ]

        from odigos.db import Database

        db = AsyncMock(spec=Database)
        db.execute = AsyncMock()

        executor = Executor(
            provider=mock_provider,
            context_assembler=mock_assembler,
            tool_registry=registry,
            skill_registry=skill_registry,
            db=db,
        )
        await executor.execute("conv-1", "Research and email")

        # Check that action_log was called with mismatch info
        log_calls = [c for c in db.execute.call_args_list if "action_log" in str(c)]
        mismatch_calls = [c for c in log_calls if "skill_mismatch" in str(c)]
        assert len(mismatch_calls) >= 1

    @pytest.mark.asyncio
    async def test_active_skill_tagged_in_action_log(self, mock_provider, mock_assembler, skill_registry):
        """Tool calls during active skill include skill name in action_log."""
        activate_tool = ActivateSkillTool(skill_registry=skill_registry)
        mock_search = AsyncMock(spec=BaseTool)
        mock_search.name = "web_search"
        mock_search.description = "Search"
        mock_search.parameters_schema = {"type": "object", "properties": {}}
        mock_search.execute.return_value = ToolResult(success=True, data="Results")

        registry = ToolRegistry()
        registry.register(activate_tool)
        registry.register(mock_search)

        mock_provider.complete.side_effect = [
            LLMResponse(
                content="", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="activate_skill", arguments={"name": "research"})],
            ),
            LLMResponse(
                content="", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_2", name="web_search", arguments={"query": "test"})],
            ),
            LLMResponse(
                content="Found it.", model="test",
                tokens_in=20, tokens_out=10, cost_usd=0.002,
            ),
        ]

        from odigos.db import Database

        db = AsyncMock(spec=Database)
        db.execute = AsyncMock()

        executor = Executor(
            provider=mock_provider,
            context_assembler=mock_assembler,
            tool_registry=registry,
            skill_registry=skill_registry,
            db=db,
        )
        await executor.execute("conv-1", "Search something")

        # Check web_search action_log includes active_skill
        log_calls = [c for c in db.execute.call_args_list if "action_log" in str(c)]
        search_logs = [c for c in log_calls if "web_search" in str(c)]
        assert len(search_logs) >= 1
        assert "research" in str(search_logs[0])  # skill name in details
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_react_loop.py::TestSkillActivation -v`
Expected: FAIL (Executor doesn't accept `skill_registry` yet)

**Step 3: Implement skill activation in Executor**

Modify `odigos/core/executor.py`:

1. Add `skill_registry` parameter to `__init__` (optional, `None`)
2. Add TYPE_CHECKING import for `SkillRegistry`
3. Add active skill tracking: `_active_skill_name`, `_active_skill_tools`, `_pending_skill_prompt`
4. In `execute()`, reset active skill state at start
5. After executing tool calls in the loop, check for pending skill injection
6. In `_execute_tool()`, detect activate_skill success and set pending prompt
7. In `_log_action()`, include active skill and mismatch info

The updated `__init__`:

```python
def __init__(
    self,
    provider: LLMProvider,
    context_assembler: ContextAssembler,
    tool_registry: ToolRegistry | None = None,
    skill_registry: SkillRegistry | None = None,
    db: Database | None = None,
    max_tool_turns: int = MAX_TOOL_TURNS,
) -> None:
    self.provider = provider
    self.context_assembler = context_assembler
    self.tool_registry = tool_registry
    self.skill_registry = skill_registry
    self.db = db
    self._max_tool_turns = max_tool_turns
```

Add to TYPE_CHECKING block:

```python
from odigos.skills.registry import SkillRegistry
```

The updated `execute()` loop body (after existing tool call execution):

```python
# After appending all tool results for this turn:
# Check for skill activation — inject system message
if self._pending_skill_prompt:
    messages.append({
        "role": "system",
        "content": f"[Active skill instructions]:\n\n{self._pending_skill_prompt}",
    })
    self._pending_skill_prompt = None
```

Reset at top of `execute()`:

```python
self._active_skill_name: str | None = None
self._active_skill_tools: set[str] = set()
self._pending_skill_prompt: str | None = None
```

The updated `_execute_tool()` — after successful tool execution, add:

```python
# Detect skill activation
if tool_call.name == "activate_skill" and result.success:
    activate_tool = self.tool_registry.get("activate_skill")
    if activate_tool and hasattr(activate_tool, "last_activated_name"):
        self._active_skill_name = activate_tool.last_activated_name
        self._active_skill_tools = set(activate_tool.last_activated_tools or [])
        self._pending_skill_prompt = activate_tool.last_activated_prompt
```

The updated `_log_action()` — include active skill info:

```python
# Add active skill info
if self._active_skill_name:
    details["active_skill"] = self._active_skill_name
    if action_name != "activate_skill" and action_name not in self._active_skill_tools:
        details["skill_mismatch"] = True
        details["expected_tools"] = sorted(self._active_skill_tools)
        logger.info(
            "Tool mismatch: %s called during skill '%s' (expected: %s)",
            action_name, self._active_skill_name, self._active_skill_tools,
        )
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_react_loop.py::TestSkillActivation -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest -v --tb=short`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add odigos/core/executor.py tests/test_react_loop.py
git commit -m "feat: executor handles skill activation with system message injection and mismatch logging"
```

---

### Task 4: Thread skill_registry through Agent and main.py

**Files:**
- Modify: `odigos/core/agent.py`
- Modify: `odigos/main.py`
- Test: existing tests still pass

**Step 1: Update Agent to pass skill_registry to ContextAssembler and Executor**

In `odigos/core/agent.py`:

```python
# ContextAssembler init — add skill_registry:
self.context_assembler = ContextAssembler(
    db,
    agent_name,
    history_limit,
    memory_manager=memory_manager,
    personality_path=personality_path,
    summarizer=summarizer,
    skill_registry=skill_registry,
)

# Executor init — add skill_registry:
self.executor = Executor(
    provider,
    self.context_assembler,
    tool_registry=tool_registry,
    skill_registry=skill_registry,
    db=db,
    max_tool_turns=max_tool_turns,
)
```

**Step 2: Register ActivateSkillTool in main.py**

In `odigos/main.py`, after skill_registry.load_all():

```python
# Register skill activation tool
from odigos.tools.skill_tool import ActivateSkillTool

if skill_registry.list():
    activate_skill_tool = ActivateSkillTool(skill_registry=skill_registry)
    tool_registry.register(activate_skill_tool)
    logger.info("Skill activation tool registered")
```

**Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest -v --tb=short`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add odigos/core/agent.py odigos/main.py
git commit -m "feat: thread skill_registry through Agent and register activate_skill tool"
```

---

### Verification

After all tasks:
- System prompt includes skill catalog (name + description for each loaded skill)
- `activate_skill` tool is available to the LLM
- Activating a skill injects its full body as a system message
- Tool calls during an active skill are tagged with the skill name in action_log
- Tool mismatches (tool not in skill's declared tools list) are logged
- All existing tests still pass (backward compatible via optional params)
- Skill activation is wired end-to-end in main.py
