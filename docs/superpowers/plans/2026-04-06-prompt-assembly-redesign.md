# Prompt Assembly Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dump-everything prompt builder with a planner-driven assembler that builds minimal, query-specific system prompts (~300-1500 chars instead of 13K).

**Architecture:** The classifier is enhanced into a query planner that returns needs flags and tool_hint. The context assembler reads the plan and only loads what's flagged. The prompt builder is simplified to concatenate identity + tool instruction + selected sections. Tool list is find_tools + hinted tool.

**Tech Stack:** Python 3.12, aiosqlite, pytest

**Spec:** `docs/superpowers/specs/2026-04-06-prompt-assembly-redesign.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `odigos/core/classifier.py` | Enhanced to return QueryPlan with needs, tool_hint, intent |
| `odigos/core/context.py` | Rewritten build() — planner-driven, budget-enforced |
| `odigos/core/executor.py` | Build tool list from plan.tool_hint + find_tools |
| `odigos/core/agent.py` | Pass recent_turns to classifier and assembler |
| `odigos/api/ws.py` | Track last 3 turns in WebSocket session |
| `odigos/personality/prompt_builder.py` | Simplified — just concatenate parts |
| `data/prompts/classifier.md` | New classifier prompt with tool catalog and plan output |
| `tests/test_classifier_plan.py` | Tests for new planner output |
| `tests/test_prompt_assembly.py` | Tests for budget-driven assembly |

---

### Task 1: Enhanced classifier output (QueryPlan)

The classifier currently returns `QueryAnalysis`. Add `QueryPlan` that extends it with needs flags, tool_hint, and response_style.

**Files:**
- Modify: `odigos/core/classifier.py`
- Create: `tests/test_classifier_plan.py`

- [ ] **Step 1: Write tests for QueryPlan**

Create `tests/test_classifier_plan.py`:

```python
"""Tests for the enhanced query planner output."""
import pytest
from odigos.core.classifier import QueryPlan, Needs


class TestNeeds:
    def test_defaults_all_false(self):
        n = Needs()
        assert n.rag is False
        assert n.user_profile is False
        assert n.user_facts is False
        assert n.history is False
        assert n.experiences is False

    def test_from_dict(self):
        n = Needs.from_dict({"rag": True, "history": True})
        assert n.rag is True
        assert n.history is True
        assert n.user_profile is False


class TestQueryPlan:
    def test_basic_fields(self):
        plan = QueryPlan(
            classification="creative",
            confidence=0.9,
            intent="generate_music",
            tool_hint="generate_music",
            needs=Needs(experiences=True),
            response_style="brief",
            complexity="single_tool",
        )
        assert plan.tool_hint == "generate_music"
        assert plan.needs.experiences is True
        assert plan.needs.rag is False

    def test_default_plan(self):
        """Default plan has no context needs — minimal prompt."""
        plan = QueryPlan.default()
        assert plan.classification == "standard"
        assert plan.tool_hint is None
        assert plan.needs.rag is False
        assert plan.needs.history is False
        assert plan.response_style == "brief"

    def test_from_classifier_json(self):
        """Parse the JSON the classifier LLM returns."""
        raw = {
            "classification": "creative",
            "confidence": 0.9,
            "intent": "generate_music",
            "tool_hint": "generate_music",
            "needs": {"rag": False, "experiences": True},
            "search_queries": [],
            "response_style": "brief",
            "complexity": "single_tool",
        }
        plan = QueryPlan.from_dict(raw)
        assert plan.classification == "creative"
        assert plan.tool_hint == "generate_music"
        assert plan.needs.experiences is True
        assert plan.needs.rag is False
        assert plan.search_queries == []

    def test_from_dict_handles_missing_fields(self):
        """Gracefully handle missing fields from LLM response."""
        raw = {"classification": "simple", "confidence": 0.8}
        plan = QueryPlan.from_dict(raw)
        assert plan.classification == "simple"
        assert plan.tool_hint is None
        assert plan.needs.rag is False
        assert plan.response_style == "brief"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_classifier_plan.py -v`
Expected: FAIL — QueryPlan and Needs don't exist

- [ ] **Step 3: Implement QueryPlan and Needs**

Add to `odigos/core/classifier.py` (after the existing QueryAnalysis dataclass):

```python
@dataclass
class Needs:
    """What context sections the assembler should load."""
    rag: bool = False
    user_profile: bool = False
    user_facts: bool = False
    history: bool = False
    experiences: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> Needs:
        return cls(
            rag=d.get("rag", False),
            user_profile=d.get("user_profile", False),
            user_facts=d.get("user_facts", False),
            history=d.get("history", False),
            experiences=d.get("experiences", False),
        )


