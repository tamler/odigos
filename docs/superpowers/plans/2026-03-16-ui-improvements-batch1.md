# UI Improvements Batch 1 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four improvements: voice UI buttons in chat, nav simplification (move pages into Settings), capability guide prompt, and agent self-config tool.

**Architecture:** Voice UI adds mic/speaker buttons to ChatPage using existing WebSocket/API endpoints. Nav simplification moves 3 route-level pages into SettingsPage tabs and removes sidebar nav links. Capability guide is a new prompt section file. Self-config tool is a new BaseTool that writes config via the settings API.

**Tech Stack:** React/TypeScript/Tailwind (frontend), Python/FastAPI (backend)

---

## Chunk 1: Voice UI in Chat

### Task 1: Add mic button (STT) to chat input bar

**Files:**
- Modify: `dashboard/src/pages/ChatPage.tsx`

- [ ] **Step 1: Add Mic icon import and recording state**

Add `Mic, MicOff` to the lucide-react import:
```typescript
import { ArrowUp, Paperclip, X, Mic, MicOff } from 'lucide-react'
```

Add state for recording and settings after existing state:
```typescript
const [recording, setRecording] = useState(false)
const [voiceEnabled, setVoiceEnabled] = useState(false)
const mediaRecorderRef = useRef<MediaRecorder | null>(null)
const audioWsRef = useRef<WebSocket | null>(null)
```

- [ ] **Step 2: Check voice settings on mount**

Add a useEffect to check if STT is enabled:
```typescript
useEffect(() => {
  get<{ stt?: { enabled?: boolean } }>('/api/settings')
    .then((s) => setVoiceEnabled(!!s.stt?.enabled))
    .catch(() => {})
}, [])
```

Note: This reads the `stt` field from the settings response. The `get_settings_endpoint` in `odigos/api/settings.py` does not currently return `stt` or `voice`. We need to add it.

- [ ] **Step 3: Add voice config to settings API response**

Modify `odigos/api/settings.py`, in the `get_settings_endpoint` return dict, add after the `feed` line:
```python
"voice": {
    "stt": settings.voice.stt.model_dump() if hasattr(settings, 'voice') and settings.voice else {},
    "tts": settings.voice.tts.model_dump() if hasattr(settings, 'voice') and settings.voice else {},
},
```

Check: verify `settings.voice` exists in the config schema. Read `odigos/config.py` for the `VoiceConfig` / `voice` field. If it uses a nested structure like `voice.stt.enabled` and `voice.tts.enabled`, adapt accordingly.

- [ ] **Step 4: Add recording toggle functions**

Add before the `return` in ChatPage:
```typescript
const startRecording = useCallback(async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const token = localStorage.getItem('odigos_api_key') || ''
    const wsUrl = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/audio/input?token=${token}`
    const ws = new WebSocket(wsUrl)
    audioWsRef.current = ws

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'transcription' && data.text) {
          setInputValue((prev) => prev + (prev ? ' ' : '') + data.text)
        }
      } catch {}
    }

    ws.onopen = () => {
      const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' })
      mediaRecorderRef.current = recorder
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) {
          ws.send(e.data)
        }
      }
      recorder.start(500) // send chunks every 500ms
      setRecording(true)
    }

    ws.onerror = () => {
      stream.getTracks().forEach((t) => t.stop())
      setRecording(false)
      toast.error('Voice connection failed')
    }
  } catch {
    toast.error('Microphone access denied')
  }
}, [])

