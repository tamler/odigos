# Web UI Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the minimal Preact dashboard with a polished React+Tailwind+shadcn/ui frontend featuring settings-first onboarding, streaming chat, file upload, and plugin-based voice discovery.

**Architecture:** Vite builds the React frontend to `dashboard/dist/`. FastAPI serves it as static files. New backend endpoints handle settings CRUD, setup status, and file upload. The plugin API exposes capabilities so the UI can conditionally render voice buttons.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, shadcn/ui, Vite, FastAPI, Python 3.12

---

### Task 1: Backend — Setup Status Endpoint

**Files:**
- Create: `tests/test_api_setup.py`
- Create: `odigos/api/setup.py`
- Modify: `odigos/main.py:486-494` (register router)

**Step 1: Write the failing test**

```python
# tests/test_api_setup.py
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

from odigos.api.setup import router


def _make_app(llm_api_key: str = "", api_key: str = "test-key") -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    settings = MagicMock()
    settings.llm_api_key = llm_api_key
    settings.api_key = api_key
    settings.llm.base_url = "https://openrouter.ai/api/v1"
    app.state.settings = settings
    return app


def test_setup_status_unconfigured():
    app = _make_app(llm_api_key="")
    client = TestClient(app)
    resp = client.get("/api/setup-status")
    assert resp.status_code == 200
    assert resp.json() == {"configured": False}


def test_setup_status_configured():
    app = _make_app(llm_api_key="sk-real-key")
    client = TestClient(app)
    resp = client.get("/api/setup-status")
    assert resp.status_code == 200
    assert resp.json() == {"configured": True}
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_setup.py -v`
Expected: FAIL with "No module named 'odigos.api.setup'"

**Step 3: Write minimal implementation**

```python
# odigos/api/setup.py
"""Setup status endpoint — no auth required (used before config exists)."""

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api")


@router.get("/setup-status")
async def setup_status(request: Request):
    """Return whether the system has been configured with an LLM key."""
    settings = request.app.state.settings
    configured = bool(settings.llm_api_key and settings.llm_api_key != "your-api-key")
    return {"configured": configured}
```

Add to `odigos/main.py` after line 494 (with the other router includes):

```python
from odigos.api.setup import router as setup_router
# ... in the router registration block:
app.include_router(setup_router)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_setup.py -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add tests/test_api_setup.py odigos/api/setup.py odigos/main.py
git commit -m "feat(api): add /api/setup-status endpoint for onboarding"
```

---

### Task 2: Backend — Settings GET/POST Endpoints

**Files:**
- Create: `tests/test_api_settings.py`
- Create: `odigos/api/settings.py`
- Modify: `odigos/main.py` (register router)

**Step 1: Write the failing test**

```python
# tests/test_api_settings.py
import os
import tempfile
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

from odigos.api.settings import router


def _make_app(tmp_path) -> tuple[FastAPI, str, str]:
    """Create test app with temp config.yaml and .env."""
    app = FastAPI()
    app.include_router(router)

    config_path = os.path.join(tmp_path, "config.yaml")
    env_path = os.path.join(tmp_path, ".env")

    # Write initial config
    with open(config_path, "w") as f:
        f.write("agent:\n  name: Odigos\nllm:\n  base_url: https://openrouter.ai/api/v1\n")
    with open(env_path, "w") as f:
        f.write("LLM_API_KEY=test-key\n")

    settings = MagicMock()
    settings.api_key = "test-key"
    settings.llm_api_key = "test-key"
    settings.llm.base_url = "https://openrouter.ai/api/v1"
    settings.llm.default_model = "anthropic/claude-sonnet-4"
    settings.llm.fallback_model = "google/gemini-2.0-flash-001"
    settings.llm.max_tokens = 4096
    settings.llm.temperature = 0.7
    settings.agent.name = "Odigos"
    settings.agent.max_tool_turns = 25
    settings.agent.run_timeout_seconds = 300
    settings.budget.daily_limit_usd = 1.0
    settings.budget.monthly_limit_usd = 20.0
    settings.budget.warn_threshold = 0.8
    settings.heartbeat.interval_seconds = 30
    settings.heartbeat.max_todos_per_tick = 3
    settings.heartbeat.idle_think_interval = 900
    settings.sandbox.timeout_seconds = 5
    settings.sandbox.max_memory_mb = 512
    settings.sandbox.allow_network = False

    app.state.settings = settings
    app.state.config_path = config_path
    app.state.env_path = env_path

    return app, config_path, env_path


def test_get_settings(tmp_path):
    app, _, _ = _make_app(tmp_path)
    client = TestClient(app)
    resp = client.get("/api/settings", headers={"Authorization": "Bearer test-key"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["llm"]["base_url"] == "https://openrouter.ai/api/v1"
    # API key should be masked
    assert data["llm_api_key"] == "****"


def test_post_settings_updates_config(tmp_path):
    app, config_path, env_path = _make_app(tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/settings",
        json={
            "llm": {"base_url": "http://localhost:11434/v1", "default_model": "llama3.2"},
            "llm_api_key": "new-key",
        },
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "saved"

    # Verify config.yaml was updated
    with open(config_path) as f:
        content = f.read()
    assert "localhost:11434" in content

    # Verify .env was updated
    with open(env_path) as f:
        content = f.read()
    assert "LLM_API_KEY=new-key" in content


def test_get_settings_no_auth(tmp_path):
    app, _, _ = _make_app(tmp_path)
    client = TestClient(app)
    resp = client.get("/api/settings")
    assert resp.status_code == 401
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_settings.py -v`
Expected: FAIL with "No module named 'odigos.api.settings'"

**Step 3: Write minimal implementation**

