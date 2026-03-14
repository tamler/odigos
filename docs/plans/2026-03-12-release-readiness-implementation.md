# Release Readiness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add plugin metadata (plugin.yaml), dashboard plugin page with config forms, update README/config/install for v1 release.

**Architecture:** Each plugin gets a `plugin.yaml` describing its name, description, config keys (typed), and external requirements. PluginManager reports load status per plugin. Dashboard renders plugin cards with config forms. Settings/secrets write to config.yaml/.env via existing API patterns.

**Tech Stack:** Python/FastAPI backend, React/TypeScript dashboard, PyYAML, lucide-react icons, shadcn/ui components

**Design doc:** `docs/plans/2026-03-12-release-readiness-design.md`

---

### Task 1: Create plugin.yaml files for all plugins

**Files:**
- Create: `plugins/searxng/plugin.yaml`
- Create: `plugins/gws/plugin.yaml`
- Create: `plugins/browser/plugin.yaml`
- Create: `plugins/channels/telegram/plugin.yaml`
- Modify: `plugins/providers/docling/plugin.yaml` (update to new format)

**Step 1: Create SearXNG plugin.yaml**

Create `plugins/searxng/plugin.yaml`:

```yaml
name: SearXNG Web Search
id: searxng
description: Adds web search capability using a SearXNG instance
category: tools
requires:
  - label: SearXNG instance
    url: https://docs.searxng.org
config_keys:
  - key: searxng_url
    required: true
    description: URL of your SearXNG instance
    type: url
  - key: searxng_username
    required: false
    description: SearXNG username (if auth is enabled)
    type: string
  - key: searxng_password
    required: false
    description: SearXNG password (if auth is enabled)
    type: secret
```

**Step 2: Create GWS plugin.yaml**

Create `plugins/gws/plugin.yaml`:

```yaml
name: Google Workspace
id: gws
description: Access Google Workspace (Gmail, Calendar, Drive) via the gws CLI
category: tools
requires:
  - label: gws CLI
    url: https://github.com/nichochar/gws
config_keys:
  - key: gws.enabled
    required: true
    description: Enable Google Workspace integration
    type: boolean
  - key: gws.timeout
    required: false
    description: Command timeout in seconds
    type: number
```

**Step 3: Create Browser plugin.yaml**

Create `plugins/browser/plugin.yaml`:

```yaml
name: Agent Browser
id: browser
description: Browser automation for web interaction and testing
category: tools
requires:
  - label: agent-browser CLI
    url: https://github.com/anthropics/agent-browser
config_keys:
  - key: browser.enabled
    required: true
    description: Enable browser automation
    type: boolean
  - key: browser.timeout
    required: false
    description: Browser action timeout in seconds
    type: number
```

**Step 4: Create Telegram plugin.yaml**

Create `plugins/channels/telegram/plugin.yaml`:

```yaml
name: Telegram Bot
id: telegram
description: Telegram bot channel for messaging your agent
category: channels
requires: []
config_keys:
  - key: telegram_bot_token
    required: true
    description: Bot token from @BotFather
    type: secret
  - key: telegram.mode
    required: false
    description: "Connection mode: polling or webhook"
    type: string
  - key: telegram.webhook_url
    required: false
    description: Webhook URL (only if mode is webhook)
    type: url
```

**Step 5: Update Docling plugin.yaml**

Replace contents of `plugins/providers/docling/plugin.yaml`:

```yaml
name: Docling Document Processor
id: docling
description: Deep document extraction with table, figure, and layout analysis
category: providers
requires:
  - label: docling Python package
    url: https://github.com/DS4SD/docling
config_keys: []
```

**Step 6: Commit**

```bash
git add plugins/searxng/plugin.yaml plugins/gws/plugin.yaml plugins/browser/plugin.yaml plugins/channels/telegram/plugin.yaml plugins/providers/docling/plugin.yaml
git commit -m "feat: add plugin.yaml metadata for all plugins"
```

---

### Task 2: PluginManager status reporting + metadata scanning

**Files:**
- Modify: `odigos/core/plugins.py`
- Create: `tests/test_plugin_metadata.py`

**Step 1: Write the failing tests**

Create `tests/test_plugin_metadata.py`:

