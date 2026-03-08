# Self-Skill-Building Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let the agent autonomously create and update skills via tools, so it can build reusable task instructions over time.

**Architecture:** Two new tools (`create_skill`, `update_skill`) wrap `SkillRegistry` methods. A `builtin` flag on the `Skill` dataclass protects shipped skills from modification. System prompt guidance tells the agent when to create skills.

**Tech Stack:** Python, pytest, YAML frontmatter `.md` files

---

### Task 1: Add `builtin` flag to Skill dataclass and SkillRegistry

**Files:**
- Modify: `odigos/skills/registry.py:13-19` (Skill dataclass)
- Modify: `odigos/skills/registry.py:28-39` (load_all method)
- Modify: `odigos/skills/registry.py:47-89` (create method)
- Test: `tests/test_skills.py`

**Step 1: Write failing tests**

Add to `tests/test_skills.py`:

```python
class TestSkillBuiltinFlag:
    def test_loaded_skills_are_builtin(self, skills_dir):
        registry = SkillRegistry()
        registry.load_all(str(skills_dir))
        for skill in registry.list():
            assert skill.builtin is True

    def test_created_skills_are_not_builtin(self, tmp_path):
        registry = SkillRegistry()
        skill = registry.create(
            name="my-skill",
            description="Test",
            system_prompt="Be helpful.",
            skills_dir=str(tmp_path),
        )
        assert skill.builtin is False

    def test_load_all_stores_skills_dir(self, skills_dir):
        registry = SkillRegistry()
        registry.load_all(str(skills_dir))
        assert registry.skills_dir == str(skills_dir)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_skills.py::TestSkillBuiltinFlag -v`
Expected: FAIL — `Skill.__init__() got unexpected keyword argument 'builtin'` or `AttributeError`

**Step 3: Implement changes**

In `odigos/skills/registry.py`:

1. Add `builtin: bool = False` to `Skill` dataclass (after `system_prompt`):

```python
@dataclass
class Skill:
    name: str
    description: str
    tools: list[str]
    complexity: str
    system_prompt: str
    builtin: bool = False
```

2. Store `skills_dir` in `load_all()` and mark loaded skills as builtin:

```python
def load_all(self, skills_dir: str) -> None:
    """Load all .md files with valid YAML frontmatter from the directory."""
    self.skills_dir = skills_dir
    path = Path(skills_dir)
    if not path.is_dir():
        logger.warning("Skills directory not found: %s", skills_dir)
        return

    for md_file in sorted(path.glob("*.md")):
        skill = self._parse_skill(md_file)
        if skill:
            skill.builtin = True
            self._skills[skill.name] = skill
            logger.info("Loaded skill: %s", skill.name)
```

3. Update `create()` — use `self.skills_dir` as default, remove the requirement:

```python
def create(
    self,
    name: str,
    description: str,
    system_prompt: str,
    tools: list[str] | None = None,
    complexity: str = "standard",
    skills_dir: str | None = None,
) -> Skill:
    """Create a new skill .md file and register it in the live registry."""
    target_dir = skills_dir or getattr(self, "skills_dir", None)
    if not target_dir:
        raise ValueError("skills_dir is required to write skill files")

    if not re.match(r"^[a-z0-9][a-z0-9_-]*$", name):
        raise ValueError(
            f"Invalid skill name: {name!r}. "
            "Use lowercase alphanumeric, hyphens, and underscores only."
        )

    meta = {
        "name": name,
        "description": description,
        "tools": tools or [],
        "complexity": complexity,
    }
    content = f"---\n{yaml.dump(meta, default_flow_style=False)}---\n{system_prompt}\n"

    path = Path(target_dir) / f"{name}.md"
    if not path.resolve().is_relative_to(Path(target_dir).resolve()):
        raise ValueError("Skill path escapes skills directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)

    skill = Skill(
        name=name,
        description=description,
        tools=tools or [],
        complexity=complexity,
        system_prompt=system_prompt,
        builtin=False,
    )
    self._skills[name] = skill
    logger.info("Created skill: %s at %s", name, path)
    return skill
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_skills.py -v`
Expected: All pass (old tests unaffected since `builtin` defaults to `False`)