```python
# odigos/api/settings.py
"""Settings GET/POST endpoints for UI configuration."""

import os

import yaml
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from odigos.api.deps import require_api_key


router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


class SettingsUpdate(BaseModel):
    """Partial settings update — all fields optional."""
    llm_api_key: str | None = None
    llm: dict | None = None
    agent: dict | None = None
    budget: dict | None = None
    heartbeat: dict | None = None
    sandbox: dict | None = None


@router.get("/settings")
async def get_settings(request: Request):
    """Return current settings with secrets masked."""
    s = request.app.state.settings
    return {
        "llm_api_key": "****" if s.llm_api_key else "",
        "llm": {
            "base_url": s.llm.base_url,
            "default_model": s.llm.default_model,
            "fallback_model": s.llm.fallback_model,
            "max_tokens": s.llm.max_tokens,
            "temperature": s.llm.temperature,
        },
        "agent": {
            "name": s.agent.name,
            "max_tool_turns": s.agent.max_tool_turns,
            "run_timeout_seconds": s.agent.run_timeout_seconds,
        },
        "budget": {
            "daily_limit_usd": s.budget.daily_limit_usd,
            "monthly_limit_usd": s.budget.monthly_limit_usd,
            "warn_threshold": s.budget.warn_threshold,
        },
        "heartbeat": {
            "interval_seconds": s.heartbeat.interval_seconds,
            "max_todos_per_tick": s.heartbeat.max_todos_per_tick,
            "idle_think_interval": s.heartbeat.idle_think_interval,
        },
        "sandbox": {
            "timeout_seconds": s.sandbox.timeout_seconds,
            "max_memory_mb": s.sandbox.max_memory_mb,
            "allow_network": s.sandbox.allow_network,
        },
    }


@router.post("/settings")
async def update_settings(update: SettingsUpdate, request: Request):
    """Update config.yaml and .env, then hot-reload settings."""
    config_path = getattr(request.app.state, "config_path", "config.yaml")
    env_path = getattr(request.app.state, "env_path", ".env")

    # Load existing config.yaml
    yaml_config = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            yaml_config = yaml.safe_load(f) or {}

    # Merge updates into yaml config
    for section in ("llm", "agent", "budget", "heartbeat", "sandbox"):
        section_data = getattr(update, section)
        if section_data is not None:
            if section not in yaml_config:
                yaml_config[section] = {}
            yaml_config[section].update(section_data)

    # Write config.yaml
    with open(config_path, "w") as f:
        yaml.dump(yaml_config, f, default_flow_style=False, sort_keys=False)

    # Update .env if API key changed
    if update.llm_api_key is not None:
        with open(env_path, "w") as f:
            f.write(f"LLM_API_KEY={update.llm_api_key}\n")

    # Hot-reload: update in-memory settings
    s = request.app.state.settings
    if update.llm is not None:
        for k, v in update.llm.items():
            if hasattr(s.llm, k):
                object.__setattr__(s.llm, k, v)
    if update.agent is not None:
        for k, v in update.agent.items():
            if hasattr(s.agent, k):
                object.__setattr__(s.agent, k, v)
    if update.budget is not None:
        for k, v in update.budget.items():
            if hasattr(s.budget, k):
                object.__setattr__(s.budget, k, v)
    if update.llm_api_key is not None:
        object.__setattr__(s, "llm_api_key", update.llm_api_key)

    return {"status": "saved"}
```

Register in `odigos/main.py`:

```python
from odigos.api.settings import router as settings_router
# ... in router registration block:
app.include_router(settings_router)
```

Also store `config_path` and `env_path` on app state in `main.py` lifespan (after settings load):

```python
app.state.config_path = config_path  # the path passed to load_settings()
app.state.env_path = ".env"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_settings.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add tests/test_api_settings.py odigos/api/settings.py odigos/main.py
git commit -m "feat(api): add settings GET/POST endpoints with hot-reload"
```

---

### Task 3: Backend — File Upload Endpoint

**Files:**
- Create: `tests/test_api_upload.py`
- Create: `odigos/api/upload.py`
- Modify: `odigos/main.py` (register router)

**Step 1: Write the failing test**

```python
# tests/test_api_upload.py
import os
import tempfile
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

from odigos.api.upload import router


def _make_app(tmp_path) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    settings = MagicMock()
    settings.api_key = "test-key"
    app.state.settings = settings
    app.state.upload_dir = str(tmp_path)
    return app


def test_upload_file(tmp_path):
    app = _make_app(tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/upload",
        files={"file": ("test.txt", b"hello world", "text/plain")},
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"] == "test.txt"
    assert data["size"] == 11
    assert "id" in data
    # Verify file was written
    assert os.path.exists(os.path.join(tmp_path, data["id"] + "_test.txt"))


def test_upload_no_file(tmp_path):
    app = _make_app(tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/upload",
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 422


def test_upload_no_auth(tmp_path):
    app = _make_app(tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/upload",
        files={"file": ("test.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 401
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_upload.py -v`
Expected: FAIL with "No module named 'odigos.api.upload'"

**Step 3: Write minimal implementation**

```python
# odigos/api/upload.py
"""File upload endpoint."""

import os
import secrets

from fastapi import APIRouter, Depends, Request, UploadFile

from odigos.api.deps import require_api_key

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


@router.post("/upload")
async def upload_file(file: UploadFile, request: Request):
    """Upload a file, store it, return a reference ID."""
    upload_dir = getattr(request.app.state, "upload_dir", "data/uploads")
    os.makedirs(upload_dir, exist_ok=True)

    file_id = secrets.token_hex(8)
    safe_name = os.path.basename(file.filename or "upload")
    dest = os.path.join(upload_dir, f"{file_id}_{safe_name}")

    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)

    return {
        "id": file_id,
        "filename": file.filename,
        "size": len(content),
        "path": dest,
    }
```

Register in `odigos/main.py`:

```python
from odigos.api.upload import router as upload_router
app.include_router(upload_router)
```

Set upload dir on app state in lifespan:

```python
app.state.upload_dir = "data/uploads"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_upload.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add tests/test_api_upload.py odigos/api/upload.py odigos/main.py
git commit -m "feat(api): add file upload endpoint"
```

---

### Task 4: Backend — Plugin Capabilities in API Response

