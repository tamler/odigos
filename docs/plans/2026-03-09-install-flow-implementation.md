# Install Flow Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a single `install.sh` script and `README.md` that takes a fresh clone to a running-ready agent.

**Architecture:** An idempotent bash script that checks prerequisites, installs Python and CLI dependencies, creates config files from examples, and offers interactive auth setup. A CLI tool registry at the top of the script makes adding new tools trivial.

**Tech Stack:** Bash, pip, npm

**Design doc:** `docs/plans/2026-03-09-install-flow-design.md`

---

### Task 1: install.sh

**Files:**
- Create: `install.sh`

**Step 1: Create install.sh**

Create `install.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# ── CLI Tool Registry ────────────────────────────────────────────────
# Format: command_name|install_command|auth_command (auth optional)
CLI_TOOLS=(
    "gws|npm install -g @googleworkspace/cli|gws auth login"
)

# ── Colors ───────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[x]${NC} $1"; exit 1; }
skip()  { echo -e "    ... $1 (already done)"; }

# ── Preflight ────────────────────────────────────────────────────────
echo ""
echo "=== Odigos Install ==="
echo ""

command -v python3 >/dev/null 2>&1 || error "python3 not found. Install Python 3.12+: https://www.python.org/downloads/"

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 12 ]; }; then
    error "Python 3.12+ required (found $PYTHON_VERSION). Install: https://www.python.org/downloads/"
fi
info "Python $PYTHON_VERSION"

command -v pip3 >/dev/null 2>&1 || command -v pip >/dev/null 2>&1 || error "pip not found. Install: https://pip.pypa.io/en/stable/installation/"
PIP_CMD=$(command -v pip3 2>/dev/null || command -v pip)
info "pip found: $PIP_CMD"

command -v npm >/dev/null 2>&1 || error "npm not found. Install Node.js: https://nodejs.org/"
info "npm $(npm --version)"

# ── Python Dependencies ──────────────────────────────────────────────
echo ""
info "Installing Python dependencies..."
$PIP_CMD install -e ".[dev]" --quiet
info "Python dependencies installed"

# ── CLI Tools ────────────────────────────────────────────────────────
echo ""
info "Checking CLI tools..."

for entry in "${CLI_TOOLS[@]}"; do
    IFS='|' read -r cmd install_cmd auth_cmd <<< "$entry"

    if command -v "$cmd" >/dev/null 2>&1; then
        skip "$cmd installed"
    else
        info "Installing $cmd..."
        eval "$install_cmd"
        if command -v "$cmd" >/dev/null 2>&1; then
            info "$cmd installed"
        else
            warn "$cmd installation may have failed. You can install manually: $install_cmd"
        fi
    fi
done

# ── Config Files ─────────────────────────────────────────────────────
echo ""
info "Checking config files..."

if [ -f .env ]; then
    skip ".env exists"
else
    cp .env.example .env
    info "Created .env from .env.example"
    echo ""
    warn "Required: Set your API keys in .env"

    read -rp "  Enter TELEGRAM_BOT_TOKEN (or press Enter to skip): " telegram_token
    if [ -n "$telegram_token" ]; then
        sed -i.bak "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=$telegram_token|" .env && rm -f .env.bak
    fi

    read -rp "  Enter OPENROUTER_API_KEY (or press Enter to skip): " openrouter_key
    if [ -n "$openrouter_key" ]; then
        sed -i.bak "s|^OPENROUTER_API_KEY=.*|OPENROUTER_API_KEY=$openrouter_key|" .env && rm -f .env.bak
    fi

    if [ -z "$telegram_token" ] || [ -z "$openrouter_key" ]; then
        warn "Edit .env to add missing keys before running Odigos"
    fi
fi

if [ -f config.yaml ]; then
    skip "config.yaml exists"
else
    cp config.yaml.example config.yaml
    info "Created config.yaml from config.yaml.example"
fi

# ── Data Directory ───────────────────────────────────────────────────
mkdir -p data
skip "data/ directory ready"

# ── Auth Checks ──────────────────────────────────────────────────────
echo ""
info "Checking CLI tool authentication..."

for entry in "${CLI_TOOLS[@]}"; do
    IFS='|' read -r cmd install_cmd auth_cmd <<< "$entry"

    # Skip tools without auth commands
    [ -z "$auth_cmd" ] && continue

    # Skip tools that aren't installed
    command -v "$cmd" >/dev/null 2>&1 || continue

    # Check if already authenticated (tool-specific)
    if [ "$cmd" = "gws" ]; then
        # gws auth status exits 0 if authenticated
        if gws auth status >/dev/null 2>&1; then
            skip "$cmd authenticated"
            continue
        fi
    fi

    echo ""
    warn "$cmd is installed but not authenticated."
    read -rp "  Run authentication now? (y/n): " do_auth
    if [ "$do_auth" = "y" ] || [ "$do_auth" = "Y" ]; then
        echo ""
        info "Starting $cmd authentication..."
        echo "  If running on a headless server, copy the URL below into your browser."
        echo ""
        # Run auth, pipe through tee so user sees output, capture for URL extraction
        AUTH_OUTPUT=$($auth_cmd 2>&1 | tee /dev/tty) || true
        # Try to extract and highlight any OAuth URL
        AUTH_URL=$(echo "$AUTH_OUTPUT" | grep -oE 'https://[^ ]+' | head -1) || true
        if [ -n "$AUTH_URL" ]; then
            echo ""
            info "Auth URL (copy to browser if needed):"
            echo ""
            echo "  $AUTH_URL"
            echo ""
        fi
    else
        warn "Skipping $cmd auth. Run manually later: $auth_cmd"
    fi
done

# ── Done ─────────────────────────────────────────────────────────────
echo ""
echo "=== Install Complete ==="
echo ""
info "To start Odigos: odigos"
info "Or: python3 -m odigos.main"
echo ""
```