**Step 5: Commit**

```bash
git add odigos/skills/registry.py tests/test_skills.py
git commit -m "feat: add builtin flag to Skill dataclass and store skills_dir"
```

---

### Task 2: Add `SkillRegistry.update()` method

**Files:**
- Modify: `odigos/skills/registry.py` (add `update()` method after `create()`)
- Test: `tests/test_skills.py`

**Step 1: Write failing tests**

Add to `tests/test_skills.py`:

```python
class TestSkillRegistryUpdate:
    def test_update_description(self, tmp_path):
        registry = SkillRegistry()
        registry.create(
            name="my-skill",
            description="Original",
            system_prompt="Be helpful.",
            skills_dir=str(tmp_path),
        )
        updated = registry.update(name="my-skill", description="Updated description")
        assert updated.description == "Updated description"
        assert registry.get("my-skill").description == "Updated description"

    def test_update_instructions(self, tmp_path):
        registry = SkillRegistry()
        registry.create(
            name="my-skill",
            description="Test",
            system_prompt="Be helpful.",
            skills_dir=str(tmp_path),
        )
        updated = registry.update(name="my-skill", instructions="New instructions here.")
        assert updated.system_prompt == "New instructions here."

    def test_update_persists_to_disk(self, tmp_path):
        registry = SkillRegistry()
        registry.create(
            name="my-skill",
            description="Test",
            system_prompt="Be helpful.",
            skills_dir=str(tmp_path),
        )
        registry.update(name="my-skill", instructions="Updated on disk.")

        # Reload from disk
        registry2 = SkillRegistry()
        registry2.load_all(str(tmp_path))
        skill = registry2.get("my-skill")
        assert skill.system_prompt == "Updated on disk."

    def test_update_rejects_builtin(self, skills_dir):
        registry = SkillRegistry()
        registry.load_all(str(skills_dir))
        with pytest.raises(ValueError, match="built-in"):
            registry.update(name="research-deep-dive", description="Hacked")

    def test_update_rejects_nonexistent(self, tmp_path):
        registry = SkillRegistry()
        registry.skills_dir = str(tmp_path)
        with pytest.raises(ValueError, match="not found"):
            registry.update(name="nonexistent", description="Nope")

    def test_update_partial_preserves_other_fields(self, tmp_path):
        registry = SkillRegistry()
        registry.create(
            name="my-skill",
            description="Original desc",
            system_prompt="Original prompt.",
            tools=["web_search"],
            complexity="standard",
            skills_dir=str(tmp_path),
        )
        updated = registry.update(name="my-skill", description="New desc")
        assert updated.description == "New desc"
        assert updated.system_prompt == "Original prompt."
        assert updated.tools == ["web_search"]
        assert updated.complexity == "standard"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_skills.py::TestSkillRegistryUpdate -v`
Expected: FAIL — `AttributeError: 'SkillRegistry' object has no attribute 'update'`

**Step 3: Implement `update()` method**

Add after the `create()` method in `odigos/skills/registry.py`:

```python
def update(
    self,
    name: str,
    description: str | None = None,
    instructions: str | None = None,
    tools: list[str] | None = None,
    complexity: str | None = None,
) -> Skill:
    """Update an existing agent-created skill. Built-in skills cannot be modified."""
    skill = self._skills.get(name)
    if not skill:
        raise ValueError(f"Skill '{name}' not found")
    if skill.builtin:
        raise ValueError(f"Cannot modify built-in skill '{name}'")

    if description is not None:
        skill.description = description
    if instructions is not None:
        skill.system_prompt = instructions
    if tools is not None:
        skill.tools = tools
    if complexity is not None:
        skill.complexity = complexity

    # Rewrite file on disk
    target_dir = getattr(self, "skills_dir", None)
    if target_dir:
        meta = {
            "name": skill.name,
            "description": skill.description,
            "tools": skill.tools,
            "complexity": skill.complexity,
        }
        content = f"---\n{yaml.dump(meta, default_flow_style=False)}---\n{skill.system_prompt}\n"
        path = Path(target_dir) / f"{name}.md"
        path.write_text(content)

    logger.info("Updated skill: %s", name)
    return skill
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_skills.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add odigos/skills/registry.py tests/test_skills.py
git commit -m "feat: add SkillRegistry.update() with builtin protection"
```