```python
import pytest
from pathlib import Path

from odigos.core.plugins import PluginManager
from odigos.core.plugin_context import PluginContext
from odigos.tools.registry import ToolRegistry
from odigos.channels.base import ChannelRegistry


@pytest.fixture
def plugin_dir(tmp_path):
    """Create a minimal plugin directory with plugin.yaml."""
    plugin = tmp_path / "testplugin"
    plugin.mkdir()
    (plugin / "__init__.py").write_text(
        'def register(ctx): pass\n'
    )
    (plugin / "plugin.yaml").write_text(
        'name: Test Plugin\n'
        'id: testplugin\n'
        'description: A test plugin\n'
        'category: tools\n'
        'requires: []\n'
        'config_keys:\n'
        '  - key: test_key\n'
        '    required: true\n'
        '    description: A test key\n'
        '    type: string\n'
    )
    return tmp_path


class TestPluginMetadata:
    def test_loaded_plugins_include_status(self, plugin_dir):
        ctx = PluginContext(
            tool_registry=ToolRegistry(),
            channel_registry=ChannelRegistry(),
            config={},
        )
        pm = PluginManager(plugin_context=ctx)
        pm.load_all(str(plugin_dir))
        assert len(pm.loaded_plugins) == 1
        p = pm.loaded_plugins[0]
        assert p["status"] == "active"

    def test_failed_plugin_has_error_status(self, tmp_path):
        plugin = tmp_path / "badplugin"
        plugin.mkdir()
        (plugin / "__init__.py").write_text(
            'def register(ctx): raise ValueError("broken")\n'
        )
        ctx = PluginContext(
            tool_registry=ToolRegistry(),
            channel_registry=ChannelRegistry(),
            config={},
        )
        pm = PluginManager(plugin_context=ctx)
        pm.load_all(str(tmp_path))
        assert len(pm.loaded_plugins) == 1
        p = pm.loaded_plugins[0]
        assert p["status"] == "error"
        assert "broken" in p.get("error_message", "")

    def test_scan_plugin_metadata(self, plugin_dir):
        pm = PluginManager()
        metadata = pm.scan_metadata(str(plugin_dir))
        assert len(metadata) == 1
        m = metadata[0]
        assert m["id"] == "testplugin"
        assert m["name"] == "Test Plugin"
        assert m["category"] == "tools"
        assert len(m["config_keys"]) == 1

    def test_scan_metadata_missing_yaml(self, tmp_path):
        plugin = tmp_path / "noyaml"
        plugin.mkdir()
        (plugin / "__init__.py").write_text('def register(ctx): pass\n')
        pm = PluginManager()
        metadata = pm.scan_metadata(str(tmp_path))
        assert len(metadata) == 1
        assert metadata[0]["id"] == "noyaml"
        assert metadata[0]["name"] == "noyaml"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plugin_metadata.py -v`
Expected: FAIL — status key missing, scan_metadata doesn't exist

**Step 3: Implement status reporting and metadata scanning**

In `odigos/core/plugins.py`, add `import yaml` at top (after existing imports). Then modify `_load_plugin` and add `scan_metadata`:

Change the `_load_plugin` method — replace the two `self.loaded_plugins.append(...)` calls and the error handling:

Replace the register pattern block (lines 110-118):
```python
        # Try new pattern: register(ctx)
        register_fn = getattr(module, "register", None)
        if register_fn is not None and callable(register_fn) and self._ctx is not None:
            try:
                register_fn(self._ctx)
                self.loaded_plugins.append({"name": stem, "file": str(py_file), "pattern": "register", "status": "active"})
                return
            except Exception as e:
                logger.warning("Plugin %s register() failed", py_file, exc_info=True)
                self.loaded_plugins.append({"name": stem, "file": str(py_file), "pattern": "register", "status": "error", "error_message": str(e)})
                return
```

Replace the hooks pattern block (lines 120-129):
```python
        # Fall back to legacy pattern: hooks dict
        hooks = getattr(module, "hooks", None)
        if hooks and isinstance(hooks, dict) and self._tracer:
            hook_count = 0
            for event_type, callback in hooks.items():
                if callable(callback):
                    self._tracer.subscribe(event_type, callback)
                    hook_count += 1
            self.loaded_plugins.append({"name": stem, "file": str(py_file), "pattern": "hooks", "hook_count": hook_count, "status": "active"})
            return
```

