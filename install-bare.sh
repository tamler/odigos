#!/usr/bin/env bash
set -euo pipefail

# Odigos bare-metal install — runs directly on the host without Docker.
# Requires: Python 3.12+, curl
# Tested on: Ubuntu 22.04+, Debian 12+, RHEL 9+, macOS 14+

# ── Helpers ─────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
err()   { echo -e "${RED}[x]${NC} $1"; }
bold()  { echo -e "${BOLD}$1${NC}"; }

echo ""
bold "=== Odigos Bare-Metal Setup ==="
echo ""

# ── Preflight ───────────────────────────────────────────────────────
# Check Python 3.12+
if ! command -v python3 &> /dev/null; then
    err "Python 3 is required. Install Python 3.12+ and try again."
    exit 1
fi

py_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
py_major=$(echo "$py_version" | cut -d. -f1)
py_minor=$(echo "$py_version" | cut -d. -f2)

if [ "$py_major" -lt 3 ] || { [ "$py_major" -eq 3 ] && [ "$py_minor" -lt 12 ]; }; then
    err "Python 3.12+ is required (found $py_version)."
    echo "  Install from: https://www.python.org/downloads/"
    exit 1
fi
info "Python $py_version found"

# Install uv if not present
if ! command -v uv &> /dev/null; then
    info "Installing uv (Python package manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv &> /dev/null; then
        err "Failed to install uv. Install manually: https://docs.astral.sh/uv/"
        exit 1
    fi
fi
info "uv found"

# ── Create directories ──────────────────────────────────────────────
mkdir -p data data/agent data/prompts data/plugins data/files skills plugins
info "Data directories ready"

# ── Install dependencies ────────────────────────────────────────────
info "Installing Python dependencies (this takes a minute on first run)..."
uv sync --quiet 2>&1 || uv sync
info "Dependencies installed"

# ── Download embedding model ────────────────────────────────────────
info "Pre-downloading embedding model (one-time, ~500MB)..."
uv run python3 -c "
from sentence_transformers import SentenceTransformer
import sys
print('  Loading nomic-embed-text-v1.5...', file=sys.stderr)
SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)
print('  Done.', file=sys.stderr)
" 2>&1
info "Embedding model cached"

# ── Environment setup ───────────────────────────────────────────────
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        info "Copied .env.example to .env"
    else
        touch .env
    fi
fi

# ── Generate API_KEY if not set ─────────────────────────────────────
if ! grep -q "^API_KEY=.\+" .env 2>/dev/null; then
    dashboard_key=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    if grep -q "^API_KEY=" .env 2>/dev/null; then
        sed -i.bak "s/^API_KEY=.*/API_KEY=${dashboard_key}/" .env && rm -f .env.bak
    else
        echo "API_KEY=${dashboard_key}" >> .env
    fi
    info "Generated API_KEY"
else
    dashboard_key=$(grep "^API_KEY=" .env | cut -d= -f2-)
    info "API_KEY already set"
fi

# ── LLM Configuration ──────────────────────────────────────────────
if grep -q "^LLM_API_KEY=.\+" .env && ! grep -q "your-api-key" .env; then
    info "LLM_API_KEY already configured"
else
    echo ""
    bold "LLM Provider Setup"
    echo ""
    echo "  Odigos works with any OpenAI-compatible API."
    echo ""
    echo "  Common providers:"
    echo "    1) OpenRouter  (https://openrouter.ai/api/v1) — multi-model, recommended"
    echo "    2) OpenAI      (https://api.openai.com/v1)"
    echo "    3) Ollama      (http://localhost:11434/v1) — free, local models"
    echo "    4) LM Studio   (http://localhost:1234/v1) — free, local models"
    echo "    5) Custom URL"
    echo ""

    read -rp "  Choose provider [1-5] (default: 1): " provider_choice
    provider_choice=${provider_choice:-1}

    case $provider_choice in
        1) base_url="https://openrouter.ai/api/v1"
           default_model="anthropic/claude-sonnet-4"
           fallback_model="openai/gpt-4.1-mini" ;;
        2) base_url="https://api.openai.com/v1"
           default_model="gpt-4o"
           fallback_model="gpt-4o-mini" ;;
        3) base_url="http://localhost:11434/v1"
           default_model="llama3.2"
           fallback_model="llama3.2" ;;
        4) base_url="http://localhost:1234/v1"
           default_model="default"
           fallback_model="default" ;;
        5) read -rp "  Enter base URL: " base_url
           read -rp "  Enter default model: " default_model
           read -rp "  Enter fallback model (or same): " fallback_model
           fallback_model=${fallback_model:-$default_model} ;;
        *) base_url="https://openrouter.ai/api/v1"
           default_model="anthropic/claude-sonnet-4"
           fallback_model="openai/gpt-4.1-mini" ;;
    esac

    echo ""
    if [[ "$base_url" == *"localhost"* ]]; then
        read -rp "  Enter LLM API key (press Enter to skip for local models): " llm_key
        llm_key=${llm_key:-no-key-needed}
    else
        read -rp "  Enter LLM API key: " llm_key
        while [ -z "$llm_key" ]; do
            warn "LLM API key is required for remote providers."
            read -rp "  Enter LLM API key: " llm_key
        done
    fi

    sed -i.bak "s|^LLM_API_KEY=.*|LLM_API_KEY=${llm_key}|" .env && rm -f .env.bak
    sed -i.bak "s|^LLM_BASE_URL=.*|LLM_BASE_URL=${base_url}|" .env && rm -f .env.bak
    sed -i.bak "s|^LLM_DEFAULT_MODEL=.*|LLM_DEFAULT_MODEL=${default_model}|" .env && rm -f .env.bak
    sed -i.bak "s|^LLM_FALLBACK_MODEL=.*|LLM_FALLBACK_MODEL=${fallback_model}|" .env && rm -f .env.bak
    info "Updated .env with LLM settings"

    cat > config.yaml << EOF