**Files:**
- Modify: `odigos/api/plugins.py:13-22`
- Modify: `tests/test_api_plugins.py` (or create if it doesn't exist)

**Step 1: Write the failing test**

```python
# tests/test_api_plugins.py
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

from odigos.api.plugins import router


def _make_app(plugins: list) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    settings = MagicMock()
    settings.api_key = "test-key"
    app.state.settings = settings
    pm = MagicMock()
    pm.loaded_plugins = plugins
    app.state.plugin_manager = pm
    return app


def test_plugins_with_capabilities():
    plugins = [
        {"name": "moonshine-stt", "capabilities": ["stt"]},
        {"name": "pocket-tts", "capabilities": ["tts"]},
        {"name": "log-tools", "capabilities": []},
    ]
    app = _make_app(plugins)
    client = TestClient(app)
    resp = client.get("/api/plugins", headers={"Authorization": "Bearer test-key"})
    assert resp.status_code == 200
    data = resp.json()["plugins"]
    assert data[0]["capabilities"] == ["stt"]
    assert data[1]["capabilities"] == ["tts"]
    assert data[2]["capabilities"] == []


def test_plugins_without_capabilities():
    """Legacy plugins without capabilities field return empty list."""
    plugins = [{"name": "legacy-plugin"}]
    app = _make_app(plugins)
    client = TestClient(app)
    resp = client.get("/api/plugins", headers={"Authorization": "Bearer test-key"})
    data = resp.json()["plugins"]
    assert data[0]["capabilities"] == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_plugins.py -v`
Expected: FAIL (capabilities not in response)

**Step 3: Update implementation**

```python
# odigos/api/plugins.py
"""Plugins list API endpoint."""

from fastapi import APIRouter, Depends

from odigos.api.deps import get_plugin_manager, require_api_key

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


@router.get("/plugins")
async def list_plugins(
    plugin_manager=Depends(get_plugin_manager),
):
    """Return list of loaded plugins with their capabilities."""
    plugins = [
        {
            "name": p["name"],
            "status": "loaded",
            "capabilities": p.get("capabilities", []),
        }
        for p in plugin_manager.loaded_plugins
    ]
    return {"plugins": plugins}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_plugins.py -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add odigos/api/plugins.py tests/test_api_plugins.py
git commit -m "feat(api): expose plugin capabilities in /api/plugins"
```

---

### Task 5: Backend — Update Dashboard Serving for Vite dist/

**Files:**
- Modify: `odigos/dashboard.py`

The current `mount_dashboard` mounts individual subdirectories (vendor, css, js, etc.). The Vite build outputs to `dashboard/dist/` with `assets/` containing hashed JS/CSS bundles. We need to update the serving to handle this.

**Step 1: Update dashboard.py**

```python
# odigos/dashboard.py
"""Serve the SPA dashboard from the dashboard/dist directory."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

DEFAULT_DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard", "dist")


def mount_dashboard(app: FastAPI, dashboard_dir: str | None = None) -> None:
    dist = dashboard_dir or DEFAULT_DASHBOARD_DIR
    index_html = os.path.join(dist, "index.html")

    if not os.path.isfile(index_html):
        return

    # Mount assets directory (Vite outputs hashed files here)
    assets_dir = os.path.join(dist, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="dashboard_assets")

    # Catch-all: serve index.html for SPA routing
    @app.get("/{path:path}")
    async def serve_spa(path: str):
        file_path = os.path.join(dist, path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(index_html)
```

**Step 2: Run existing tests to verify nothing breaks**

Run: `pytest tests/ -v -x --timeout=10`
Expected: All existing tests pass

**Step 3: Commit**

```bash
git add odigos/dashboard.py
git commit -m "refactor: update dashboard serving for Vite dist/ output"
```

---

### Task 6: Frontend — Scaffold Vite + React + TypeScript + Tailwind + shadcn/ui

**Files:**
- Create: `dashboard/package.json`
- Create: `dashboard/vite.config.ts`
- Create: `dashboard/tsconfig.json`
- Create: `dashboard/tsconfig.app.json`
- Create: `dashboard/tailwind.config.ts` (or via postcss)
- Create: `dashboard/src/main.tsx`
- Create: `dashboard/src/App.tsx`
- Create: `dashboard/index.html` (Vite entry)
- Create: `dashboard/components.json` (shadcn config)

**Step 1: Initialize the project**

```bash
cd dashboard

# Remove old files (keep as backup if desired)
mkdir -p _old && mv *.html css/ js/ lib/ components/ pages/ vendor/ _old/ 2>/dev/null || true

# Create Vite React+TS project
npm create vite@latest . -- --template react-ts

# Install Tailwind CSS v4
npm install tailwindcss @tailwindcss/vite

# Install shadcn/ui dependencies
npm install class-variance-authority clsx tailwind-merge lucide-react

# Install shadcn/ui CLI and init
npx shadcn@latest init
```

Follow shadcn init prompts: New York style, Zinc base color, CSS variables yes.

**Step 2: Configure Vite for correct base path**

```typescript
// dashboard/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: 'dist',
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
```

**Step 3: Create minimal App.tsx**

```tsx
// dashboard/src/App.tsx
export default function App() {
  return (
    <div className="flex items-center justify-center min-h-screen bg-background text-foreground">
      <h1 className="text-2xl font-bold">Odigos</h1>
    </div>
  )
}
```

```tsx
// dashboard/src/main.tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
```

**Step 4: Build and verify**

```bash
npm run build
ls dist/index.html dist/assets/
```

Expected: `dist/` contains `index.html` and `assets/` with hashed `.js` and `.css` files.

**Step 5: Commit**

```bash
cd ..
git add dashboard/package.json dashboard/vite.config.ts dashboard/tsconfig*.json \
  dashboard/src/ dashboard/index.html dashboard/components.json \
  dashboard/dist/ dashboard/postcss.config.* dashboard/tailwind.config.* \
  dashboard/.gitignore
git commit -m "feat(ui): scaffold Vite + React + TypeScript + Tailwind + shadcn/ui"
```

---

### Task 7: Frontend — API Client and Auth Utilities

**Files:**
- Create: `dashboard/src/lib/api.ts`
- Create: `dashboard/src/lib/auth.ts`
- Create: `dashboard/src/lib/ws.ts`

**Step 1: Create API client**

```typescript
// dashboard/src/lib/api.ts
const BASE = ''  // Same origin

function getToken(): string {
  return localStorage.getItem('odigos_api_key') || ''
}

function headers(): HeadersInit {
  return {
    'Authorization': `Bearer ${getToken()}`,
    'Content-Type': 'application/json',
  }
}

export async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: headers() })
  if (res.status === 401 || res.status === 403) {
    throw new Error('unauthorized')
  }
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: headers(),
    body: body ? JSON.stringify(body) : undefined,
  })
  if (res.status === 401 || res.status === 403) {
    throw new Error('unauthorized')
  }
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export async function uploadFile(file: File): Promise<{
  id: string; filename: string; size: number; path: string
}> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/api/upload`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${getToken()}` },
    body: form,
  })
  if (!res.ok) throw new Error(`Upload error: ${res.status}`)
  return res.json()
}
```

```typescript
// dashboard/src/lib/auth.ts
const STORAGE_KEY = 'odigos_api_key'

export function getApiKey(): string | null {
  return localStorage.getItem(STORAGE_KEY)
}

export function setApiKey(key: string): void {
  localStorage.setItem(STORAGE_KEY, key)
}

export function clearApiKey(): void {
  localStorage.removeItem(STORAGE_KEY)
}

export function isAuthenticated(): boolean {
  return !!getApiKey()
}
```

```typescript
// dashboard/src/lib/ws.ts
import { getApiKey } from './auth'

type MessageHandler = (msg: Record<string, unknown>) => void

export class ChatSocket {
  private ws: WebSocket | null = null
  private onMessage: MessageHandler
  private onStatusChange: (connected: boolean) => void
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null

  constructor(
    onMessage: MessageHandler,
    onStatusChange: (connected: boolean) => void,
  ) {
    this.onMessage = onMessage
    this.onStatusChange = onStatusChange
  }

  connect(): void {
    const token = getApiKey()
    if (!token) return

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    this.ws = new WebSocket(`${proto}//${window.location.host}/api/ws?token=${token}`)

    this.ws.onopen = () => this.onStatusChange(true)
    this.ws.onclose = () => {
      this.onStatusChange(false)
      this.scheduleReconnect()
    }
    this.ws.onmessage = (e) => {
      try {
        this.onMessage(JSON.parse(e.data))
      } catch { /* ignore parse errors */ }
    }
  }

  send(type: string, data: Record<string, unknown> = {}): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, ...data }))
    }
  }

  disconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.ws?.close()
    this.ws = null
  }

  private scheduleReconnect(): void {
    this.reconnectTimer = setTimeout(() => this.connect(), 3000)
  }
}
```

**Step 2: Commit**

```bash
git add dashboard/src/lib/
git commit -m "feat(ui): add API client, auth, and WebSocket utilities"
```

---

### Task 8: Frontend — Router, Layout, and Navigation

**Files:**
- Install: `react-router-dom`
- Create: `dashboard/src/App.tsx` (update with router)
- Create: `dashboard/src/layouts/AppLayout.tsx`
- Create: `dashboard/src/pages/ChatPage.tsx` (placeholder)
- Create: `dashboard/src/pages/SettingsPage.tsx` (placeholder)

**Step 1: Install router**

```bash
cd dashboard && npm install react-router-dom
```

**Step 2: Create layout and pages**

```tsx
// dashboard/src/layouts/AppLayout.tsx
import { Outlet, NavLink } from 'react-router-dom'
import { MessageSquare, Settings } from 'lucide-react'