Add the `scan_metadata` method after `reload`:

```python
    def scan_metadata(self, plugins_dir: str) -> list[dict]:
        """Scan plugin directories for plugin.yaml metadata files.

        Returns metadata for all discovered plugins, even if not loaded.
        """
        import yaml

        results = []
        plugins_path = Path(plugins_dir)
        if not plugins_path.exists():
            return results

        # Scan top-level plugin dirs
        for subdir in sorted(plugins_path.iterdir()):
            if not subdir.is_dir() or subdir.name.startswith("__"):
                continue

            # Category subdirs (providers/, tools/, channels/)
            if subdir.name in ("providers", "tools", "channels"):
                for nested in sorted(subdir.iterdir()):
                    if nested.is_dir() and not nested.name.startswith("__"):
                        meta = self._read_plugin_yaml(nested)
                        if meta:
                            results.append(meta)
                continue

            meta = self._read_plugin_yaml(subdir)
            if meta:
                results.append(meta)

        return results

    @staticmethod
    def _read_plugin_yaml(plugin_dir: Path) -> dict | None:
        """Read and parse a plugin.yaml, falling back to defaults."""
        init = plugin_dir / "__init__.py"
        if not init.exists():
            return None

        yaml_file = plugin_dir / "plugin.yaml"
        if yaml_file.exists():
            import yaml
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f) or {}
                data.setdefault("id", plugin_dir.name)
                data.setdefault("name", plugin_dir.name)
                data.setdefault("description", "")
                data.setdefault("category", "tools")
                data.setdefault("requires", [])
                data.setdefault("config_keys", [])
                return data
            except Exception:
                logger.warning("Failed to parse %s", yaml_file)

        # No yaml — return minimal metadata
        return {
            "id": plugin_dir.name,
            "name": plugin_dir.name,
            "description": "",
            "category": "tools",
            "requires": [],
            "config_keys": [],
        }
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_plugin_metadata.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add odigos/core/plugins.py tests/test_plugin_metadata.py
git commit -m "feat: add plugin status reporting and metadata scanning"
```

---

### Task 3: Plugin API endpoint — merge metadata with load status

**Files:**
- Modify: `odigos/api/plugins.py`
- Modify: `odigos/main.py` (add `app.state.plugin_manager`)
- Create: `tests/test_api_plugins.py`

**Step 1: Write the failing tests**

Create `tests/test_api_plugins.py`:

```python
import pytest
from unittest.mock import MagicMock


class TestPluginAPI:
    def test_list_plugins_merges_metadata_and_status(self):
        from odigos.api.plugins import _merge_plugins

        metadata = [
            {
                "id": "searxng",
                "name": "SearXNG Web Search",
                "description": "Adds web search",
                "category": "tools",
                "requires": [],
                "config_keys": [
                    {"key": "searxng_url", "required": True, "description": "URL", "type": "url"},
                ],
            },
        ]
        loaded = [
            {"name": "searxng", "file": "plugins/searxng/__init__.py", "pattern": "register", "status": "active"},
        ]
        settings = MagicMock()
        settings.searxng_url = "http://localhost:8080"

        result = _merge_plugins(metadata, loaded, settings)
        assert len(result) == 1
        p = result[0]
        assert p["id"] == "searxng"
        assert p["status"] == "active"
        assert p["config_keys"][0]["configured"] is True

    def test_unconfigured_plugin_shows_available(self):
        from odigos.api.plugins import _merge_plugins

        metadata = [
            {
                "id": "searxng",
                "name": "SearXNG",
                "description": "",
                "category": "tools",
                "requires": [],
                "config_keys": [
                    {"key": "searxng_url", "required": True, "description": "URL", "type": "url"},
                ],
            },
        ]
        loaded = []
        settings = MagicMock()
        settings.searxng_url = ""

        result = _merge_plugins(metadata, loaded, settings)
        assert result[0]["status"] == "available"
        assert result[0]["config_keys"][0]["configured"] is False
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api_plugins.py -v`
Expected: FAIL — `_merge_plugins` doesn't exist

**Step 3: Rewrite the plugins API endpoint**

Replace `odigos/api/plugins.py`:

