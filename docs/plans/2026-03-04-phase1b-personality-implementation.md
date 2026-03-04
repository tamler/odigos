# Phase 1b: Personality Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a personality system driven by `data/personality.yaml` that controls the agent's voice, tone, and identity via a structured prompt builder.

**Architecture:** New `odigos/personality/` package with a YAML loader (returns a Personality dataclass with defaults) and a structured prompt builder that composes system prompt sections. The prompt builder replaces the hardcoded template in context.py. Personality is re-read on every message (hot reload).

**Tech Stack:** Python 3.12, pydantic (for dataclass), PyYAML (already a dep), pytest

---

### Task 1: Personality Loader

**Files:**
- Create: `odigos/personality/__init__.py`
- Create: `odigos/personality/loader.py`
- Create: `data/personality.yaml`
- Create: `tests/test_personality.py`

**Step 1: Write the failing test**

Create `tests/test_personality.py`:

```python
import tempfile
from pathlib import Path

import pytest
import yaml

from odigos.personality.loader import Personality, load_personality


class TestLoadPersonality:
    def test_loads_from_yaml(self, tmp_path: Path):
        """Load personality from a YAML file."""
        personality_file = tmp_path / "personality.yaml"
        personality_file.write_text(
            yaml.dump(
                {
                    "name": "Jarvis",
                    "voice": {
                        "tone": "formal and precise",
                        "verbosity": "verbose",
                        "humor": "none",
                        "formality": "always formal",
                    },
                    "identity": {
                        "role": "butler",
                        "relationship": "servant",
                        "first_person": False,
                        "expresses_uncertainty": False,
                        "expresses_opinions": False,
                    },
                }
            )
        )

        personality = load_personality(str(personality_file))

        assert personality.name == "Jarvis"
        assert personality.voice.tone == "formal and precise"
        assert personality.voice.verbosity == "verbose"
        assert personality.identity.role == "butler"
        assert personality.identity.first_person is False

    def test_returns_defaults_when_file_missing(self):
        """Missing file returns default personality."""
        personality = load_personality("/nonexistent/path.yaml")

        assert personality.name == "Odigos"
        assert personality.voice.tone == "direct, warm, slightly informal"
        assert personality.identity.first_person is True

    def test_partial_yaml_fills_defaults(self, tmp_path: Path):
        """YAML with only some fields fills the rest with defaults."""
        personality_file = tmp_path / "personality.yaml"
        personality_file.write_text(yaml.dump({"name": "Nova"}))

        personality = load_personality(str(personality_file))

        assert personality.name == "Nova"
        # Defaults for everything else
        assert personality.voice.tone == "direct, warm, slightly informal"
        assert personality.identity.role == "personal assistant and research partner"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_personality.py -v`