---

### Task 3: Create `CreateSkillTool` and `UpdateSkillTool`

**Files:**
- Create: `odigos/tools/skill_manage.py`
- Create: `tests/test_skill_manage.py`

**Step 1: Write failing tests**

Create `tests/test_skill_manage.py`:

```python
import pytest

from odigos.skills.registry import SkillRegistry
from odigos.tools.skill_manage import CreateSkillTool, UpdateSkillTool


@pytest.fixture
def registry_with_dir(tmp_path):
    registry = SkillRegistry()
    registry.load_all(str(tmp_path))
    return registry


@pytest.fixture
def registry_with_builtin(tmp_path):
    skill_file = tmp_path / "builtin-skill.md"
    skill_file.write_text(
        "---\n"
        "name: builtin-skill\n"
        "description: A built-in skill\n"
        "tools: []\n"
        "complexity: light\n"
        "---\n"
        "Built-in instructions.\n"
    )
    registry = SkillRegistry()
    registry.load_all(str(tmp_path))
    return registry


class TestCreateSkillTool:
    @pytest.mark.asyncio
    async def test_create_skill_success(self, registry_with_dir):
        tool = CreateSkillTool(skill_registry=registry_with_dir)
        result = await tool.execute({
            "name": "daily-digest",
            "description": "Summarize the day",
            "instructions": "Review today's conversations and create a summary.",
        })
        assert result.success is True
        assert "daily-digest" in result.data
        assert registry_with_dir.get("daily-digest") is not None

    @pytest.mark.asyncio
    async def test_create_skill_invalid_name(self, registry_with_dir):
        tool = CreateSkillTool(skill_registry=registry_with_dir)
        result = await tool.execute({
            "name": "Bad Name!",
            "description": "Test",
            "instructions": "Test.",
        })
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_create_skill_missing_fields(self, registry_with_dir):
        tool = CreateSkillTool(skill_registry=registry_with_dir)
        result = await tool.execute({"name": "test"})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_create_skill_with_optional_fields(self, registry_with_dir):
        tool = CreateSkillTool(skill_registry=registry_with_dir)
        result = await tool.execute({
            "name": "research-v2",
            "description": "Better research",
            "instructions": "Search thoroughly.",
            "tools": ["web_search", "read_page"],
            "complexity": "heavy",
        })
        assert result.success is True
        skill = registry_with_dir.get("research-v2")
        assert skill.tools == ["web_search", "read_page"]
        assert skill.complexity == "heavy"

    @pytest.mark.asyncio
    async def test_tool_metadata(self, registry_with_dir):
        tool = CreateSkillTool(skill_registry=registry_with_dir)
        assert tool.name == "create_skill"
        assert "name" in tool.parameters_schema["properties"]
        assert "description" in tool.parameters_schema["properties"]
        assert "instructions" in tool.parameters_schema["properties"]


class TestUpdateSkillTool:
    @pytest.mark.asyncio
    async def test_update_skill_success(self, registry_with_dir):
        # First create a skill
        create_tool = CreateSkillTool(skill_registry=registry_with_dir)
        await create_tool.execute({
            "name": "my-skill",
            "description": "Original",
            "instructions": "Original instructions.",
        })

        tool = UpdateSkillTool(skill_registry=registry_with_dir)
        result = await tool.execute({
            "name": "my-skill",
            "description": "Updated description",
        })
        assert result.success is True
        assert registry_with_dir.get("my-skill").description == "Updated description"

    @pytest.mark.asyncio
    async def test_update_builtin_rejected(self, registry_with_builtin):
        tool = UpdateSkillTool(skill_registry=registry_with_builtin)
        result = await tool.execute({
            "name": "builtin-skill",
            "description": "Hacked",
        })
        assert result.success is False
        assert "built-in" in result.error.lower()

    @pytest.mark.asyncio
    async def test_update_nonexistent_rejected(self, registry_with_dir):
        tool = UpdateSkillTool(skill_registry=registry_with_dir)
        result = await tool.execute({
            "name": "nonexistent",
            "description": "Nope",
        })
        assert result.success is False

    @pytest.mark.asyncio
    async def test_update_missing_name(self, registry_with_dir):
        tool = UpdateSkillTool(skill_registry=registry_with_dir)
        result = await tool.execute({"description": "No name given"})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_tool_metadata(self, registry_with_dir):
        tool = UpdateSkillTool(skill_registry=registry_with_dir)
        assert tool.name == "update_skill"
        assert "name" in tool.parameters_schema["properties"]
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_skill_manage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'odigos.tools.skill_manage'`

