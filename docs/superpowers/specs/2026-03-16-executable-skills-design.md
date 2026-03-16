# Executable Skill Library Design

## Goal

Extend the skills system so agents can save working code as reusable tools. When the agent writes code that solves a problem, it can package the code as an executable skill that appears in its tool list for future use. This is phase 1 of SAGE-inspired skill evolution (phases 2 and 3 -- skill usage tracking and task similarity detection -- follow in separate specs).

## Context

Today, skills are Markdown files in `skills/` with text instructions. The agent activates a skill to get behavioral guidance, but skills cannot execute code. When the agent writes useful code via CodeTool, that code is discarded after the conversation.

The SAGE paper (arxiv.org/html/2512.17102v2) demonstrates that agents improve significantly when they can save and reuse executable code across tasks. We adapt this for API-based LLMs (no RL fine-tuning) by letting the agent self-evaluate which code to save and auto-registering it as a callable tool.

## Skill Creation Flow

1. Agent executes code via CodeTool during normal conversation
2. Agent evaluates whether the code is reusable (guided by capabilities prompt)
3. Agent calls `CreateSkillTool` with a `code` parameter and a `parameters` dict describing the skill's input schema
4. CreateSkillTool validates the code structurally (see Validation section), writes the Markdown descriptor to `skills/{name}.md` and the Python function to `skills/code/{name}.py`
5. A `CodeSkillRunner` tool instance registers immediately in the tool registry (with name collision check against built-in tools)
6. Agent can call the new skill as a tool in the same conversation
7. On first successful execution, the skill's `verified` flag flips to `true`

## Skill File Structure

### Markdown descriptor (`skills/fetch_stock_price.md`)

```yaml
---
name: fetch_stock_price
description: Fetch current stock price for a ticker symbol
code: skills/code/fetch_stock_price.py
parameters:
  ticker:
    type: string
    description: Stock ticker symbol
verified: false
timeout: 15
allow_network: true
---
Use when the user asks about current stock prices. Returns the current
price from the configured API. Handles common ticker formats.
```

The Markdown body is a usage guide for the agent's context (same as today's text skills). The `code` frontmatter field links to the executable Python file. Existing frontmatter fields (`tools`, `complexity`) are optional and ignored for code skills.

### Code file (`skills/code/fetch_stock_price.py`)

```python
def run(ticker: str) -> str:
    import httpx
    resp = httpx.get(f"https://api.example.com/price/{ticker}")
    data = resp.json()
    return f"{ticker}: ${data['price']:.2f}"
```

Contract:
- One `def run(**params) -> str` function per file (synchronous -- the sandbox runs in a subprocess via `asyncio.create_subprocess_exec`, so the user code itself is sync while `CodeSkillRunner.execute()` is async per BaseTool contract)
- Parameters match the `parameters` frontmatter in the Markdown descriptor
- Returns a string result
- Runs in the CodeTool sandbox (bubblewrap isolation)
- Can import standard library and installed packages

## Components

### CodeSkillRunner (new tool class)

A tool class that wraps a single executable skill. One instance per code skill in the registry.

```
class CodeSkillRunner(BaseTool):
    name: str          # from skill frontmatter (prefixed with "skill_" to avoid collisions)
    description: str   # from skill frontmatter
    parameters_schema: dict  # generated from skill parameters frontmatter

    async execute(params) -> ToolResult:
        1. Read the .py file from the skill's code path
        2. Construct wrapper script:
           - Contains the skill's function definition (read from .py file)
           - Appends: import json; print(json.dumps({"result": run(**params)}))
        3. Create a SandboxProvider instance with the skill's timeout and allow_network settings
        4. Execute wrapper via sandbox.execute(code_string)
        5. Parse JSON output for result
        6. If success and not yet verified, update frontmatter verified=true
        7. Return ToolResult with the function's return value
        8. On error, return ToolResult with error (agent can fix and re-save)
```

The wrapper script approach means CodeSkillRunner constructs an inline Python string that:
1. Contains the skill's function definition (read from the .py file)
2. Calls `run()` with the provided params
3. Prints the result as JSON

CodeSkillRunner creates a fresh `SandboxProvider` per execution with the skill's `timeout` and `allow_network` settings, then calls `sandbox.execute(code_string)`. This uses the existing interface without modifying SandboxProvider.

### Sandbox configuration per skill

Each code skill can declare in frontmatter:
- `timeout: int` -- sandbox timeout in seconds (default: 10, max: 60)
- `allow_network: bool` -- whether the sandbox allows outbound network (default: false)

Skills that need HTTP access (API integrations) set `allow_network: true`. The SandboxProvider already supports both settings.

