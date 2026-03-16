# Executable Skill Library Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let agents save working code as reusable tools that register in the tool list and can be called in the same or future conversations.

**Architecture:** Extend the Skill dataclass with code-related fields. New CodeSkillRunner tool wraps code skills and executes them in the existing SandboxProvider. CreateSkillTool and UpdateSkillTool get a `code` parameter. SkillRegistry scans for code skills at startup and registers CodeSkillRunner instances.

**Tech Stack:** Python, ast module (validation), existing SandboxProvider (bubblewrap)

**Spec:** `docs/superpowers/specs/2026-03-16-executable-skills-design.md`

---

## Chunk 1: CodeSkillRunner and Validation

### Task 1: Code validation module

**Files:**
- Create: `odigos/skills/code_validator.py`
- Create: `tests/test_code_validator.py`

- [ ] **Step 1: Write tests**

Create `tests/test_code_validator.py`:
```python
import pytest
from odigos.skills.code_validator import validate_skill_code


def test_valid_code():
    code = 'def run(ticker: str) -> str:\n    return f"Price: {ticker}"'
    params = {"ticker": {"type": "string"}}
    errors = validate_skill_code(code, params)
    assert errors == []


def test_missing_run_function():
    code = 'def helper(x):\n    return x'
    errors = validate_skill_code(code, {})
    assert any("run" in e for e in errors)


def test_syntax_error():
    code = 'def run(:\n    pass'
    errors = validate_skill_code(code, {})
    assert any("syntax" in e.lower() for e in errors)


def test_dangerous_import():
    code = 'def run() -> str:\n    import subprocess\n    return ""'
    errors = validate_skill_code(code, {})
    assert any("subprocess" in e for e in errors)


def test_parameter_mismatch():
    code = 'def run(x: str) -> str:\n    return x'
    params = {"ticker": {"type": "string"}}
    errors = validate_skill_code(code, params)
    assert any("parameter" in e.lower() for e in errors)


def test_multiple_run_functions():
    code = 'def run(a):\n    pass\ndef run(b):\n    pass'
    errors = validate_skill_code(code, {})
    assert errors == []  # Python allows redefinition, last wins
```

- [ ] **Step 2: Implement validator**

Create `odigos/skills/code_validator.py`:
```python
"""Validate skill code before saving."""
from __future__ import annotations

import ast

BLOCKED_IMPORTS = {"subprocess", "os.system", "ctypes", "importlib"}
BLOCKED_CALLS = {"eval", "exec", "__import__"}


def validate_skill_code(code: str, parameters: dict) -> list[str]:
    """Validate skill code. Returns list of error strings (empty = valid)."""
    errors = []

    # 1. Syntax check
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"Syntax error: {e}"]

    # 2. Find run() function
    run_funcs = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run"
    ]
    if not run_funcs:
        errors.append("Code must define a 'run()' function")
        return errors

    run_func = run_funcs[-1]  # last definition wins

    # 3. Check parameters match
    func_params = [arg.arg for arg in run_func.args.args]
    expected_params = list(parameters.keys()) if parameters else []
    if sorted(func_params) != sorted(expected_params):
        errors.append(
            f"Parameter mismatch: run() has {func_params}, "
            f"expected {expected_params}"
        )

    # 4. Check for dangerous imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in BLOCKED_IMPORTS or alias.name.split(".")[0] in BLOCKED_IMPORTS:
                    errors.append(f"Blocked import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module in BLOCKED_IMPORTS or node.module.split(".")[0] in BLOCKED_IMPORTS):
                errors.append(f"Blocked import: {node.module}")

    # 5. Check for dangerous calls
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
                errors.append(f"Blocked call: {node.func.id}")

    return errors
```

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/test_code_validator.py -xvs`
Expected: All 6 pass

- [ ] **Step 4: Commit**

```bash
git add odigos/skills/code_validator.py tests/test_code_validator.py
git commit -m "feat: add code validator for executable skills"
```

### Task 2: CodeSkillRunner tool

**Files:**
- Create: `odigos/tools/code_skill_runner.py`
- Create: `tests/test_code_skill_runner.py`

- [ ] **Step 1: Write tests**

Create `tests/test_code_skill_runner.py`:
```python
import pytest
from pathlib import Path
from odigos.tools.code_skill_runner import CodeSkillRunner