**Step 3: Implement the tools**

Create `odigos/tools/skill_manage.py`:

```python
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class CreateSkillTool(BaseTool):
    """Tool that creates a new reusable skill."""

    name = "create_skill"
    description = (
        "Create a new reusable skill with instructions for a specific task type. "
        "Use this when you notice a recurring pattern that would benefit from "
        "standardized instructions. The skill will be immediately available."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Lowercase name with hyphens/underscores (e.g. 'daily-digest').",
            },
            "description": {
                "type": "string",
                "description": "One-line description of what the skill does.",
            },
            "instructions": {
                "type": "string",
                "description": "Full instructions the agent should follow when this skill is activated.",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of tool names this skill typically uses (optional).",
            },
            "complexity": {
                "type": "string",
                "enum": ["light", "standard", "heavy"],
                "description": "Expected complexity level (default: standard).",
            },
        },
        "required": ["name", "description", "instructions"],
    }

    def __init__(self, skill_registry: SkillRegistry) -> None:
        self._registry = skill_registry

    async def execute(self, params: dict) -> ToolResult:
        name = params.get("name")
        description = params.get("description")
        instructions = params.get("instructions")

        if not name or not description or not instructions:
            return ToolResult(
                success=False,
                data="",
                error="Missing required parameters: name, description, and instructions are all required.",
            )

        try:
            skill = self._registry.create(
                name=name,
                description=description,
                system_prompt=instructions,
                tools=params.get("tools"),
                complexity=params.get("complexity", "standard"),
            )
        except ValueError as e:
            return ToolResult(success=False, data="", error=str(e))

        return ToolResult(
            success=True,
            data=f"Skill '{skill.name}' created and available in the catalog.",
        )


class UpdateSkillTool(BaseTool):
    """Tool that updates an existing agent-created skill."""

    name = "update_skill"
    description = (
        "Update an existing skill you created. Use this to refine instructions "
        "based on corrections or learned improvements. Cannot modify built-in skills."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the skill to update.",
            },
            "description": {
                "type": "string",
                "description": "New one-line description (optional).",
            },
            "instructions": {
                "type": "string",
                "description": "New full instructions (optional).",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "New list of tool names (optional).",
            },
            "complexity": {
                "type": "string",
                "enum": ["light", "standard", "heavy"],
                "description": "New complexity level (optional).",
            },
        },
        "required": ["name"],
    }

    def __init__(self, skill_registry: SkillRegistry) -> None:
        self._registry = skill_registry

    async def execute(self, params: dict) -> ToolResult:
        name = params.get("name")
        if not name:
            return ToolResult(
                success=False, data="", error="Missing required parameter: name"
            )

        try:
            skill = self._registry.update(
                name=name,
                description=params.get("description"),
                instructions=params.get("instructions"),
                tools=params.get("tools"),
                complexity=params.get("complexity"),
            )
        except ValueError as e:
            return ToolResult(success=False, data="", error=str(e))

        return ToolResult(
            success=True,
            data=f"Skill '{skill.name}' updated.",
        )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_skill_manage.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add odigos/tools/skill_manage.py tests/test_skill_manage.py
git commit -m "feat: add CreateSkillTool and UpdateSkillTool"
```