### SkillRegistry changes (`odigos/skills/registry.py`)

The existing SkillRegistry scans `skills/` for `.md` files. Extend it to:
- Detect skills with a `code` frontmatter field
- Validate the referenced `.py` file exists (skip registration if missing, log warning)
- For each, create a CodeSkillRunner instance and register it in the tool registry
- Support dynamic registration (when CreateSkillTool saves a new code skill mid-conversation)

### Skill dataclass changes (`odigos/skills/registry.py`)

Extend the existing `Skill` dataclass with optional fields:
- `code: str | None = None` -- path to the `.py` file
- `parameters: dict | None = None` -- input parameter schema
- `verified: bool = False` -- whether the code has been executed successfully
- `timeout: int = 10` -- sandbox timeout
- `allow_network: bool = False` -- sandbox network access

The `_parse_skill` method is updated to read these from frontmatter when present.

### CreateSkillTool changes (`odigos/tools/skill_manage.py`)

Extend to accept optional parameters:
- `code: str` -- the Python function source code
- `parameters: dict` -- the skill's input parameter schema

When `code` is provided:
- Validate the code structurally (see Validation section)
- Write the Python file to `skills/code/{name}.py`
- Add `code`, `parameters`, `verified: false`, `timeout`, `allow_network` to the Markdown frontmatter
- Create `skills/code/` directory if it doesn't exist
- Check for name collisions with built-in tools (prefix with `skill_` if collision)
- Register a CodeSkillRunner instance immediately in the tool registry

### UpdateSkillTool changes (`odigos/tools/skill_manage.py`)

Extend to accept an optional `code` parameter:
- When provided, overwrite the `.py` file
- Reset `verified` to `false` (code changed, needs re-verification)
- Re-register the CodeSkillRunner with updated code

When deleting a skill that has a `code` field, also delete the `.py` file in `skills/code/`.

### Capabilities prompt update

Update `data/agent/capabilities.md` to include guidance:

```
**Executable Skills:** When you write code that solves a reusable problem
(API integrations, data transformations, recurring calculations), save it
as an executable skill using CreateSkillTool with the code parameter.
Good candidates: code you'd want to reuse if a similar question comes up.
Bad candidates: one-off scripts, conversation-specific logic.
The code must define a single `def run(...)` function that returns a string.
```

## Validation

When CreateSkillTool receives a `code` parameter, validate before saving:

1. **Syntax check:** `ast.parse(code)` succeeds
2. **Structure check:** The AST contains exactly one function definition named `run`
3. **Signature check:** The `run` function's parameters match the `parameters` dict provided by the agent
4. **No dangerous imports:** Reject `os.system`, `subprocess.run`, `eval`, `exec` (these bypass the sandbox)

If validation fails, return a ToolResult with the specific error so the agent can fix and retry.

## What stays the same

- Text-only skills (no `code` field) work exactly as before
- ActivateSkillTool unchanged -- for text instruction skills
- Evolution engine can still propose changes to skill content via trials
- Skill files remain in `skills/` directory, code files in `skills/code/`
- Install scripts already create `skills/` directory

## Files Modified

| File | Change |
|---|---|
| `odigos/tools/skill_manage.py` | Extend CreateSkillTool and UpdateSkillTool with `code` and `parameters` params |
| `odigos/skills/registry.py` | Extend Skill dataclass, scan for code skills, register CodeSkillRunner instances |
| `odigos/tools/code_skill_runner.py` | New: CodeSkillRunner tool class |
| `data/agent/capabilities.md` | Add executable skills guidance |
| `tests/test_code_skill_runner.py` | New: tests for code skill execution |
| `tests/test_skill_manage.py` | Extend: tests for code parameter in create/update |

## Security

- Code skills run in the same sandbox as CodeTool (bubblewrap, timeout, memory limits)
- Only the specific `.py` file referenced in frontmatter is loaded -- no arbitrary file execution
- The `code` frontmatter path is validated to be within `skills/code/` (no path traversal)
- Structural validation rejects code without a proper `run()` function
- Dangerous imports (`os.system`, `subprocess`, `eval`, `exec`) are rejected at save time
- Skills created by the agent are subject to the same approval gates as any tool execution (if approval is enabled)
- `allow_network` defaults to `false` -- skills need explicit opt-in for network access

## Out of Scope (phases 2 and 3)

- Skill usage tracking and evaluation scoring (phase 2)
- Task similarity detection and proactive skill surfacing (phase 3)
- Skill sharing between agents (mesh networking)
- Automatic skill deprecation/cleanup