@pytest.fixture
def simple_skill(tmp_path):
    code_dir = tmp_path / "skills" / "code"
    code_dir.mkdir(parents=True)
    code_file = code_dir / "add_numbers.py"
    code_file.write_text('def run(a: str, b: str) -> str:\n    return str(int(a) + int(b))')

    return CodeSkillRunner(
        skill_name="add_numbers",
        skill_description="Add two numbers",
        code_path=str(code_file),
        parameters={"a": {"type": "string"}, "b": {"type": "string"}},
        timeout=5,
        allow_network=False,
    )


@pytest.mark.asyncio
async def test_execute_simple_skill(simple_skill):
    result = await simple_skill.execute({"a": "3", "b": "4"})
    assert result.success
    assert "7" in result.data


@pytest.mark.asyncio
async def test_execute_missing_code_file():
    runner = CodeSkillRunner(
        skill_name="missing",
        skill_description="Missing code",
        code_path="/nonexistent/path.py",
        parameters={},
        timeout=5,
        allow_network=False,
    )
    result = await runner.execute({})
    assert not result.success
    assert "not found" in result.error.lower()


def test_tool_metadata(simple_skill):
    assert simple_skill.name == "skill_add_numbers"
    assert simple_skill.description == "Add two numbers"
    assert "a" in simple_skill.parameters_schema["properties"]
    assert "b" in simple_skill.parameters_schema["properties"]
```

- [ ] **Step 2: Implement CodeSkillRunner**

Create `odigos/tools/code_skill_runner.py`:
```python
"""CodeSkillRunner -- executes saved code skills in the sandbox."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from odigos.providers.sandbox import SandboxProvider
from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class CodeSkillRunner(BaseTool):
    """Wraps a single executable code skill as a callable tool."""

    def __init__(
        self,
        skill_name: str,
        skill_description: str,
        code_path: str,
        parameters: dict,
        timeout: int = 10,
        allow_network: bool = False,
    ) -> None:
        self.name = f"skill_{skill_name}"
        self.description = skill_description
        self._code_path = Path(code_path)
        self._timeout = timeout
        self._allow_network = allow_network

        # Build JSON Schema from parameters dict
        props = {}
        required = []
        for param_name, param_info in (parameters or {}).items():
            props[param_name] = {
                "type": param_info.get("type", "string"),
                "description": param_info.get("description", ""),
            }
            required.append(param_name)

        self.parameters_schema = {
            "type": "object",
            "properties": props,
            "required": required,
        }

    async def execute(self, params: dict) -> ToolResult:
        if not self._code_path.exists():
            return ToolResult(
                success=False, data="",
                error=f"Skill code file not found: {self._code_path}",
            )

        # Read the skill code
        skill_code = self._code_path.read_text()

        # Build wrapper: define function, call it, print JSON result
        param_str = ", ".join(
            f"{k}={json.dumps(v)}" for k, v in params.items()
        )
        wrapper = f"""{skill_code}

import json as _json
try:
    _result = run({param_str})
    print(_json.dumps({{"success": True, "result": str(_result)}}))
except Exception as _e:
    print(_json.dumps({{"success": False, "error": str(_e)}}))