Expected: FAIL (module doesn't exist)

**Step 3: Implement personality loader**

Create `odigos/personality/__init__.py` (empty file).

Create `odigos/personality/loader.py`:

```python
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class VoiceConfig:
    tone: str = "direct, warm, slightly informal"
    verbosity: str = "concise by default, detailed when asked"
    humor: str = "dry, occasional, never forced"
    formality: str = "casual with owner, professional with others"


@dataclass
class IdentityConfig:
    role: str = "personal assistant and research partner"
    relationship: str = "trusted aide — not a servant, not a peer"
    first_person: bool = True
    expresses_uncertainty: bool = True
    expresses_opinions: bool = True


@dataclass
class Personality:
    name: str = "Odigos"
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    identity: IdentityConfig = field(default_factory=IdentityConfig)


def load_personality(path: str) -> Personality:
    """Load personality from a YAML file. Returns defaults if file is missing."""
    filepath = Path(path)
    if not filepath.exists():
        logger.info("Personality file not found at %s, using defaults", path)
        return Personality()

    with open(filepath) as f:
        data = yaml.safe_load(f) or {}

    voice_data = data.get("voice", {})
    identity_data = data.get("identity", {})

    return Personality(
        name=data.get("name", "Odigos"),
        voice=VoiceConfig(**{k: v for k, v in voice_data.items() if k in VoiceConfig.__dataclass_fields__}),
        identity=IdentityConfig(**{k: v for k, v in identity_data.items() if k in IdentityConfig.__dataclass_fields__}),
    )
```

Create `data/personality.yaml`:

```yaml
name: "Odigos"

voice:
  tone: "direct, warm, slightly informal"
  verbosity: "concise by default, detailed when asked"
  humor: "dry, occasional, never forced"
  formality: "casual with owner, professional with others"

identity:
  role: "personal assistant and research partner"
  relationship: "trusted aide — not a servant, not a peer"
  first_person: true
  expresses_uncertainty: true
  expresses_opinions: true
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_personality.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add odigos/personality/__init__.py odigos/personality/loader.py data/personality.yaml tests/test_personality.py
git commit -m "feat: add personality loader with YAML config and defaults"
```

---

### Task 2: Structured Prompt Builder

**Files:**
- Create: `odigos/personality/prompt_builder.py`
- Add tests to: `tests/test_personality.py`

**Step 1: Write the failing test**

Add to `tests/test_personality.py`:

```python
from odigos.personality.prompt_builder import build_system_prompt


class TestPromptBuilder:
    def test_builds_prompt_with_personality(self):
        """Prompt includes personality identity and voice sections."""
        personality = Personality(
            name="TestBot",
            voice=VoiceConfig(tone="cheerful", verbosity="brief"),
            identity=IdentityConfig(role="helper", relationship="friendly"),
        )

        prompt = build_system_prompt(personality)

        assert "TestBot" in prompt
        assert "cheerful" in prompt
        assert "brief" in prompt
        assert "helper" in prompt
        assert "<!--entities" in prompt  # entity extraction always included

    def test_builds_prompt_with_memory_context(self):
        """Prompt includes memory section when provided."""
        personality = Personality()

        prompt = build_system_prompt(
            personality,
            memory_context="## Relevant memories\n- Alice prefers mornings.",
        )

        assert "Relevant memories" in prompt
        assert "Alice prefers mornings" in prompt

    def test_builds_prompt_without_memory(self):
        """Prompt works fine without memory context."""
        personality = Personality()

        prompt = build_system_prompt(personality)

        assert "Odigos" in prompt
        assert "<!--entities" in prompt
        # No memory section
        assert "Relevant memories" not in prompt

    def test_uncertainty_and_opinions_in_prompt(self):
        """Identity flags are reflected in the prompt."""
        personality = Personality(
            identity=IdentityConfig(
                expresses_uncertainty=True,
                expresses_opinions=True,
            )
        )

        prompt = build_system_prompt(personality)

        assert "uncertain" in prompt.lower() or "not sure" in prompt.lower()

    def test_no_uncertainty_when_disabled(self):
        """When expresses_uncertainty is False, prompt doesn't mention it."""
        personality = Personality(
            identity=IdentityConfig(expresses_uncertainty=False)
        )

        prompt = build_system_prompt(personality)

        # Should NOT contain uncertainty language
        assert "not sure" not in prompt.lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_personality.py::TestPromptBuilder -v`
Expected: FAIL (module doesn't exist)

**Step 3: Implement prompt builder**

Create `odigos/personality/prompt_builder.py`:

```python
from odigos.personality.loader import Personality

ENTITY_EXTRACTION_INSTRUCTION = """After your response, on a new line, include extracted entities in this exact format:
<!--entities
[{{"name": "...", "type": "person|project|preference|concept", "relationship": "...", "detail": "..."}}]
-->
Only include entities if the conversation mentions specific people, projects, preferences, or important concepts.
If none are relevant, omit the block entirely."""


def build_system_prompt(
    personality: Personality,
    memory_context: str = "",
) -> str:
    """Compose the system prompt from structured sections.

    Sections:
    1. Identity -- who the agent is
    2. Voice guidelines -- how to communicate
    3. Memory context -- relevant memories (if any)
    4. Entity extraction -- always appended
    """
    sections = []

    # 1. Identity
    sections.append(_build_identity_section(personality))

    # 2. Voice guidelines
    sections.append(_build_voice_section(personality))

    # 3. Memory context (optional)
    if memory_context:
        sections.append(memory_context)

    # 4. Entity extraction (always)
    sections.append(ENTITY_EXTRACTION_INSTRUCTION)

    return "\n\n".join(sections)


def _build_identity_section(personality: Personality) -> str:
    """Build the identity/intro section of the system prompt."""
    identity = personality.identity

    lines = [f"You are {personality.name}, a {identity.role}."]

    if identity.relationship:
        lines.append(f"Your relationship with the user: {identity.relationship}.")

    if identity.first_person:
        lines.append("Speak in first person.")

    if identity.expresses_uncertainty:
        lines.append(
            "When you're not sure about something, say so honestly rather than guessing."
        )

    if identity.expresses_opinions:
        lines.append(
            "When asked, share your perspective with reasoning."
        )

    return " ".join(lines)


def _build_voice_section(personality: Personality) -> str:
    """Build the voice/style guidelines section."""
    voice = personality.voice

    lines = ["## Communication style"]
    lines.append(f"- Tone: {voice.tone}")
    lines.append(f"- Verbosity: {voice.verbosity}")
    lines.append(f"- Humor: {voice.humor}")
    lines.append(f"- Formality: {voice.formality}")

    return "\n".join(lines)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_personality.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add odigos/personality/prompt_builder.py tests/test_personality.py
git commit -m "feat: add structured prompt builder composing personality sections"
```

---

### Task 3: Wire Personality into Context Assembly

**Files:**
- Modify: `odigos/core/context.py` (use prompt builder instead of hardcoded template)
- Modify: `odigos/config.py` (add PersonalityConfig)
- Modify: `config.yaml` (add personality section)
- Modify: `tests/test_core.py` (update context assembler tests)

**Step 1: Write the failing test**

Add to `tests/test_core.py`:

```python
from odigos.personality.loader import Personality, VoiceConfig, IdentityConfig

class TestContextAssemblerWithPersonality:
    async def test_uses_personality_from_file(self, db: Database, tmp_path):
        """Context assembler loads personality from file and uses it in prompt."""
        import yaml

        personality_file = tmp_path / "personality.yaml"
        personality_file.write_text(
            yaml.dump({"name": "Hal", "voice": {"tone": "robotic and precise"}})
        )

        assembler = ContextAssembler(
            db=db,
            agent_name="Hal",
            history_limit=20,
            personality_path=str(personality_file),
        )
        messages = await assembler.build("conv-1", "Hello")

        system_content = messages[0]["content"]
        assert "Hal" in system_content
        assert "robotic and precise" in system_content

    async def test_falls_back_to_defaults(self, db: Database):
        """Missing personality file falls back to defaults."""
        assembler = ContextAssembler(
            db=db,
            agent_name="Odigos",
            history_limit=20,
            personality_path="/nonexistent/file.yaml",
        )
        messages = await assembler.build("conv-1", "Hello")

        system_content = messages[0]["content"]
        assert "Odigos" in system_content
        assert "direct, warm" in system_content
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestContextAssemblerWithPersonality -v`
Expected: FAIL (ContextAssembler doesn't accept personality_path)

**Step 3: Update context.py**

Replace `odigos/core/context.py` with:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from odigos.db import Database
from odigos.personality.loader import load_personality
from odigos.personality.prompt_builder import build_system_prompt

if TYPE_CHECKING:
    from odigos.memory.manager import MemoryManager


class ContextAssembler:
    """Builds the messages list for an LLM call from conversation history."""

    def __init__(
        self,
        db: Database,
        agent_name: str,
        history_limit: int = 20,
        memory_manager: MemoryManager | None = None,
        personality_path: str = "data/personality.yaml",
    ) -> None:
        self.db = db
        self.agent_name = agent_name
        self.history_limit = history_limit
        self.memory_manager = memory_manager
        self.personality_path = personality_path

    async def build(self, conversation_id: str, current_message: str) -> list[dict]:
        """Assemble the full messages list: system + history + current."""
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

        return messages
```

Add `PersonalityConfig` to `odigos/config.py`:

```python
class PersonalityConfig(BaseModel):
    path: str = "data/personality.yaml"
```

Add `personality: PersonalityConfig = PersonalityConfig()` to the `Settings` class.

Add `personality:` section to `config.yaml`:

```yaml
personality:
  path: "data/personality.yaml"
```

Update `odigos/main.py` to pass `personality_path` when creating Agent. In the lifespan, change the Agent creation to:

```python
agent = Agent(
    db=_db,
    provider=_provider,
    agent_name=settings.agent.name,
    memory_manager=memory_manager,
    personality_path=settings.personality.path,
)
```

Update `odigos/core/agent.py` to accept and pass `personality_path`:

In `Agent.__init__`, add `personality_path: str = "data/personality.yaml"` parameter, and pass it to ContextAssembler:

```python
self.context_assembler = ContextAssembler(
    db, agent_name, history_limit,
    memory_manager=memory_manager,
    personality_path=personality_path,
)
```

**Step 4: Fix existing tests**

The existing `TestContextAssembler` and `TestContextAssemblerWithMemory` tests create `ContextAssembler` without `personality_path`. Since the default is `"data/personality.yaml"` and the file exists in the project, the tests will use the default personality. However, the assertions like `"TestBot" in messages[0]["content"]` check that the agent name appears in the system prompt -- this will now come from the personality file, not from `agent_name`.

The prompt builder uses `personality.name` for the identity section. So when tests create `ContextAssembler(db=db, agent_name="TestBot")` with no personality_path, it will load `data/personality.yaml` which says `name: "Odigos"`. To fix this:

- For `TestContextAssembler`: pass `personality_path="/nonexistent"` so it falls back to defaults (which use `name="Odigos"`, matching the test data), OR update assertions to match the default personality name.
- For `TestContextAssemblerWithMemory`: similarly adjust.
- The simplest fix: pass a nonexistent personality_path in tests so defaults are used, and update the name assertion to match "Odigos" (or just check system role exists).

Update existing test assertions as needed. The key is: system prompt will now contain personality-driven content instead of the old hardcoded template, so `"TestBot" in messages[0]["content"]` needs to change. Replace with checking for the default personality name or pass a custom personality file in tests.

**Step 5: Run ALL tests**

Run: `uv run pytest -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add odigos/core/context.py odigos/core/agent.py odigos/config.py odigos/main.py config.yaml tests/test_core.py
git commit -m "feat: wire personality into context assembly with hot reload"
```

---

### Task 4: Final Verification and Lint

**Files:** All modified files

**Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: ALL PASS

**Step 2: Run linter**

Run: `uv run ruff check odigos/ tests/`

Fix any issues.

**Step 3: Format**

Run: `uv run ruff format odigos/ tests/`

**Step 4: Run tests again**

Run: `uv run pytest -v`
Expected: ALL PASS

**Step 5: Verify app starts**

Run: `uv run odigos` (ctrl-C after startup)
Expected: No import errors, logs show "Odigos is ready."

**Step 6: Commit**

```bash
git add -A
git commit -m "chore: lint and final verification for Phase 1b personality"
```