export default function AppLayout() {
  return (
    <div className="flex h-screen bg-background text-foreground">
      {/* Sidebar */}
      <aside className="w-14 border-r flex flex-col items-center py-4 gap-4">
        <NavLink
          to="/"
          className={({ isActive }) =>
            `p-2 rounded-lg transition-colors ${isActive ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:text-foreground'}`
          }
        >
          <MessageSquare className="h-5 w-5" />
        </NavLink>
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            `p-2 rounded-lg transition-colors ${isActive ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:text-foreground'}`
          }
        >
          <Settings className="h-5 w-5" />
        </NavLink>
      </aside>

      {/* Main content */}
      <main className="flex-1 flex flex-col overflow-hidden">
        <Outlet />
      </main>
    </div>
  )
}
```

```tsx
// dashboard/src/pages/ChatPage.tsx
export default function ChatPage() {
  return <div className="flex-1 flex items-center justify-center text-muted-foreground">Chat — coming next</div>
}
```

```tsx
// dashboard/src/pages/SettingsPage.tsx
export default function SettingsPage() {
  return <div className="flex-1 flex items-center justify-center text-muted-foreground">Settings — coming next</div>
}
```

```tsx
// dashboard/src/App.tsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { get } from './lib/api'
import { isAuthenticated } from './lib/auth'
import AppLayout from './layouts/AppLayout'
import ChatPage from './pages/ChatPage'
import SettingsPage from './pages/SettingsPage'