**Step 2: Make executable**

Run: `chmod +x install.sh`

**Step 3: Verify script syntax**

Run: `bash -n install.sh`
Expected: No output (valid syntax)

**Step 4: Commit**

```bash
git add install.sh
git commit -m "feat: add install.sh for full agent setup"
```

---

### Task 2: README.md

**Files:**
- Create: `README.md`

**Step 1: Create README.md**

Create `README.md`:

```markdown
# Odigos

Self-hosted personal AI agent.

## Prerequisites

- **Python 3.12+** -- [python.org/downloads](https://www.python.org/downloads/)
- **pip** -- included with Python 3.12+
- **Node.js / npm** -- [nodejs.org](https://nodejs.org/) (for CLI tool dependencies)
- **Telegram Bot Token** -- create via [@BotFather](https://t.me/BotFather)
- **OpenRouter API Key** -- [openrouter.ai/keys](https://openrouter.ai/keys)

## Install

```bash
git clone <repo-url> && cd odigos
./install.sh
```

The install script:
1. Installs Python dependencies
2. Installs CLI tools (Google Workspace CLI, etc.)
3. Creates `.env` and `config.yaml` from examples
4. Prompts for API keys
5. Offers authentication setup for CLI tools

Safe to re-run anytime to pick up new dependencies.

## Run

```bash
odigos
```

Or with a custom config:

```bash
odigos path/to/config.yaml
```

## Configuration

- `.env` -- API keys and secrets
- `config.yaml` -- agent settings, tool configuration, model selection

See `config.yaml.example` for all available options.
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with prerequisites and install instructions"
```

---

### Task 3: Update config.yaml.example with GWS section

**Files:**
- Modify: `config.yaml.example`

**Context:** The example config should show the `gws` section so users know it exists and how to enable it.

**Step 1: Add GWS config to example**

Append to `config.yaml.example`:

```yaml

gws:
  enabled: false
  timeout: 30
```

**Step 2: Commit**

```bash
git add config.yaml.example
git commit -m "docs: add gws config section to config.yaml.example"
```
