# Install Flow Design

**Date:** 2026-03-09
**Status:** Approved
**Phase:** 4

## Context

The agent has growing CLI tool dependencies (e.g., `gws` for Google Workspace). There's no install infrastructure -- users must manually install Python deps, CLI tools, configure files, and run auth flows. We need a single script that takes a fresh clone to a running agent.

## Decisions

1. **Single `install.sh`** -- one script for full setup. No Makefile, no Python post-install hooks.
2. **Install everything unconditionally** -- all CLI deps installed regardless of config. They're lightweight and avoids parsing YAML in bash.
3. **Idempotent** -- safe to re-run anytime. Checks state before acting, never overwrites existing config.
4. **Interactive auth with URL capture** -- detects missing auth, offers to run it, displays OAuth URLs prominently for headless/VPS environments.
5. **README.md** -- documents prerequisites and install instructions.

## Components

### 1. `install.sh`

Sections in order:

1. **Preflight** -- check for `python3`, `pip`, `npm`. Fail early with clear messages.
2. **Python deps** -- `pip install .`
3. **CLI tools** -- loop through registry of `(command, install_cmd, auth_cmd)` tuples. Skip already-installed.
4. **Config files** -- copy `.env.example` to `.env` and `config.yaml.example` to `config.yaml` if missing. Prompt for required `.env` values (TELEGRAM_BOT_TOKEN, OPENROUTER_API_KEY).
5. **Database** -- initialize/migrate via Python.
6. **Auth checks** -- for each CLI needing auth, detect if authenticated. Offer interactive setup, capture and display auth URLs for headless use.

### 2. CLI tool registry

Bash array at top of script:

```bash
CLI_TOOLS=(
    "gws|npm install -g @googleworkspace/cli|gws auth login"
)
```

Format: `command_name|install_command|auth_command`. Adding a new CLI tool = one line.

### 3. Auth URL capture

For tools that print OAuth URLs during auth, pipe through `tee` and grep for URLs to display prominently:

```
Authentication required for gws.
Visit this URL to authenticate:

  https://accounts.google.com/o/oauth2/...

Paste the authorization code below:
```

### 4. README.md

Minimal README with:
- Prerequisites: Python 3.12+, pip, Node.js/npm, Telegram bot token, OpenRouter API key
- Install: `./install.sh`
- Run: `odigos` or `python -m odigos.main`

## Error Handling

- Missing prerequisites: exit immediately with platform-specific install instructions
- Failed pip install: exit with error, no partial state
- Failed CLI install: warn and continue -- other tools still work
- User skips auth: print reminder and continue
- Re-run: every step checks before acting, never overwrites `.env` or `config.yaml`

## Testing

Manual testing only. Verify idempotency by running twice -- second run should be no-ops.