```python
"""Plugins list and configuration API endpoints."""

from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from odigos.api.deps import get_plugin_manager, get_settings, require_api_key
from odigos.api.settings import _update_env_file

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


def _resolve_setting(settings, key: str):
    """Resolve a dotted config key like 'gws.enabled' from Settings."""
    parts = key.split(".", 1)
    obj = settings
    for part in parts:
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj


def _merge_plugins(metadata: list[dict], loaded: list[dict], settings) -> list[dict]:
    """Merge plugin metadata with load status and config state."""
    loaded_by_name = {p["name"]: p for p in loaded}
    result = []

    for meta in metadata:
        plugin_id = meta["id"]
        load_info = loaded_by_name.get(plugin_id, {})
        status = load_info.get("status", "available")

        # Annotate config keys with configured state
        config_keys = []
        for ck in meta.get("config_keys", []):
            value = _resolve_setting(settings, ck["key"])
            configured = bool(value) if value is not None else False
            config_keys.append({**ck, "configured": configured})

        result.append({
            "id": plugin_id,
            "name": meta.get("name", plugin_id),
            "description": meta.get("description", ""),
            "category": meta.get("category", "tools"),
            "status": status,
            "error_message": load_info.get("error_message"),
            "requires": meta.get("requires", []),
            "config_keys": config_keys,
        })

    return result


@router.get("/plugins")
async def list_plugins(
    plugin_manager=Depends(get_plugin_manager),
    settings=Depends(get_settings),
):
    """Return all plugins with metadata, load status, and config state."""
    metadata = plugin_manager.scan_metadata("plugins")
    merged = _merge_plugins(metadata, plugin_manager.loaded_plugins, settings)
    return {"plugins": merged}


class PluginConfigUpdate(BaseModel):
    values: dict[str, str | bool | int | float]


@router.post("/plugins/{plugin_id}/configure")
async def configure_plugin(
    plugin_id: str,
    update: PluginConfigUpdate,
    request: Request,
    plugin_manager=Depends(get_plugin_manager),
    settings=Depends(get_settings),
):
    """Write plugin config values to config.yaml (settings) and .env (secrets)."""
    # Find the plugin metadata to know which keys are secrets
    metadata = plugin_manager.scan_metadata("plugins")
    plugin_meta = next((m for m in metadata if m["id"] == plugin_id), None)
    if not plugin_meta:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")

    secret_keys = {
        ck["key"] for ck in plugin_meta.get("config_keys", []) if ck.get("type") == "secret"
    }

    config_path = Path(request.app.state.config_path)
    env_path = Path(request.app.state.env_path)

    # Load existing config.yaml
    yaml_config: dict = {}
    if config_path.exists():
        with open(config_path) as f:
            yaml_config = yaml.safe_load(f) or {}

    for key, value in update.values.items():
        if key in secret_keys:
            # Secrets go to .env — convert dotted key to ENV_VAR format
            env_key = key.upper().replace(".", "_")
            _update_env_file(env_path, env_key, str(value))
        else:
            # Settings go to config.yaml — handle dotted keys
            parts = key.split(".")
            target = yaml_config
            for part in parts[:-1]:
                if part not in target:
                    target[part] = {}
                target = target[part]
            target[parts[-1]] = value

    # Write updated config.yaml
    with open(config_path, "w") as f:
        yaml.dump(yaml_config, f, default_flow_style=False)

    return {"status": "ok", "message": "Configuration saved. Restart to apply changes."}
```

**Step 4: Add `app.state.plugin_manager` to main.py**

In `odigos/main.py`, after the line `plugin_manager.load_all("plugins")`, add:

```python
    app.state.plugin_manager = plugin_manager
```

**Step 5: Run tests**

Run: `uv run pytest tests/test_api_plugins.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add odigos/api/plugins.py odigos/main.py tests/test_api_plugins.py
git commit -m "feat: plugin API with metadata merging and config endpoint"
```

---

### Task 4: Dashboard Plugins page

**Files:**
- Create: `dashboard/src/pages/PluginsPage.tsx`
- Modify: `dashboard/src/App.tsx` (add route)
- Modify: `dashboard/src/layouts/AppLayout.tsx` (add nav link)

**Step 1: Create PluginsPage.tsx**

Create `dashboard/src/pages/PluginsPage.tsx`:

```tsx
import { useState, useEffect, useCallback } from 'react'
import { get, post } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Puzzle, ExternalLink, Check, X, AlertCircle } from 'lucide-react'

interface ConfigKey {
  key: string
  required: boolean
  description: string
  type: string
  configured: boolean
}

interface Requirement {
  label: string
  url: string
}

interface Plugin {
  id: string
  name: string
  description: string
  category: string
  status: string
  error_message?: string
  requires: Requirement[]
  config_keys: ConfigKey[]
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    active: 'bg-green-500/10 text-green-500 border-green-500/20',
    available: 'bg-muted text-muted-foreground border-border',
    skipped: 'bg-muted text-muted-foreground border-border',
    error: 'bg-red-500/10 text-red-500 border-red-500/20',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full border ${styles[status] || styles.available}`}>
      {status}
    </span>
  )
}

function CategoryBadge({ category }: { category: string }) {
  return (
    <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
      {category}
    </span>
  )
}

function PluginCard({ plugin, onSaved }: { plugin: Plugin; onSaved: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const [values, setValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  const hasConfigKeys = plugin.config_keys.length > 0

  async function handleSave() {
    setSaving(true)
    try {
      // Convert types
      const typed: Record<string, string | boolean | number> = {}
      for (const ck of plugin.config_keys) {
        const v = values[ck.key]
        if (v === undefined || v === '') continue
        if (ck.type === 'boolean') typed[ck.key] = v === 'true'
        else if (ck.type === 'number') typed[ck.key] = Number(v)
        else typed[ck.key] = v
      }
      await post(`/api/plugins/${plugin.id}/configure`, { values: typed })
      toast.success('Configuration saved. Restart to apply.')
      onSaved()
    } catch {
      toast.error('Failed to save configuration')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="border rounded-lg p-4 space-y-3">
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h3 className="font-medium text-sm">{plugin.name}</h3>
            <CategoryBadge category={plugin.category} />
            <StatusBadge status={plugin.status} />
          </div>
          <p className="text-sm text-muted-foreground">{plugin.description}</p>
        </div>
        {hasConfigKeys && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? 'Close' : 'Configure'}
          </Button>
        )}
      </div>

      {plugin.error_message && (
        <div className="flex items-center gap-2 text-sm text-red-500">
          <AlertCircle className="h-4 w-4" />
          {plugin.error_message}
        </div>
      )}

      {plugin.requires.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {plugin.requires.map((r, i) => (
            <a
              key={i}
              href={r.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <ExternalLink className="h-3 w-3" />
              {r.label}
            </a>
          ))}
        </div>
      )}

      {expanded && hasConfigKeys && (
        <div className="space-y-3 pt-2 border-t">
          {plugin.config_keys.map((ck) => (
            <div key={ck.key} className="space-y-1">
              <div className="flex items-center gap-2">
                <label className="text-sm font-medium">{ck.key}</label>
                {ck.required && <span className="text-xs text-red-500">required</span>}
                {ck.configured ? (
                  <Check className="h-3 w-3 text-green-500" />
                ) : (
                  <X className="h-3 w-3 text-muted-foreground" />
                )}
              </div>
              <p className="text-xs text-muted-foreground">{ck.description}</p>
              {ck.type === 'boolean' ? (
                <select
                  className="w-full px-3 py-1.5 rounded-md border bg-background text-sm"
                  value={values[ck.key] || ''}
                  onChange={(e) => setValues({ ...values, [ck.key]: e.target.value })}
                >
                  <option value="">-- select --</option>
                  <option value="true">Enabled</option>
                  <option value="false">Disabled</option>
                </select>
              ) : (
                <input
                  type={ck.type === 'secret' ? 'password' : 'text'}
                  placeholder={ck.type === 'secret' ? '********' : `Enter ${ck.key}`}
                  className="w-full px-3 py-1.5 rounded-md border bg-background text-sm"
                  value={values[ck.key] || ''}
                  onChange={(e) => setValues({ ...values, [ck.key]: e.target.value })}
                />
              )}
            </div>
          ))}
          <Button size="sm" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving...' : 'Save Configuration'}
          </Button>
        </div>
      )}
    </div>
  )
}

export default function PluginsPage() {
  const [plugins, setPlugins] = useState<Plugin[]>([])

  const load = useCallback(async () => {
    try {
      const data = await get<{ plugins: Plugin[] }>('/api/plugins')
      setPlugins(data.plugins)
    } catch {
      toast.error('Failed to load plugins')
    }
  }, [])

  useEffect(() => { load() }, [load])

  const active = plugins.filter((p) => p.status === 'active')
  const available = plugins.filter((p) => p.status !== 'active')

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-4xl mx-auto px-6 py-8 space-y-8">
        <div className="flex items-center gap-3">
          <Puzzle className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-lg font-semibold">Plugins</h1>
        </div>

        {active.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-sm font-medium text-muted-foreground">Active</h2>
            <div className="space-y-3">
              {active.map((p) => (
                <PluginCard key={p.id} plugin={p} onSaved={load} />
              ))}
            </div>
          </div>
        )}

        {available.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-sm font-medium text-muted-foreground">Available</h2>
            <div className="space-y-3">
              {available.map((p) => (
                <PluginCard key={p.id} plugin={p} onSaved={load} />
              ))}
            </div>
          </div>
        )}

        {plugins.length === 0 && (
          <p className="text-sm text-muted-foreground">No plugins found.</p>
        )}
      </div>
    </div>
  )
}
```

**Step 2: Add route in App.tsx**

In `dashboard/src/App.tsx`, add import:

```tsx
import PluginsPage from './pages/PluginsPage'
```

Add route after the `/agents` route:

```tsx
              <Route path="/plugins" element={<PluginsPage />} />