# Odigos Configuration
# See config.yaml.example for all available options.

api_key: "${dashboard_key}"

agent:
  name: "Odigos"

llm:
  base_url: "${base_url}"
  default_model: "${default_model}"
  fallback_model: "${fallback_model}"
  max_tokens: 4096
  temperature: 0.7

budget:
  daily_limit_usd: 5.0
  monthly_limit_usd: 50.0

server:
  host: "0.0.0.0"
  port: 8000
EOF
    info "Wrote config.yaml"
fi

# ── Voice Setup (optional) ────────────────────────────────────────
echo ""
read -rp "$(echo -e "${BOLD}Enable voice (text-to-speech and speech-to-text)? [y/N]:${NC} ")" enable_voice
enable_voice=${enable_voice:-N}

if [[ "$enable_voice" =~ ^[Yy]$ ]]; then
    if [ -f "./install-voice.sh" ]; then
        bash ./install-voice.sh
    else
        warn "install-voice.sh not found. Run it separately after install."
    fi
fi

# ── Systemd service (Linux only) ────────────────────────────────────
install_dir=$(pwd)
if [ "$(uname)" = "Linux" ] && command -v systemctl &> /dev/null; then
    echo ""
    read -rp "$(echo -e "${BOLD}Install as systemd service? [Y/n]:${NC} ")" install_service
    install_service=${install_service:-Y}

    if [[ "$install_service" =~ ^[Yy]$ ]]; then
        uv_path=$(command -v uv)
        service_user=$(whoami)

        sudo tee /etc/systemd/system/odigos.service > /dev/null << EOF
[Unit]
Description=Odigos AI Agent
After=network.target

[Service]
Type=simple
User=${service_user}
WorkingDirectory=${install_dir}
ExecStart=${uv_path} run python -m uvicorn odigos.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
EnvironmentFile=${install_dir}/.env

[Install]
WantedBy=multi-user.target
EOF

        sudo systemctl daemon-reload
        sudo systemctl enable odigos
        info "Systemd service installed and enabled"

        echo ""
        read -rp "$(echo -e "${BOLD}Start Odigos now? [Y/n]:${NC} ")" start_now
        start_now=${start_now:-Y}

        if [[ "$start_now" =~ ^[Yy]$ ]]; then
            sudo systemctl start odigos

            echo -n "  Waiting for Odigos to start..."
            healthy=false
            for i in $(seq 1 60); do
                if curl -sf "http://localhost:8000/health" > /dev/null 2>&1; then
                    healthy=true
                    break
                fi
                echo -n "."
                sleep 2
            done
            echo ""

            if $healthy; then
                echo ""
                info "Odigos is running!"
                echo ""
                bold "  Dashboard: http://$(hostname -f 2>/dev/null || echo localhost):8000"
                bold "  API Key:   ${dashboard_key}"
                echo ""
                echo "  Useful commands:"
                echo "    sudo systemctl status odigos     Status"
                echo "    sudo journalctl -u odigos -f     View logs"
                echo "    sudo systemctl restart odigos    Restart"
                echo "    sudo systemctl stop odigos       Stop"
                echo ""
            else
                warn "Odigos did not become healthy within 120s."
                echo "  Check logs: sudo journalctl -u odigos -f"
            fi
        fi
    fi
else
    # macOS or no systemd
    echo ""
    read -rp "$(echo -e "${BOLD}Start Odigos now? [Y/n]:${NC} ")" start_now
    start_now=${start_now:-Y}

    if [[ "$start_now" =~ ^[Yy]$ ]]; then
        echo ""
        info "Starting Odigos..."
        echo "  Press Ctrl+C to stop."
        echo ""
        uv run python -m uvicorn odigos.main:app --host 0.0.0.0 --port 8000
    else
        echo ""
        info "Setup complete. To start manually:"
        echo ""
        echo "    uv run python -m uvicorn odigos.main:app --host 0.0.0.0 --port 8000"
        echo ""
    fi
fi