const stopRecording = useCallback(() => {
  if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
    mediaRecorderRef.current.stop()
    mediaRecorderRef.current.stream.getTracks().forEach((t) => t.stop())
  }
  if (audioWsRef.current) {
    audioWsRef.current.close()
    audioWsRef.current = null
  }
  mediaRecorderRef.current = null
  setRecording(false)
}, [])
```

- [ ] **Step 5: Add mic button to input bar**

In the composer bottom bar, between the FileUploadTrigger and the Send button, add:
```tsx
{voiceEnabled && (
  <Button
    variant="ghost"
    size="icon"
    className={`h-8 w-8 rounded-lg ${recording ? 'text-red-500 animate-pulse' : 'text-muted-foreground hover:text-foreground'}`}
    disabled={!connected}
    onClick={recording ? stopRecording : startRecording}
  >
    {recording ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
  </Button>
)}
```

The layout becomes: `[attach] [mic?] ........... [send]`

- [ ] **Step 6: Type-check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/pages/ChatPage.tsx odigos/api/settings.py
git commit -m "feat(dashboard): add mic button for voice input in chat

Streams audio to /ws/audio/input when recording. Transcribed text
appends to the input field. Only shown when STT is enabled."
```

### Task 2: Add speaker button (TTS) on assistant messages

**Files:**
- Modify: `dashboard/src/pages/ChatPage.tsx`

- [ ] **Step 1: Add Volume2 icon import**

Add `Volume2` to the lucide-react import (alongside the existing icons).

- [ ] **Step 2: Add TTS playback function**

Add a `playTTS` function:
```typescript
const playTTS = useCallback(async (text: string) => {
  try {
    const token = localStorage.getItem('odigos_api_key') || ''
    const res = await fetch(`/api/audio/speak?text=${encodeURIComponent(text)}`, {
      headers: { 'Authorization': `Bearer ${token}` },
    })
    if (!res.ok) throw new Error('TTS failed')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const audio = new Audio(url)
    audio.onended = () => URL.revokeObjectURL(url)
    audio.play()
  } catch {
    toast.error('Text-to-speech failed')
  }
}, [])
```

- [ ] **Step 3: Add speaker icon to assistant messages**

In the assistant message rendering block (the `else` branch around line 216), wrap it:
```tsx
<div className="group/msg">
  <div className="text-sm text-foreground leading-relaxed">
    <Markdown>{msg.content}</Markdown>
  </div>
  {voiceEnabled && (
    <button
      onClick={() => playTTS(msg.content)}
      className="mt-1 text-muted-foreground hover:text-foreground opacity-0 group-hover/msg:opacity-100 transition-opacity"
      title="Read aloud"
    >
      <Volume2 className="h-3.5 w-3.5" />
    </button>
  )}
</div>
```

- [ ] **Step 4: Type-check and build**

Run: `cd dashboard && npx tsc --noEmit && npm run build`
Expected: No errors, build succeeds

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/ChatPage.tsx dashboard/dist/
git commit -m "feat(dashboard): add TTS speaker button on assistant messages

Plays audio via /api/audio/speak endpoint. Only visible when
voice is enabled. Shows on hover to keep UI clean."
```

---

## Chunk 2: Nav Simplification

### Task 3: Move Connections, Feed, Inspector into Settings tabs

**Files:**
- Modify: `dashboard/src/pages/SettingsPage.tsx`
- Modify: `dashboard/src/pages/ConnectionsPage.tsx`
- Modify: `dashboard/src/pages/FeedPage.tsx`
- Modify: `dashboard/src/pages/StatePage.tsx`
- Modify: `dashboard/src/App.tsx`
- Modify: `dashboard/src/layouts/AppLayout.tsx`

- [ ] **Step 1: Add new tabs to SettingsPage**

Add imports at top of SettingsPage.tsx:
```typescript
import ConnectionsTab from '../ConnectionsPage'
import FeedTab from '../FeedPage'
import InspectorTab from '../StatePage'
```

Add 3 new entries to the TABS array:
```typescript
const TABS = [
  { id: 'general', label: 'General' },
  { id: 'skills', label: 'Skills' },
  { id: 'prompts', label: 'Prompts' },
  { id: 'evolution', label: 'Evolution' },
  { id: 'agents', label: 'Agents' },
  { id: 'plugins', label: 'Plugins' },
  { id: 'connections', label: 'Connections' },
  { id: 'feed', label: 'Feed' },
  { id: 'inspector', label: 'Inspector' },
] as const
```

Add tab content rendering:
```tsx
<div className={activeTab === 'connections' ? '' : 'hidden'}><ConnectionsTab active={activeTab === 'connections'} /></div>
<div className={activeTab === 'feed' ? '' : 'hidden'}><FeedTab active={activeTab === 'feed'} /></div>
<div className={activeTab === 'inspector' ? '' : 'hidden'}><InspectorTab active={activeTab === 'inspector'} /></div>
```

- [ ] **Step 2: Add active prop to the 3 moved pages**

Each page needs an `active` prop and refetch-on-active pattern, same as the other settings tabs.

For **ConnectionsPage.tsx**: Change `export default function ConnectionsPage()` to `export default function ConnectionsPage({ active }: { active?: boolean })`. Find its data loading `useEffect`/`useCallback` and add `useEffect(() => { if (active) loadFn() }, [active])`.

For **FeedPage.tsx**: Same pattern.

For **StatePage.tsx**: Same pattern.

Also change the outer container div in each from `max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8` to `max-w-3xl mx-auto px-4 sm:px-6 py-4 sm:py-6` to match the settings tab styling.

- [ ] **Step 3: Remove routes from App.tsx**

In `dashboard/src/App.tsx`, remove these 3 Route lines:
```tsx
<Route path="/status" element={<StatePage />} />
<Route path="/feed" element={<FeedPage />} />
<Route path="/connections" element={<ConnectionsPage />} />
```

And remove the corresponding imports:
```typescript
import StatePage from './pages/StatePage'
import FeedPage from './pages/FeedPage'
import ConnectionsPage from './pages/ConnectionsPage'
```

- [ ] **Step 4: Remove sidebar nav links from AppLayout**

In `dashboard/src/layouts/AppLayout.tsx`, remove the 3 bottom nav Tooltip blocks for Connections, Feed, and Inspector (the blocks from roughly line 261-301). Keep only the Settings button.

Also remove the `isConnectionsPage`, `isFeedPage`, `isStatusPage` variables and remove `Activity, Rss, Link2` from the lucide-react import (if no longer used elsewhere in the file).

- [ ] **Step 5: Type-check and build**

Run: `cd dashboard && npx tsc --noEmit && npm run build`
Expected: No errors, build succeeds

- [ ] **Step 6: Commit**

```bash
git add dashboard/
git commit -m "feat(dashboard): move Connections/Feed/Inspector into Settings tabs

Sidebar now only has Chat + Settings. All admin pages are
Settings tabs. Reduces navigation complexity."
```

---

## Chunk 3: Capability Guide + Self-Config Tool

### Task 4: Create capabilities prompt section

**Files:**
- Create: `data/agent/capabilities.md`

- [ ] **Step 1: Write the capabilities prompt section**

Create `data/agent/capabilities.md`:
```markdown
---
priority: 50
always_include: true
---
## Your capabilities

When users ask what you can do, walk them through these capabilities:

**Communication:** You maintain conversations with memory across sessions. You recall past discussions, entities, and facts.

**Web:** You can search the web (if SearXNG is configured) and scrape/read web pages.

**Documents:** You can read uploaded files (PDF, Word, Excel, images, etc.) and process them.

**Code:** You can write and execute Python code and shell commands in a sandboxed environment.

**Files:** You can read and write files in your allowed directories.

**Goals & Todos:** You can create and track goals, todos, and reminders. You'll proactively check on them.

**Skills:** You have reusable skills for specific tasks. You can create new skills from patterns you learn.

**Voice:** If enabled, you can speak responses aloud and transcribe voice input.

**Self-improvement:** You evaluate your own performance and run experiments to improve over time.

When explaining capabilities, give practical examples relevant to what the user is working on. Don't just list features — show how they help.
```

- [ ] **Step 2: Force-add to git (data/ is gitignored)**

```bash
git add -f data/agent/capabilities.md
git commit -m "feat: add capabilities prompt section for user onboarding

Agent can now explain its own features when asked 'what can you do?'"
```

### Task 5: Create ManageSettingsTool

**Files:**
- Create: `odigos/tools/settings_tool.py`
- Modify: `odigos/main.py` (register the tool)
- Create: `tests/test_settings_tool.py`

- [ ] **Step 1: Write the test**

Create `tests/test_settings_tool.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from odigos.tools.settings_tool import ManageSettingsTool


@pytest.fixture
def tool():
    settings = MagicMock()
    settings.searxng_url = ""
    settings.browser = MagicMock(enabled=False)
    settings.gws = MagicMock(enabled=False)
    settings.voice = MagicMock(
        stt=MagicMock(enabled=False),
        tts=MagicMock(enabled=False),
    )
    settings.budget = MagicMock(daily_limit_usd=5.0, monthly_limit_usd=50.0)
    settings.approval = MagicMock(enabled=False, tools=[])
    config_path = "/tmp/test_config.yaml"
    return ManageSettingsTool(settings=settings, config_path=config_path)


@pytest.mark.asyncio
async def test_read_setting(tool):
    result = await tool.execute({"action": "read", "key": "browser.enabled"})
    assert result.success
    assert "False" in result.data


@pytest.mark.asyncio
async def test_list_settings(tool):
    result = await tool.execute({"action": "list"})
    assert result.success
    assert "browser" in result.data
    assert "voice" in result.data


@pytest.mark.asyncio
async def test_write_blocked_key(tool):
    result = await tool.execute({"action": "write", "key": "api_key", "value": "hacked"})
    assert not result.success
    assert "not allowed" in result.data.lower() or result.error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_settings_tool.py -xvs`
Expected: ImportError (module doesn't exist yet)

- [ ] **Step 3: Write the tool**

Create `odigos/tools/settings_tool.py`:
```python
"""ManageSettingsTool — lets the agent read and update its own configuration."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Keys the agent is allowed to read/write
_ALLOWED_KEYS = {
    "browser.enabled", "browser.timeout",
    "gws.enabled", "gws.timeout",
    "voice.stt.enabled", "voice.stt.model",
    "voice.tts.enabled", "voice.tts.voice",
    "searxng_url",
    "approval.enabled", "approval.tools",
    "heartbeat.interval_seconds", "heartbeat.idle_think_interval",
}

# Keys that can never be written by the agent
_BLOCKED_KEYS = {"api_key", "llm_api_key", "budget", "llm"}


class ManageSettingsTool(BaseTool):
    """Read or update agent configuration settings."""

    name = "manage_settings"
    description = (
        "Read or update the agent's configuration. Use 'list' to see available settings, "
        "'read' to check a setting's value, or 'write' to change a setting. "
        "Cannot modify API keys, LLM config, or budget limits."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "read", "write"],
                "description": "Action to perform",
            },
            "key": {
                "type": "string",
                "description": "Dotted setting key (e.g., 'browser.enabled')",
            },
            "value": {
                "description": "New value for write action",
            },
        },
        "required": ["action"],
    }

    def __init__(self, settings: Any, config_path: str) -> None:
        self._settings = settings
        self._config_path = Path(config_path)

    def _resolve(self, key: str) -> Any:
        obj = self._settings
        for part in key.split("."):
            try:
                obj = getattr(obj, part)
            except AttributeError:
                return None
        return obj

    async def execute(self, params: dict) -> ToolResult:
        action = params.get("action", "list")

        if action == "list":
            lines = []
            for key in sorted(_ALLOWED_KEYS):
                val = self._resolve(key)
                lines.append(f"  {key} = {val}")
            return ToolResult(success=True, data="Available settings:\n" + "\n".join(lines))

        if action == "read":
            key = params.get("key", "")
            val = self._resolve(key)
            return ToolResult(success=True, data=f"{key} = {val}")

        if action == "write":
            key = params.get("key", "")
            value = params.get("value")

            # Block protected keys
            for blocked in _BLOCKED_KEYS:
                if key.startswith(blocked):
                    return ToolResult(success=False, data="", error=f"Modifying '{key}' is not allowed")

            if key not in _ALLOWED_KEYS:
                return ToolResult(
                    success=False, data="",
                    error=f"Unknown setting '{key}'. Use action='list' to see available settings.",
                )

            # Write to config.yaml
            try:
                yaml_config: dict = {}
                if self._config_path.exists():
                    with open(self._config_path) as f:
                        yaml_config = yaml.safe_load(f) or {}

                # Navigate dotted key path
                parts = key.split(".")
                target = yaml_config
                for part in parts[:-1]:
                    target = target.setdefault(part, {})
                target[parts[-1]] = value

                with open(self._config_path, "w") as f:
                    yaml.dump(yaml_config, f, default_flow_style=False)

                # Hot-reload in-memory setting
                obj = self._settings
                for part in parts[:-1]:
                    obj = getattr(obj, part)
                object.__setattr__(obj, parts[-1], value)

                logger.info("Agent updated setting %s = %s", key, value)
                return ToolResult(success=True, data=f"Updated {key} = {value}")
            except Exception as e:
                return ToolResult(success=False, data="", error=str(e))

        return ToolResult(success=False, data="", error=f"Unknown action: {action}")
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_settings_tool.py -xvs`
Expected: All 3 pass

- [ ] **Step 5: Register the tool in main.py**

In `odigos/main.py`, find where tools are registered (look for `tool_registry.register`). Add:
```python
from odigos.tools.settings_tool import ManageSettingsTool
tool_registry.register(ManageSettingsTool(settings=settings, config_path="config.yaml"))
```

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ --ignore=tests/e2e -x -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add odigos/tools/settings_tool.py tests/test_settings_tool.py odigos/main.py
git commit -m "feat: add ManageSettingsTool for agent self-configuration

Agent can list, read, and write allowed settings. Protected keys
(api_key, llm, budget) are blocked. Writes to config.yaml and
hot-reloads in memory."
```

---

## Chunk 4: Final Build and Deploy

### Task 6: Build dashboard and push

- [ ] **Step 1: Full type-check and build**

Run: `cd dashboard && npx tsc --noEmit && npm run build`

- [ ] **Step 2: Run backend tests**

Run: `.venv/bin/python -m pytest tests/ --ignore=tests/e2e -x -q`

- [ ] **Step 3: Commit build artifacts and push**

```bash
git add dashboard/dist/
git commit -m "build: rebuild dashboard with voice UI and nav simplification"
git push
```

- [ ] **Step 4: Deploy to personal VPS**

```bash
ssh root@82.25.91.86 "cd /opt/odigos && git pull && systemctl restart odigos"
```

- [ ] **Step 5: Deploy to tester VPS**

```bash
ssh root@100.89.147.103 "cd /opt/odigos/repo && git pull && cd /opt/odigos && docker compose build --no-cache && docker compose down && docker compose up -d"
```