export default function App() {
  const [setupDone, setSetupDone] = useState<boolean | null>(null)

  useEffect(() => {
    get<{ configured: boolean }>('/api/setup-status')
      .then((data) => setSetupDone(data.configured))
      .catch(() => setSetupDone(false))
  }, [])

  if (setupDone === null) {
    return <div className="flex items-center justify-center h-screen text-muted-foreground">Loading...</div>
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={setupDone && isAuthenticated() ? <ChatPage /> : <Navigate to="/settings" />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
```

**Step 3: Build and verify**

```bash
npm run build && ls dist/index.html
```

**Step 4: Commit**

```bash
cd ..
git add dashboard/src/ dashboard/package.json dashboard/package-lock.json dashboard/dist/
git commit -m "feat(ui): add router, layout, and page scaffolding with onboarding redirect"
```

---

### Task 9: Frontend — Settings Page with Onboarding Modal

**Files:**
- Install: shadcn components (button, input, select, card, dialog, label, tabs)
- Create: `dashboard/src/pages/SettingsPage.tsx` (full implementation)
- Create: `dashboard/src/components/SetupModal.tsx`

**Step 1: Install shadcn components**

```bash
cd dashboard
npx shadcn@latest add button input select card dialog label tabs separator
```

**Step 2: Create the setup modal**

```tsx
// dashboard/src/components/SetupModal.tsx
import { useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { post } from '@/lib/api'
import { setApiKey } from '@/lib/auth'

const PROVIDERS = [
  { id: 'openrouter', name: 'OpenRouter', url: 'https://openrouter.ai/api/v1', model: 'anthropic/claude-sonnet-4', fallback: 'google/gemini-2.0-flash-001' },
  { id: 'openai', name: 'OpenAI', url: 'https://api.openai.com/v1', model: 'gpt-4o', fallback: 'gpt-4o-mini' },
  { id: 'ollama', name: 'Ollama (local)', url: 'http://host.docker.internal:11434/v1', model: 'llama3.2', fallback: 'llama3.2' },
  { id: 'lmstudio', name: 'LM Studio (local)', url: 'http://host.docker.internal:1234/v1', model: 'default', fallback: 'default' },
  { id: 'custom', name: 'Custom', url: '', model: '', fallback: '' },
]

interface Props {
  open: boolean
  onComplete: () => void
}

export default function SetupModal({ open, onComplete }: Props) {
  const [provider, setProvider] = useState('openrouter')
  const [baseUrl, setBaseUrl] = useState(PROVIDERS[0].url)
  const [apiKey, setLlmApiKey] = useState('')
  const [model, setModel] = useState(PROVIDERS[0].model)
  const [fallback, setFallback] = useState(PROVIDERS[0].fallback)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  function onProviderChange(id: string) {
    setProvider(id)
    const p = PROVIDERS.find((p) => p.id === id)
    if (p) {
      setBaseUrl(p.url)
      setModel(p.model)
      setFallback(p.fallback)
    }
  }

  async function handleSave() {
    setSaving(true)
    setError('')
    try {
      await post('/api/settings', {
        llm_api_key: apiKey || 'no-key-needed',
        llm: {
          base_url: baseUrl,
          default_model: model,
          fallback_model: fallback,
        },
      })
      // The settings endpoint returns the api_key if auto-generated
      // For now, prompt the user or read from response
      const resp = await fetch('/api/health')
      if (resp.ok) {
        onComplete()
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const isLocal = baseUrl.includes('localhost') || baseUrl.includes('host.docker.internal')

  return (
    <Dialog open={open}>
      <DialogContent className="sm:max-w-md" onInteractOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle>Welcome to Odigos</DialogTitle>
          <DialogDescription>Configure your LLM provider to get started.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label>Provider</Label>
            <Select value={provider} onValueChange={onProviderChange}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {PROVIDERS.map((p) => (
                  <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Base URL</Label>
            <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://..." />
          </div>
          <div className="space-y-2">
            <Label>API Key {isLocal && '(optional for local models)'}</Label>
            <Input type="password" value={apiKey} onChange={(e) => setLlmApiKey(e.target.value)} placeholder={isLocal ? 'Press Enter to skip' : 'sk-...'} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-2">
              <Label>Model</Label>
              <Input value={model} onChange={(e) => setModel(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Fallback Model</Label>
              <Input value={fallback} onChange={(e) => setFallback(e.target.value)} />
            </div>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button className="w-full" onClick={handleSave} disabled={saving || (!baseUrl || !model)}>
            {saving ? 'Saving...' : 'Save & Start'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
```

**Step 3: Create the full settings page**

```tsx
// dashboard/src/pages/SettingsPage.tsx
import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Separator } from '@/components/ui/separator'
import { get, post } from '@/lib/api'
import SetupModal from '@/components/SetupModal'

interface SettingsData {
  llm_api_key: string
  llm: { base_url: string; default_model: string; fallback_model: string; max_tokens: number; temperature: number }
  agent: { name: string; max_tool_turns: number; run_timeout_seconds: number }
  budget: { daily_limit_usd: number; monthly_limit_usd: number; warn_threshold: number }
  heartbeat: { interval_seconds: number; max_todos_per_tick: number; idle_think_interval: number }
  sandbox: { timeout_seconds: number; max_memory_mb: number; allow_network: boolean }
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<SettingsData | null>(null)
  const [showSetup, setShowSetup] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    get<{ configured: boolean }>('/api/setup-status').then((data) => {
      if (!data.configured) setShowSetup(true)
    })
    get<SettingsData>('/api/settings')
      .then(setSettings)
      .catch(() => setShowSetup(true))
  }, [])

  function update(section: string, field: string, value: string | number | boolean) {
    if (!settings) return
    setSettings({ ...settings, [section]: { ...(settings as any)[section], [field]: value } })
    setSaved(false)
  }

  async function save() {
    if (!settings) return
    setSaving(true)
    try {
      await post('/api/settings', settings)
      setSaved(true)
    } finally {
      setSaving(false)
    }
  }

  if (!settings && !showSetup) {
    return <div className="flex-1 flex items-center justify-center text-muted-foreground">Loading...</div>
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <SetupModal open={showSetup} onComplete={() => { setShowSetup(false); window.location.reload() }} />
      <div className="max-w-2xl mx-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">Settings</h1>
          <Button onClick={save} disabled={saving || saved}>
            {saved ? 'Saved' : saving ? 'Saving...' : 'Save Changes'}
          </Button>
        </div>
        <Tabs defaultValue="llm">
          <TabsList>
            <TabsTrigger value="llm">LLM</TabsTrigger>
            <TabsTrigger value="agent">Agent</TabsTrigger>
            <TabsTrigger value="budget">Budget</TabsTrigger>
            <TabsTrigger value="advanced">Advanced</TabsTrigger>
          </TabsList>

          <TabsContent value="llm" className="space-y-4 mt-4">
            <Card>
              <CardHeader><CardTitle>LLM Provider</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label>Base URL</Label>
                  <Input value={settings?.llm.base_url || ''} onChange={(e) => update('llm', 'base_url', e.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label>API Key</Label>
                  <Input type="password" placeholder="****" onChange={(e) => setSettings(s => s ? { ...s, llm_api_key: e.target.value } : s)} />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Default Model</Label>
                    <Input value={settings?.llm.default_model || ''} onChange={(e) => update('llm', 'default_model', e.target.value)} />
                  </div>
                  <div className="space-y-2">
                    <Label>Fallback Model</Label>
                    <Input value={settings?.llm.fallback_model || ''} onChange={(e) => update('llm', 'fallback_model', e.target.value)} />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Max Tokens</Label>
                    <Input type="number" value={settings?.llm.max_tokens || 4096} onChange={(e) => update('llm', 'max_tokens', parseInt(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Temperature</Label>
                    <Input type="number" step="0.1" value={settings?.llm.temperature || 0.7} onChange={(e) => update('llm', 'temperature', parseFloat(e.target.value))} />
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="agent" className="space-y-4 mt-4">
            <Card>
              <CardHeader><CardTitle>Agent</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label>Name</Label>
                  <Input value={settings?.agent.name || ''} onChange={(e) => update('agent', 'name', e.target.value)} />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Max Tool Turns</Label>
                    <Input type="number" value={settings?.agent.max_tool_turns || 25} onChange={(e) => update('agent', 'max_tool_turns', parseInt(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Run Timeout (seconds)</Label>
                    <Input type="number" value={settings?.agent.run_timeout_seconds || 300} onChange={(e) => update('agent', 'run_timeout_seconds', parseInt(e.target.value))} />
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="budget" className="space-y-4 mt-4">
            <Card>
              <CardHeader><CardTitle>Budget Limits</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Daily Limit (USD)</Label>
                    <Input type="number" step="0.5" value={settings?.budget.daily_limit_usd || 1} onChange={(e) => update('budget', 'daily_limit_usd', parseFloat(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Monthly Limit (USD)</Label>
                    <Input type="number" step="1" value={settings?.budget.monthly_limit_usd || 20} onChange={(e) => update('budget', 'monthly_limit_usd', parseFloat(e.target.value))} />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label>Warning Threshold (0-1)</Label>
                  <Input type="number" step="0.05" min="0" max="1" value={settings?.budget.warn_threshold || 0.8} onChange={(e) => update('budget', 'warn_threshold', parseFloat(e.target.value))} />
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="advanced" className="space-y-4 mt-4">
            <Card>
              <CardHeader><CardTitle>Heartbeat</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-3 gap-4">
                  <div className="space-y-2">
                    <Label>Interval (s)</Label>
                    <Input type="number" value={settings?.heartbeat.interval_seconds || 30} onChange={(e) => update('heartbeat', 'interval_seconds', parseInt(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Max Todos/Tick</Label>
                    <Input type="number" value={settings?.heartbeat.max_todos_per_tick || 3} onChange={(e) => update('heartbeat', 'max_todos_per_tick', parseInt(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Idle Think (s)</Label>
                    <Input type="number" value={settings?.heartbeat.idle_think_interval || 900} onChange={(e) => update('heartbeat', 'idle_think_interval', parseInt(e.target.value))} />
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Sandbox</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Timeout (s)</Label>
                    <Input type="number" value={settings?.sandbox.timeout_seconds || 5} onChange={(e) => update('sandbox', 'timeout_seconds', parseInt(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Max Memory (MB)</Label>
                    <Input type="number" value={settings?.sandbox.max_memory_mb || 512} onChange={(e) => update('sandbox', 'max_memory_mb', parseInt(e.target.value))} />
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
```

**Step 4: Build and verify**

```bash
cd dashboard && npm run build
```

**Step 5: Commit**

```bash
cd ..
git add dashboard/src/ dashboard/dist/ dashboard/package*.json
git commit -m "feat(ui): settings page with onboarding modal"
```

---

### Task 10: Frontend — Chat Page with Streaming Messages

**Files:**
- Install: `react-markdown`, `remark-gfm`, `react-syntax-highlighter`
- Create: `dashboard/src/pages/ChatPage.tsx` (full implementation)
- Create: `dashboard/src/components/ChatMessage.tsx`
- Create: `dashboard/src/components/ChatInput.tsx`

**Step 1: Install markdown dependencies**

```bash
cd dashboard
npm install react-markdown remark-gfm react-syntax-highlighter @types/react-syntax-highlighter
```

**Step 2: Create ChatMessage component**

```tsx
// dashboard/src/components/ChatMessage.tsx
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'

interface Props {
  role: 'user' | 'assistant'
  content: string
  timestamp?: string
}

export default function ChatMessage({ role, content, timestamp }: Props) {
  const isUser = role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} group`}>
      <div className={`max-w-[80%] rounded-2xl px-4 py-3 ${
        isUser
          ? 'bg-primary text-primary-foreground'
          : 'bg-muted'
      }`}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            code({ className, children, ...props }) {
              const match = /language-(\w+)/.exec(className || '')
              const inline = !match
              return inline ? (
                <code className="bg-background/50 px-1 py-0.5 rounded text-sm" {...props}>{children}</code>
              ) : (
                <SyntaxHighlighter
                  style={oneDark}
                  language={match[1]}
                  PreTag="div"
                  className="rounded-lg my-2 text-sm"
                >
                  {String(children).replace(/\n$/, '')}
                </SyntaxHighlighter>
              )
            },
          }}
        >
          {content}
        </ReactMarkdown>
        {timestamp && (
          <span className="text-xs opacity-0 group-hover:opacity-50 transition-opacity mt-1 block">
            {new Date(timestamp).toLocaleTimeString()}
          </span>
        )}
      </div>
    </div>
  )
}
```

**Step 3: Create ChatInput component**

```tsx
// dashboard/src/components/ChatInput.tsx
import { useState, useRef, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Send, Paperclip, Mic, Volume2 } from 'lucide-react'
import { uploadFile } from '@/lib/api'

interface Props {
  onSend: (content: string, attachments?: { id: string; filename: string }[]) => void
  disabled: boolean
  hasSTT: boolean
  hasTTS: boolean
}

export default function ChatInput({ onSend, disabled, hasSTT, hasTTS }: Props) {
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<{ id: string; filename: string }[]>([])
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleSend = useCallback(() => {
    const trimmed = input.trim()
    if (!trimmed && attachments.length === 0) return
    onSend(trimmed, attachments.length > 0 ? attachments : undefined)
    setInput('')
    setAttachments([])
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }, [input, attachments, onSend])

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files
    if (!files?.length) return
    setUploading(true)
    try {
      for (const file of Array.from(files)) {
        const result = await uploadFile(file)
        setAttachments((prev) => [...prev, { id: result.id, filename: result.filename }])
      }
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value)
    // Auto-grow
    const el = e.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }

  return (
    <div className="border-t p-4">
      {attachments.length > 0 && (
        <div className="flex gap-2 mb-2 flex-wrap">
          {attachments.map((a) => (
            <span key={a.id} className="text-xs bg-muted px-2 py-1 rounded-full flex items-center gap-1">
              {a.filename}
              <button onClick={() => setAttachments((prev) => prev.filter((x) => x.id !== a.id))} className="hover:text-destructive">&times;</button>
            </span>
          ))}
        </div>
      )}
      <div className="flex items-end gap-2">
        <input ref={fileRef} type="file" multiple className="hidden" onChange={handleFileSelect} />
        <Button variant="ghost" size="icon" onClick={() => fileRef.current?.click()} disabled={disabled || uploading}>
          <Paperclip className="h-4 w-4" />
        </Button>
        {hasSTT && (
          <Button variant="ghost" size="icon" disabled={disabled}>
            <Mic className="h-4 w-4" />
          </Button>
        )}
        <textarea
          ref={textareaRef}
          value={input}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder="Send a message..."
          disabled={disabled}
          rows={1}
          className="flex-1 resize-none bg-muted rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring min-h-[44px] max-h-[200px]"
        />
        {hasTTS && (
          <Button variant="ghost" size="icon" disabled={disabled}>
            <Volume2 className="h-4 w-4" />
          </Button>
        )}
        <Button size="icon" onClick={handleSend} disabled={disabled || (!input.trim() && attachments.length === 0)}>
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}
```

**Step 4: Create full ChatPage**

```tsx
// dashboard/src/pages/ChatPage.tsx
import { useEffect, useRef, useState, useCallback } from 'react'
import { ChatSocket } from '@/lib/ws'
import { get } from '@/lib/api'
import ChatMessage from '@/components/ChatMessage'
import ChatInput from '@/components/ChatInput'

interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [connected, setConnected] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [hasSTT, setHasSTT] = useState(false)
  const [hasTTS, setHasTTS] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const socketRef = useRef<ChatSocket | null>(null)

  // Check plugin capabilities
  useEffect(() => {
    get<{ plugins: { capabilities: string[] }[] }>('/api/plugins')
      .then((data) => {
        const caps = data.plugins.flatMap((p) => p.capabilities)
        setHasSTT(caps.includes('stt'))
        setHasTTS(caps.includes('tts'))
      })
      .catch(() => {})
  }, [])

  // WebSocket connection
  useEffect(() => {
    const socket = new ChatSocket(
      (msg) => {
        if (msg.type === 'chat_response') {
          setThinking(false)
          setMessages((prev) => [...prev, {
            role: 'assistant',
            content: msg.content as string,
            timestamp: new Date().toISOString(),
          }])
        }
      },
      setConnected,
    )
    socket.connect()
    socketRef.current = socket
    return () => socket.disconnect()
  }, [])

  // Auto-scroll
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, thinking])

  const handleSend = useCallback((content: string, attachments?: { id: string; filename: string }[]) => {
    // Add user message to display
    let displayContent = content
    if (attachments?.length) {
      const fileList = attachments.map((a) => a.filename).join(', ')
      displayContent = content ? `${content}\n\n[Attached: ${fileList}]` : `[Attached: ${fileList}]`
    }

    setMessages((prev) => [...prev, {
      role: 'user',
      content: displayContent,
      timestamp: new Date().toISOString(),
    }])
    setThinking(true)

    // Send via WebSocket
    const msgContent = attachments?.length
      ? `${content}\n\n[Files: ${attachments.map((a) => `${a.filename} (${a.id})`).join(', ')}]`
      : content
    socketRef.current?.send('chat', { content: msgContent })
  }, [])

  return (
    <div className="flex-1 flex flex-col">
      {/* Header */}
      <div className="border-b px-4 py-3 flex items-center justify-between">
        <h2 className="font-semibold">Chat</h2>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className={`h-2 w-2 rounded-full ${connected ? 'bg-green-500' : 'bg-red-500'}`} />
          {connected ? 'Connected' : 'Disconnected'}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && !thinking && (
          <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm h-full">
            Send a message to start chatting
          </div>
        )}
        {messages.map((msg, i) => (
          <ChatMessage key={i} role={msg.role} content={msg.content} timestamp={msg.timestamp} />
        ))}
        {thinking && (
          <div className="flex justify-start">
            <div className="bg-muted rounded-2xl px-4 py-3">
              <span className="animate-pulse">Thinking...</span>
            </div>
          </div>
        )}
        <div ref={scrollRef} />
      </div>

      {/* Input */}
      <ChatInput
        onSend={handleSend}
        disabled={!connected}
        hasSTT={hasSTT}
        hasTTS={hasTTS}
      />
    </div>
  )
}
```

**Step 5: Build and verify**

```bash
cd dashboard && npm run build
```

**Step 6: Commit**

```bash
cd ..
git add dashboard/src/ dashboard/dist/ dashboard/package*.json
git commit -m "feat(ui): chat page with streaming messages, file upload, and voice buttons"
```

---

### Task 11: Frontend — Conversation History Sidebar

**Files:**
- Create: `dashboard/src/components/ConversationSidebar.tsx`
- Modify: `dashboard/src/pages/ChatPage.tsx` (integrate sidebar)

**Step 1: Create the sidebar component**

```tsx
// dashboard/src/components/ConversationSidebar.tsx
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Plus, MessageSquare } from 'lucide-react'
import { get } from '@/lib/api'

interface Conversation {
  id: string
  created_at: string
  message_count?: number
}

interface Props {
  activeId: string | null
  onSelect: (id: string | null) => void
}

export default function ConversationSidebar({ activeId, onSelect }: Props) {
  const [conversations, setConversations] = useState<Conversation[]>([])

  useEffect(() => {
    get<{ conversations: Conversation[] }>('/api/conversations?limit=50')
      .then((data) => setConversations(data.conversations))
      .catch(() => {})
  }, [])

  return (
    <div className="w-64 border-r flex flex-col bg-muted/30">
      <div className="p-3">
        <Button variant="outline" className="w-full justify-start gap-2" onClick={() => onSelect(null)}>
          <Plus className="h-4 w-4" /> New Chat
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto px-2 space-y-1">
        {conversations.map((c) => (
          <button
            key={c.id}
            onClick={() => onSelect(c.id)}
            className={`w-full text-left px-3 py-2 rounded-lg text-sm flex items-center gap-2 transition-colors ${
              activeId === c.id ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-accent/50'
            }`}
          >
            <MessageSquare className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{c.id}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
```

**Step 2: Integrate into ChatPage**

Update ChatPage.tsx to include the sidebar — wrap the existing content in a flex container with `<ConversationSidebar />` on the left. Add `activeConversation` state. This is a UI-only integration since the WebSocket already creates conversation IDs.

**Step 3: Build and commit**

```bash
cd dashboard && npm run build && cd ..
git add dashboard/src/ dashboard/dist/
git commit -m "feat(ui): conversation history sidebar"
```

---

### Task 12: Frontend — Login Prompt Component

**Files:**
- Create: `dashboard/src/components/LoginPrompt.tsx`
- Modify: `dashboard/src/App.tsx` (integrate auth check)

**Step 1: Create login prompt**

```tsx
// dashboard/src/components/LoginPrompt.tsx
import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { setApiKey } from '@/lib/auth'

interface Props {
  onLogin: () => void
}

export default function LoginPrompt({ onLogin }: Props) {
  const [key, setKey] = useState('')
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!key.trim()) return
    setApiKey(key.trim())
    // Verify the key works
    try {
      const res = await fetch('/api/settings', {
        headers: { Authorization: `Bearer ${key.trim()}` },
      })
      if (res.ok) {
        onLogin()
      } else {
        setError('Invalid API key')
      }
    } catch {
      setError('Connection failed')
    }
  }

  return (
    <div className="flex items-center justify-center h-screen">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Sign In</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label>API Key</Label>
              <Input type="password" value={key} onChange={(e) => { setKey(e.target.value); setError('') }} placeholder="Enter your API key" autoFocus />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={!key.trim()}>Sign In</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
```

**Step 2: Update App.tsx to check auth state**

Add auth state management to App.tsx: if configured but not authenticated, show `<LoginPrompt />` instead of redirecting to settings.

**Step 3: Build and commit**

```bash
cd dashboard && npm run build && cd ..
git add dashboard/src/ dashboard/dist/
git commit -m "feat(ui): login prompt for returning users"
```

---

### Task 13: Build, Test End-to-End, and Clean Up

**Step 1: Build the final frontend**

```bash
cd dashboard && npm run build && cd ..
```

**Step 2: Start the container and test**

```bash
docker compose down
docker compose up -d --build
```

**Step 3: Test the full flow**

1. Open `http://localhost:8000` — should redirect to settings with setup modal
2. Fill in LLM provider, API key, model — click "Save & Start"
3. Should redirect to chat — connection status should show "Connected"
4. Send a test message — should get a response
5. Click Settings nav — all settings should be loaded and editable
6. Change a setting, save, verify it persists

**Step 4: Clean up old dashboard files**

```bash
rm -rf dashboard/_old  # old Preact files backed up in Task 6
```

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat(ui): complete web UI redesign with onboarding, chat, and settings"
```

---

### Task Summary

| Task | Component | New Files | Tests |
|------|-----------|-----------|-------|
| 1 | Setup status endpoint | `odigos/api/setup.py` | 2 |
| 2 | Settings GET/POST | `odigos/api/settings.py` | 3 |
| 3 | File upload endpoint | `odigos/api/upload.py` | 3 |
| 4 | Plugin capabilities | Modify `odigos/api/plugins.py` | 2 |
| 5 | Dashboard serving | Modify `odigos/dashboard.py` | 0 |
| 6 | Frontend scaffold | Vite + React + TS + Tailwind | 0 |
| 7 | API/auth/WS utilities | `dashboard/src/lib/*` | 0 |
| 8 | Router + layout | `dashboard/src/layouts/*`, `pages/*` | 0 |
| 9 | Settings + onboarding modal | `dashboard/src/pages/SettingsPage.tsx`, `SetupModal.tsx` | 0 |
| 10 | Chat page | `ChatMessage.tsx`, `ChatInput.tsx`, `ChatPage.tsx` | 0 |
| 11 | Conversation sidebar | `ConversationSidebar.tsx` | 0 |
| 12 | Login prompt | `LoginPrompt.tsx` | 0 |
| 13 | E2E test + cleanup | — | Manual |

**Total: 13 tasks, 10 backend tests, ~15 new files**
