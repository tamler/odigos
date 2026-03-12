# Release Readiness: v1 Pre-Release Polish

**Date:** 2026-03-12
**Status:** Approved

## Context

Odigos is near release. The capability audit is complete (FileTool, conversation export, dead code cleanup, AgentService facade, plugin conversion, two-phase loading). This design covers the remaining gaps to make the project ready for public open-source release.

Peer communication protocol upgrade is deferred to post-release.

## 1. Plugin Metadata + Dashboard Plugin Page

### Plugin Metadata

Each plugin gets a `plugin.yaml` alongside its `__init__.py`:

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

Config key types: `string`, `url`, `secret`, `boolean`, `number`.

Secrets (`type: secret`) are stored in `.env`, all other settings in `config.yaml`.

### PluginManager Status Reporting

`PluginManager.loaded_plugins` currently stores `{"name", "file", "pattern"}`. Extend to include:

- `status`: `active` | `skipped` | `error`
- `metadata`: parsed `plugin.yaml` content (or None if no yaml)
- `error_message`: string if status is error

Add `PluginManager.get_plugin_metadata(plugins_dir)` that scans for `plugin.yaml` files and returns metadata for all discovered plugins (including ones not loaded).

### API Endpoint

`GET /api/plugins` already exists. Extend it to merge plugin metadata with load status:

```json
[
  {
    "id": "searxng",
    "name": "SearXNG Web Search",
    "description": "Adds web search capability using a SearXNG instance",
    "category": "tools",
    "status": "skipped",
    "requires": [{"label": "SearXNG instance", "url": "https://docs.searxng.org"}],
    "config_keys": [
      {"key": "searxng_url", "required": true, "description": "...", "type": "url", "configured": false},
      ...
    ]
  }
]
```

`POST /api/plugins/{id}/configure` accepts `{key: value}` pairs. Writes secrets to `.env`, settings to `config.yaml`. Returns success/error.

### Dashboard Plugin Page

New page at `/plugins` in the dashboard:

- Grid of plugin cards showing name, description, category badge, status indicator
- Status colors: green (active), gray (available/skipped), red (error)
- Click card to expand config form rendered from `config_keys`
- Save button writes config and shows restart hint
- External requirements shown as links

## 2. Config Updates

### config.yaml.example

Add missing sections:

```yaml
# File tool sandbox
file_access:
  allowed_paths:
    - "data/files"
```

### Dockerfile

Add `data/files` to the `mkdir` line.

### install.sh

Add `data/files` to the `mkdir -p` line.

## 3. README Update

### Prerequisites

Remove Telegram Bot Token (now a plugin). Keep:
- Docker (recommended) OR Python 3.12+ (bare metal)
- OpenRouter API Key (or any OpenAI-compatible provider)

### Install Sections

**Docker (recommended):**
```bash
git clone <repo-url> && cd odigos
./install.sh
```

**Run without Docker:**
```bash
git clone <repo-url> && cd odigos
pip install -e .        # or: uv sync
cp config.yaml.example config.yaml
# Edit config.yaml and create .env with LLM_API_KEY=...
odigos                  # or: uv run odigos
```

Include a systemd unit file template:

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

### Plugins Section

Brief explanation: plugins live in `plugins/`, configured via dashboard or config.yaml. Link to plugin page.

## 4. Release Verification Checklist

- [ ] Full test suite passes
- [ ] Docker build succeeds, container starts healthy
- [ ] Fresh install.sh on clean directory works
- [ ] Dashboard loads, chat works, export works
- [ ] Plugin page shows all plugins with correct status
- [ ] config.yaml.example covers all config options
- [ ] README accurately reflects install and run flows