"""

        # Execute in a fresh sandbox with skill-specific settings
        sandbox = SandboxProvider(
            timeout=self._timeout,
            allow_network=self._allow_network,
        )
        result = await sandbox.execute(wrapper)

        if result.timed_out:
            return ToolResult(
                success=False, data="",
                error=f"Skill execution timed out after {self._timeout}s",
            )

        if result.exit_code != 0:
            return ToolResult(
                success=False, data=result.stdout,
                error=result.stderr or f"Skill exited with code {result.exit_code}",
            )

        # Parse JSON output
        try:
            output = json.loads(result.stdout.strip())
            if output.get("success"):
                return ToolResult(success=True, data=output["result"])
            else:
                return ToolResult(
                    success=False, data="",
                    error=output.get("error", "Skill execution failed"),
                )
        except (json.JSONDecodeError, KeyError):
            return ToolResult(success=True, data=result.stdout.strip())
```

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/test_code_skill_runner.py -xvs`
Expected: All 3 pass

- [ ] **Step 4: Commit**

```bash
git add odigos/tools/code_skill_runner.py tests/test_code_skill_runner.py
git commit -m "feat: add CodeSkillRunner tool for executing saved code skills"
```

---

## Chunk 2: Registry and Tool Integration

### Task 3: Extend Skill dataclass and SkillRegistry

**Files:**
- Modify: `odigos/skills/registry.py`
- Modify: `tests/test_skills.py`

- [ ] **Step 1: Extend Skill dataclass**

Add optional fields to the `Skill` dataclass in `odigos/skills/registry.py`:
```python
@dataclass
class Skill:
    name: str
    description: str
    tools: list[str]
    complexity: str
    system_prompt: str
    builtin: bool = False
    code: str | None = None          # path to .py file
    parameters: dict | None = None   # input parameter schema
    verified: bool = False
    timeout: int = 10
    allow_network: bool = False
```

- [ ] **Step 2: Update _parse_skill to read new fields**

In `_parse_skill`, after reading the existing fields, add:
```python
code=meta.get("code"),
parameters=meta.get("parameters"),
verified=meta.get("verified", False),
timeout=meta.get("timeout", 10),
allow_network=meta.get("allow_network", False),
```

- [ ] **Step 3: Add register_code_skills method**

Add to `SkillRegistry`:
```python
def register_code_skills(self, tool_registry) -> int:
    """Register CodeSkillRunner instances for all code skills. Returns count."""
    from odigos.tools.code_skill_runner import CodeSkillRunner

    count = 0
    for skill in self._skills.values():
        if not skill.code:
            continue
        code_path = Path(self.skills_dir) / ".." / skill.code if not Path(skill.code).is_absolute() else Path(skill.code)
        # Resolve relative to skills_dir parent (project root)
        code_path = (Path(self.skills_dir).parent / skill.code).resolve()
        if not code_path.exists():
            logger.warning("Code skill '%s' references missing file: %s", skill.name, code_path)
            continue

        tool_name = f"skill_{skill.name}"
        if tool_registry.get(tool_name):
            logger.warning("Tool name collision: '%s' already registered, skipping code skill", tool_name)
            continue

        runner = CodeSkillRunner(
            skill_name=skill.name,
            skill_description=skill.description,
            code_path=str(code_path),
            parameters=skill.parameters or {},
            timeout=skill.timeout,
            allow_network=skill.allow_network,
        )
        tool_registry.register(runner)
        count += 1
        logger.info("Registered code skill tool: %s", tool_name)

    return count
```

- [ ] **Step 4: Update create() to support code skills**

Extend the `create()` method to accept optional `code`, `parameters`, `timeout`, `allow_network` params. When `code` is provided:
- Validate via `validate_skill_code()`
- Write the `.py` file to `skills/code/{name}.py`
- Include `code`, `parameters`, `verified: false`, `timeout`, `allow_network` in the YAML frontmatter
- Return the skill with the new fields populated

- [ ] **Step 5: Update update() to support code changes**

Extend `update()` to accept optional `code` param. When provided:
- Validate via `validate_skill_code()`
- Overwrite the `.py` file
- Reset `verified` to `false` in the frontmatter
- Rewrite the `.md` file with updated frontmatter

- [ ] **Step 6: Update delete() to clean up code files**

In `delete()`, if the skill has a `code` field, also delete the `.py` file.

- [ ] **Step 7: Run tests**

Run: `.venv/bin/python -m pytest tests/test_skills.py tests/test_skill_manage.py -xvs`
Expected: All pass (existing + any new tests)

- [ ] **Step 8: Commit**

```bash
git add odigos/skills/registry.py
git commit -m "feat: extend SkillRegistry for executable code skills

Skill dataclass gains code, parameters, verified, timeout, allow_network.
create/update/delete handle code files. register_code_skills loads
CodeSkillRunner instances into the tool registry."
```

### Task 4: Wire up in main.py and update CreateSkillTool

**Files:**
- Modify: `odigos/main.py`
- Modify: `odigos/tools/skill_manage.py`

- [ ] **Step 1: Register code skills at startup**

In `odigos/main.py`, after `skill_registry.load_all(...)`, add:
```python
code_skill_count = skill_registry.register_code_skills(tool_registry)
if code_skill_count:
    logger.info("Registered %d code skill tools", code_skill_count)
```

Also ensure `skills/code/` directory is created at startup:
```python
Path("skills/code").mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2: Update CreateSkillTool parameters_schema**

In `odigos/tools/skill_manage.py`, add to CreateSkillTool's parameters_schema properties:
```python
"code": {
    "type": "string",
    "description": "Python code defining a run() function. The function receives parameters as keyword arguments and returns a string. When provided, the skill becomes an executable tool.",
},
"parameters": {
    "type": "object",
    "description": "Parameter schema for the code skill's run() function. Keys are parameter names, values have 'type' and 'description'.",
},
"timeout": {
    "type": "integer",
    "description": "Sandbox timeout in seconds (default 10, max 60).",
},
"allow_network": {
    "type": "boolean",
    "description": "Whether the skill can make network requests (default false).",
},
```

- [ ] **Step 3: Update CreateSkillTool.execute()**

When `params.get("code")` is provided:
1. Validate with `validate_skill_code(code, parameters)`
2. Call `self._registry.create(...)` with the code-related params
3. Register a CodeSkillRunner immediately in the tool registry
4. Return success message noting it's an executable skill

The tool registry needs to be passed to CreateSkillTool. Update `__init__` to accept an optional `tool_registry` parameter.

- [ ] **Step 4: Update UpdateSkillTool similarly**

Add `code` to UpdateSkillTool's parameters_schema. When provided, pass to `self._registry.update()`. Re-register the CodeSkillRunner if the tool registry is available.

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ --ignore=tests/e2e -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add odigos/main.py odigos/tools/skill_manage.py
git commit -m "feat: wire executable skills into startup and CreateSkillTool

Code skills register as tools at startup. CreateSkillTool validates
and saves code, registers CodeSkillRunner immediately."
```

---

## Chunk 3: Capabilities Update, Verification, and Deploy

### Task 5: Update capabilities prompt and add verification

**Files:**
- Modify: `data/agent/capabilities.md`
- Modify: `odigos/tools/code_skill_runner.py`
- Modify: `odigos/skills/registry.py`

- [ ] **Step 1: Update capabilities.md**

Add to `data/agent/capabilities.md` after the existing Skills section:
```markdown
**Executable Skills:** When you write code that solves a reusable problem
(API integrations, data transformations, recurring calculations), save it
as an executable skill using create_skill with the code parameter.
Good candidates: code you'd want to reuse if a similar question comes up.
Bad candidates: one-off scripts, conversation-specific logic.
The code must define a single `def run(...)` function that returns a string.
Provide a parameters dict describing the function's inputs.
```

- [ ] **Step 2: Add verified flag update on successful execution**

In `CodeSkillRunner.execute()`, after a successful result, check if verified is false and update:
```python
# After successful execution, mark as verified
if not self._verified:
    self._update_verified()
```

Add `_verified` to `__init__` and a `_update_verified()` method that reads the .md file, sets `verified: true` in the frontmatter, and rewrites it.

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ --ignore=tests/e2e -x -q`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add data/agent/capabilities.md odigos/tools/code_skill_runner.py odigos/skills/registry.py
git commit -m "feat: executable skills capabilities prompt and auto-verification

Agent is guided to save reusable code as executable skills.
Skills auto-verify on first successful execution."
```

### Task 6: Build, test, deploy

- [ ] **Step 1: Full test suite**

Run: `.venv/bin/python -m pytest tests/ --ignore=tests/e2e -x -q`

- [ ] **Step 2: Dashboard build** (no frontend changes, but rebuild for consistency)

Run: `cd dashboard && npm run build`

- [ ] **Step 3: Commit and push**

```bash
git add dashboard/dist/
git commit -m "build: rebuild dashboard"
git push
```

- [ ] **Step 4: Deploy to personal VPS**

```bash
ssh root@82.25.91.86 "export PATH=\$HOME/.local/bin:\$PATH && cd /opt/odigos && git pull && uv sync && systemctl restart odigos"
```

- [ ] **Step 5: Deploy to tester VPS**

```bash
ssh root@100.89.147.103 "cd /opt/odigos/repo && git pull && cd /opt/odigos && docker compose build --no-cache && docker compose down && docker compose up -d"
```