@dataclass
class QueryPlan:
    """Full assembly plan produced by the query planner."""
    classification: str
    confidence: float
    intent: str = ""
    tool_hint: str | None = None
    needs: Needs = field(default_factory=Needs)
    search_queries: list[str] = field(default_factory=list)
    sub_questions: list[str] = field(default_factory=list)
    response_style: str = "brief"
    complexity: str = "conversation"
    entities: list[str] = field(default_factory=list)
    tier: int = 1
    similarity_hint: str | None = None

    @classmethod
    def default(cls) -> QueryPlan:
        return cls(classification="standard", confidence=0.5, response_style="brief")

    @classmethod
    def from_dict(cls, d: dict) -> QueryPlan:
        needs_raw = d.get("needs", {})
        return cls(
            classification=d.get("classification", "standard"),
            confidence=d.get("confidence", 0.5),
            intent=d.get("intent", ""),
            tool_hint=d.get("tool_hint"),
            needs=Needs.from_dict(needs_raw) if isinstance(needs_raw, dict) else Needs(),
            search_queries=d.get("search_queries", []),
            sub_questions=d.get("sub_questions", []),
            response_style=d.get("response_style", "brief"),
            complexity=d.get("complexity", "conversation"),
            entities=d.get("entities", []),
        )
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_classifier_plan.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add odigos/core/classifier.py tests/test_classifier_plan.py
git commit -m "feat(classifier): add QueryPlan and Needs dataclasses for planner output"
```

---

### Task 2: Update classifier prompt and parsing

Update the classifier to return QueryPlan instead of QueryAnalysis. Add the tool catalog to the classifier prompt. Accept recent_turns as input.

**Files:**
- Modify: `odigos/core/classifier.py`
- Modify: `data/prompts/classifier.md`

- [ ] **Step 1: Build tool catalog generator**

Add a method to the `QueryClassifier` class that builds the lightweight tool catalog from the registry:

```python
def _build_tool_catalog(self) -> str:
    """Build lightweight tool index for the classifier prompt."""
    if not self.tool_registry:
        return ""
    lines = []
    for tool in self.tool_registry.list():
        if tool.name == "find_tools":
            continue
        desc = tool.description.split(".")[0]  # first sentence only
        lines.append(f"{tool.name}: {desc}")
    return "\n".join(lines)
```

The tool_registry needs to be passed to the classifier. Check how the classifier is instantiated in bootstrap.py and add `tool_registry` parameter.

- [ ] **Step 2: Update classifier prompt**

Replace `data/prompts/classifier.md` with:

```markdown
Classify this user message and create an execution plan. Respond ONLY with valid JSON.

Recent conversation:
{recent_turns}

Current message: "{message}"

Available tools:
{tool_catalog}

Respond with:
{{"classification": "simple|standard|document_query|complex|planning|creative", "confidence": 0.85, "intent": "what the user wants done", "tool_hint": "tool_name_or_null", "needs": {{"rag": false, "user_profile": false, "user_facts": false, "history": false, "experiences": false}}, "search_queries": [], "response_style": "brief|detailed|step_by_step", "complexity": "single_tool|multi_step|conversation"}}

Rules:
- tool_hint: pick the single most likely tool from the list above. null if no tool needed.
- needs.rag: true only if the answer requires searching documents or past conversations
- needs.user_profile: true only if the answer depends on knowing the user personally
- needs.user_facts: true only if the user references something they told the agent before
- needs.history: true only if this message references earlier messages ("do it again", "change that")
- needs.experiences: true if using a tool (past lessons help)
- response_style: "brief" for simple requests, "detailed" for research/analysis, "step_by_step" for planning
- classification "creative" for any generation request (images, music, code, documents)
```

- [ ] **Step 3: Update classify() to accept recent_turns and return QueryPlan**

Modify the `classify()` method:
- Accept `recent_turns: list[dict] | None = None` parameter
- Format recent_turns into the prompt template
- Parse the LLM response into `QueryPlan.from_dict()` instead of the current manual parsing
- Keep the heuristic path (returns a basic QueryPlan with default needs)
- Keep the fallback (returns `QueryPlan.default()`)

The `_classify_llm()` method needs to accept and format `recent_turns` and `tool_catalog`.

- [ ] **Step 4: Update heuristic classification to return QueryPlan**

The `_classify_heuristic()` method currently returns a string or None. Update it to return `QueryPlan | None` with appropriate default needs. Simple greetings get all needs false.

- [ ] **Step 5: Pass tool_registry to classifier in bootstrap**

Read `odigos/bootstrap.py` and find where the classifier is created. Add `tool_registry=self.container.tool_registry` parameter.

- [ ] **Step 6: Verify syntax and run tests**

Run: `python3 -c "from odigos.core.classifier import QueryClassifier; print('OK')"`
Run: `python3 -m pytest tests/test_classifier_plan.py -v`

- [ ] **Step 7: Commit**

```bash
git add odigos/core/classifier.py data/prompts/classifier.md odigos/bootstrap.py
git commit -m "feat(classifier): query planner with tool catalog and needs flags"
```

---

### Task 3: Rewrite context assembler (build method)

Replace the 13-parallel-query build() with the planner-driven, budget-enforced assembler.

**Files:**
- Modify: `odigos/core/context.py`
- Create: `tests/test_prompt_assembly.py`

- [ ] **Step 1: Write tests for budget-driven assembly**

Create `tests/test_prompt_assembly.py`:

```python
"""Tests for planner-driven prompt assembly."""
import pytest
from odigos.core.classifier import QueryPlan, Needs