```

**Step 3: Add nav link in AppLayout.tsx**

In `dashboard/src/layouts/AppLayout.tsx`, add `Puzzle` to the lucide-react import line.

Add a new NavLink block before the Settings NavLink (before line 240):

```tsx
            <Tooltip>
              <TooltipTrigger>
                <NavLink
                  to="/plugins"
                  className={({ isActive }) =>
                    `flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${
                      isActive ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                    }`
                  }
                >
                  <Puzzle className="h-4 w-4 shrink-0" />
                  {!collapsed && 'Plugins'}
                </NavLink>
              </TooltipTrigger>
              {collapsed && <TooltipContent side="right">Plugins</TooltipContent>}
            </Tooltip>
```

**Step 4: Build and verify**

Run: `cd dashboard && npm run build`
Expected: Build succeeds

**Step 5: Commit**

```bash
git add dashboard/src/pages/PluginsPage.tsx dashboard/src/App.tsx dashboard/src/layouts/AppLayout.tsx dashboard/dist/
git commit -m "feat: add Plugins page to dashboard with config forms"
```

---

### Task 5: Config, Dockerfile, and install.sh updates

**Files:**
- Modify: `config.yaml.example`
- Modify: `Dockerfile`
- Modify: `install.sh`

**Step 1: Update config.yaml.example**

Add after the `browser` section (before `approval`):

```yaml
# File tool sandbox
file_access:
  allowed_paths:
    - "data/files"
```

**Step 2: Update Dockerfile**

Change the `mkdir` line from:
```dockerfile
RUN mkdir -p /app/data /app/data/plugins
```
To:
```dockerfile
RUN mkdir -p /app/data /app/data/plugins /app/data/files
```

**Step 3: Update install.sh**

Change the `mkdir -p` line from:
```bash
mkdir -p data data/plugins skills plugins
```
To:
```bash
mkdir -p data data/plugins data/files skills plugins
```

**Step 4: Commit**

```bash
git add config.yaml.example Dockerfile install.sh
git commit -m "chore: add file_access config, data/files dir to Docker and install"
```

---

### Task 6: README rewrite

**Files:**
- Modify: `README.md`

**Step 1: Rewrite README.md**

Replace entire contents of `README.md`:

```markdown
# Odigos

Self-hosted personal AI agent with a web dashboard, plugin system, and autonomous capabilities.

## Prerequisites