---

### Task 4: Add skill creation guidance to system prompt

**Files:**
- Modify: `odigos/personality/prompt_builder.py:1-9` (add constant)
- Modify: `odigos/personality/prompt_builder.py:58-61` (inject after skill catalog)
- Test: `tests/test_prompt_builder.py`

**Step 1: Write failing tests**

Add to `tests/test_prompt_builder.py`:

```python
class TestSkillCreationInstruction:
    def test_skill_creation_instruction_present(self, sample_personality):
        prompt = build_system_prompt(sample_personality)
        assert "create reusable skills" in prompt.lower() or "create_skill" in prompt.lower()

    def test_skill_creation_after_catalog(self, sample_personality):
        prompt = build_system_prompt(
            sample_personality,
            skill_catalog="## Available skills\n- **research**: Deep research",
        )
        catalog_pos = prompt.find("Available skills")
        creation_pos = prompt.find("create_skill") if "create_skill" in prompt else prompt.find("create reusable skills")
        assert catalog_pos < creation_pos
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_prompt_builder.py::TestSkillCreationInstruction -v`
Expected: FAIL — assertion error, instruction not found

**Step 3: Implement**

Add the constant to `odigos/personality/prompt_builder.py` after `CORRECTION_DETECTION_INSTRUCTION`:

```python
SKILL_CREATION_INSTRUCTION = """You can create reusable skills for task types you encounter repeatedly using the create_skill tool. A skill is a set of instructions that guide your behavior for a specific kind of task. Create a skill when you notice you've handled the same type of request multiple times with similar steps. Use update_skill to refine a skill you created when you receive corrections or learn better approaches. When you create or update a skill, mention it briefly in your response so the user is aware."""
```

Insert it after the skill catalog section (section 5) in `build_system_prompt()`. Add as new section 6, shifting corrections to 7, correction detection to 8, entity extraction to 9:

```python
    # 5. Skill catalog (optional)
    if skill_catalog:
        sections.append(skill_catalog)

    # 6. Skill creation guidance (always)
    sections.append(SKILL_CREATION_INSTRUCTION)

    # 7. Learned corrections (optional)
    if corrections_context:
        sections.append(corrections_context)

    # 8. Correction detection (always)
    sections.append(CORRECTION_DETECTION_INSTRUCTION)

    # 9. Entity extraction (always)
    sections.append(ENTITY_EXTRACTION_INSTRUCTION)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_prompt_builder.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add odigos/personality/prompt_builder.py tests/test_prompt_builder.py
git commit -m "feat: add skill creation guidance to system prompt"
```

---

### Task 5: Wire tools into main.py

**Files:**
- Modify: `odigos/main.py:175-181` (skill tool registration block)

**Step 1: Implement**

Replace the skill tool registration block in `main.py`:

```python
    # Register skill tools (activation, creation, update)
    from odigos.tools.skill_tool import ActivateSkillTool
    from odigos.tools.skill_manage import CreateSkillTool, UpdateSkillTool

    activate_skill_tool = ActivateSkillTool(skill_registry=skill_registry)
    tool_registry.register(activate_skill_tool)

    create_skill_tool = CreateSkillTool(skill_registry=skill_registry)
    tool_registry.register(create_skill_tool)

    update_skill_tool = UpdateSkillTool(skill_registry=skill_registry)
    tool_registry.register(update_skill_tool)

    logger.info("Skill tools registered (activate, create, update)")
```

Note: Remove the `if skill_registry.list():` guard — the create/update tools should be available even when no skills exist yet (the agent needs them to create the first skill).

**Step 2: Run full test suite**

Run: `pytest -x -q`
Expected: All tests pass

**Step 3: Commit**

```bash
git add odigos/main.py
git commit -m "feat: wire CreateSkillTool and UpdateSkillTool into main.py"
```