class TestBudgetAssembly:
    def test_minimal_prompt_for_simple_request(self):
        """Simple request gets identity + tool instruction only."""
        plan = QueryPlan(classification="simple", confidence=1.0, needs=Needs())
        # The assembled prompt should be < 500 chars
        # (actual test will call the assembler once implemented)

    def test_rag_loaded_when_needed(self):
        """RAG is loaded only when plan.needs.rag is true."""
        plan = QueryPlan(
            classification="document_query", confidence=0.9,
            needs=Needs(rag=True),
            search_queries=["Python yesterday"],
        )
        # Assembler should call memory_manager.recall()

    def test_tool_hint_adds_to_tool_list(self):
        """tool_hint adds the hinted tool schema alongside find_tools."""
        plan = QueryPlan(
            classification="creative", confidence=0.9,
            tool_hint="generate_music",
            needs=Needs(experiences=True),
        )
        # Tool list should be [find_tools, generate_music]

    def test_response_style_is_last(self):
        """response_style instruction is the last content in system prompt."""
        plan = QueryPlan(
            classification="standard", confidence=0.9,
            response_style="brief",
            needs=Needs(rag=True),
        )
        # Last line of system prompt should be conciseness instruction
```

These are structural tests — they'll be fleshed out when the assembler is implemented. For now they document the expected behavior.

- [ ] **Step 2: Define identity and tool instruction constants**

Add to `odigos/core/context.py` (or a new constants section):

```python
_TOOL_INSTRUCTION = (
    "You can manage workspaces, generate media, execute code, and more. "
    "Use find_tools to discover specific capabilities. "
    "Call it when asked to do something. "
    "Do not say \"I can't\" without checking find_tools first."
)
```

The identity is loaded from `data/agent/identity.md` at init time and cached.

- [ ] **Step 3: Rewrite build() method**

Replace the existing `build()` method with the planner-driven version. Key changes:
- Accept `plan: QueryPlan` parameter (in addition to existing params for backward compat)
- Accept `recent_turns: list[dict] | None = None` parameter
- Only load sections that `plan.needs` flags true
- Build tool list from `plan.tool_hint` + find_tools
- Return `(messages, tools)` tuple instead of just messages
- Budget enforcement: cap total system prompt at `self.max_prompt_tokens`
- Response style injected last
- If `plan` is None, fall back to loading everything (backward compat during migration)

The old parallel-loading inner functions (_memory_context, _memory_index, _doc_listing, _skill_hints, etc.) are kept but only called when the corresponding need is flagged.

- [ ] **Step 4: Update build_headless() to use QueryPlan**

Replace the current `build_headless()` with one that creates a pre-built QueryPlan and calls the new `build()`:

```python
async def build_headless(self, step_description, plan_context=""):
    plan = QueryPlan(
        classification="standard",
        confidence=1.0,
        needs=Needs(rag=True, experiences=True),
        response_style="brief",
    )
    messages, tools = await self.build(
        "headless", step_description, plan=plan,
    )
    # Prepend plan_context to messages
    ...
    return messages
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_prompt_assembly.py tests/test_classifier_plan.py -v`

- [ ] **Step 6: Commit**

```bash
git add odigos/core/context.py tests/test_prompt_assembly.py
git commit -m "feat(context): planner-driven build() with budget enforcement"
```

---

### Task 4: Update executor to use QueryPlan and new build() signature

**Files:**
- Modify: `odigos/core/executor.py`
- Modify: `odigos/core/agent.py`

- [ ] **Step 1: Update executor.execute() to use plan**

The executor currently calls `self.context_assembler.build(conversation_id, message_content, ...)` which returns messages. Update it to:

1. Receive `query_plan: QueryPlan` instead of `query_analysis: QueryAnalysis`
2. Call `self.context_assembler.build(conversation_id, message_content, plan=query_plan, recent_turns=recent_turns)` which returns `(messages, tools)`
3. Use the returned `tools` instead of calling `self.tool_registry.tool_definitions()`
4. Remove the old tool_definitions() call entirely

- [ ] **Step 2: Update agent._run() to pass QueryPlan**

The agent calls `self.classifier.classify(message.content)` which now returns `QueryPlan`. Pass it to the executor as `query_plan`.

Also add `recent_turns` parameter to `handle_message()` and `_run()`. Pass it through to both the classifier and the executor.

- [ ] **Step 3: Verify syntax**

Run: `python3 -c "from odigos.core.executor import Executor; print('OK')"`
Run: `python3 -c "from odigos.core.agent import Agent; print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add odigos/core/executor.py odigos/core/agent.py
git commit -m "feat(executor): use QueryPlan for tool list and context assembly"
```

---

### Task 5: Track recent turns in WebSocket handler

**Files:**
- Modify: `odigos/api/ws.py`

- [ ] **Step 1: Track last 3 turns in the WebSocket session**

In the WebSocket chat processing loop, maintain a `recent_turns` list. After each exchange (user message + assistant response), append both to the list. Keep only the last 3 pairs (6 messages).

Pass `recent_turns` to `agent_service.handle_message()` as a new parameter.

```python
recent_turns: list[dict] = []