- **Docker** (recommended) -- [docs.docker.com/get-docker](https://docs.docker.com/get-docker/)
- **LLM API Key** -- any OpenAI-compatible provider ([OpenRouter](https://openrouter.ai/keys), OpenAI, Ollama, LM Studio, etc.)

## Quick Start (Docker)

```bash
git clone <repo-url> && cd odigos
./install.sh
```

The install script configures your LLM provider, builds the Docker image, and starts Odigos. Open **http://localhost:8000** when ready.

**Useful commands:**
```bash
docker compose logs -f odigos    # View logs
docker compose restart odigos    # Restart
docker compose down              # Stop
```

## Run Without Docker

```bash
git clone <repo-url> && cd odigos
pip install -e .
cp config.yaml.example config.yaml
```

Create a `.env` file with your API key:
```bash
echo "LLM_API_KEY=your-key-here" > .env
```

Start the agent:
```bash
odigos
```

### Run as a systemd Service

Create `/etc/systemd/system/odigos.service`:

```ini
[Unit]
Description=Odigos AI Agent
After=network.target

[Service]
Type=simple
User=odigos
WorkingDirectory=/opt/odigos
ExecStart=/opt/odigos/.venv/bin/python -m uvicorn odigos.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
EnvironmentFile=/opt/odigos/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now odigos
```

## Configuration

- `.env` -- API keys and secrets (never committed)
- `config.yaml` -- agent settings, model selection, tool configuration

See `config.yaml.example` for all available options.

## Plugins

Odigos uses a plugin system for optional capabilities. Plugins live in the `plugins/` directory and can be configured through the dashboard at **Plugins** or directly in `config.yaml`.

**Available plugins:**

| Plugin | Category | What it adds |
|--------|----------|-------------|
| SearXNG | Search | Web search via a SearXNG instance |
| Google Workspace | Tools | Gmail, Calendar, Drive access via gws CLI |
| Agent Browser | Tools | Browser automation for web interaction |
| Telegram | Channel | Telegram bot interface for your agent |
| Docling | Provider | Deep document extraction (tables, figures, layout) |

Enable a plugin by providing its required configuration (API keys, URLs, etc.) in the dashboard or config.yaml. Restart to apply changes.

## Architecture

- **FastAPI** backend with WebSocket support
- **React** dashboard (built, served from `/dashboard/dist`)
- **SQLite** for all storage (conversations, memory, goals, budget)
- **sqlite-vec + FTS5** for hybrid vector/text search
- **Plugin system** for optional tools, channels, and providers
- **Local embeddings** (nomic-embed-text-v1.5, runs on CPU)
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README for v1 — Docker, bare-metal, systemd, plugins"
```

---

### Task 7: Release verification

**Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 2: Verify Docker build**

Run: `docker compose build`
Expected: Build succeeds

**Step 3: Verify plugin metadata loads**

Run: `uv run python -c "
from odigos.core.plugins import PluginManager
pm = PluginManager()
meta = pm.scan_metadata('plugins')
for m in meta:
    print(f'{m[\"id\"]:15s} {m[\"name\"]:30s} {m[\"category\"]:10s} {len(m[\"config_keys\"])} keys')
"`
Expected: Lists all 5 plugins with their metadata

**Step 4: Verify no dead imports**

Run: `grep -r "from odigos.core.peers" odigos/ tests/` — should return nothing

**Step 5: Commit if any fixes were needed**

---

## Summary of Changes

| File | Action |
|------|--------|
| `plugins/searxng/plugin.yaml` | New: plugin metadata |
| `plugins/gws/plugin.yaml` | New: plugin metadata |
| `plugins/browser/plugin.yaml` | New: plugin metadata |
| `plugins/channels/telegram/plugin.yaml` | New: plugin metadata |
| `plugins/providers/docling/plugin.yaml` | Updated to new format |
| `odigos/core/plugins.py` | Add status reporting + scan_metadata |
| `tests/test_plugin_metadata.py` | New: metadata tests |
| `odigos/api/plugins.py` | Rewrite with metadata merge + configure endpoint |
| `odigos/main.py` | Add app.state.plugin_manager |
| `tests/test_api_plugins.py` | New: API tests |
| `dashboard/src/pages/PluginsPage.tsx` | New: plugin dashboard page |
| `dashboard/src/App.tsx` | Add /plugins route |
| `dashboard/src/layouts/AppLayout.tsx` | Add Plugins nav link |
| `config.yaml.example` | Add file_access section |
| `Dockerfile` | Add data/files directory |
| `install.sh` | Add data/files directory |
| `README.md` | Full rewrite for v1 |