# After user sends message:
recent_turns.append({"role": "user", "content": data["content"]})

# After agent responds:
recent_turns.append({"role": "assistant", "content": response})

# Keep last 6 messages (3 turns)
if len(recent_turns) > 6:
    recent_turns = recent_turns[-6:]
```

- [ ] **Step 2: Pass recent_turns through the call chain**

`ws.py` → `agent_service.handle_message(msg, recent_turns=recent_turns)` → `agent.handle_message(message, recent_turns=recent_turns)` → `agent._run(... recent_turns=recent_turns)` → `classifier.classify(message, recent_turns=recent_turns)` AND `context_assembler.build(... recent_turns=recent_turns)`

- [ ] **Step 3: Commit**

```bash
git add odigos/api/ws.py
git commit -m "feat(ws): track recent turns for classifier context"
```

---

### Task 6: Simplify prompt builder and clean up

**Files:**
- Modify: `odigos/personality/prompt_builder.py`
- Modify: `odigos/personality/section_registry.py`
- Remove: `odigos/core/relevance.py` (pruning no longer needed)
- Modify: `data/agent/capabilities.md` (remove)
- Modify: `data/agent/meta.md` (set exclude_from_prompt)
- Modify: `data/agent/query handling.md` (set exclude_from_prompt)
- Modify: `data/agent/skill_creation.md` (set exclude_from_prompt)

- [ ] **Step 1: Simplify prompt_builder.py**

The current `build_system_prompt()` takes 15+ parameters. Simplify to just concatenate a list of parts:

```python
def build_system_prompt(parts: list[str], concise_instruction: str = "") -> str:
    """Compose system prompt from assembler-selected parts."""
    filtered = [p for p in parts if p.strip()]
    if concise_instruction:
        filtered.append(concise_instruction)
    return "\n\n".join(filtered)
```

- [ ] **Step 2: Simplify section_registry.py**

The registry only needs to load `identity.md`. Remove the `always_include` flag, cache logic, and multi-section loading. Keep `_load_one()` for loading a single file.

- [ ] **Step 3: Remove relevance.py**

Delete `odigos/core/relevance.py`. Remove all imports of `prune_sections` from context.py.

- [ ] **Step 4: Set excluded prompt sections**

For `meta.md`, `query handling.md`, `skill_creation.md` — set `exclude_from_prompt: true` in their frontmatter. They stay on disk for the evolution engine but aren't loaded into the chat prompt.

`capabilities.md` — set `exclude_from_prompt: true`. Its content is replaced by the `_TOOL_INSTRUCTION` constant.

- [ ] **Step 5: Run all tests**

Run: `python3 -m pytest tests/ -x -q --ignore=tests/test_core.py`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add odigos/personality/prompt_builder.py odigos/personality/section_registry.py odigos/core/context.py data/agent/
git rm odigos/core/relevance.py
git commit -m "refactor: simplify prompt builder, remove pruning, clean up sections"
```

---

### Task 7: Integration verification

- [ ] **Step 1: Run full test suite**

Run: `python3 -m pytest tests/ -x -q --ignore=tests/test_core.py`

- [ ] **Step 2: Verify prompt size on server**

Deploy and run the test_sections.py script to verify the system prompt for "Make me a song about cats" is < 500 chars.

- [ ] **Step 3: Verify tool_hint works**

Check server logs — the classifier should return `tool_hint: "generate_music"` and the agent should call it without needing find_tools.

- [ ] **Step 4: Verify multi-turn context**

Send a follow-up message ("do it again but in jazz") and verify the classifier sees the previous turns and correctly identifies it as a music generation request.

- [ ] **Step 5: Deploy to all servers**

```bash
bash deploy.sh
```

- [ ] **Step 6: Commit any fixes**

```bash
git add -A && git commit -m "fix: integration cleanup for prompt assembly redesign"
```
