#!/usr/bin/env bash
set -euo pipefail

# ── Helpers ─────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
bold()  { echo -e "${BOLD}$1${NC}"; }

echo ""
bold "=== Odigos Setup ==="
echo ""

# ── Preflight ───────────────────────────────────────────────────────
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is required. Install it from https://docs.docker.com/get-docker/"
    exit 1
fi
info "Docker found"

if ! docker compose version &> /dev/null; then
    echo "Error: Docker Compose v2 is required (docker compose, not docker-compose)."
    echo "       Update Docker Desktop or install the compose plugin:"
    echo "       https://docs.docker.com/compose/install/"
    exit 1
fi
info "Docker Compose v2 found"

if ! docker info &> /dev/null; then
    echo "Error: Docker daemon is not running. Start Docker and try again."
    exit 1
fi
info "Docker daemon running"

# ── Create directories ──────────────────────────────────────────────
mkdir -p data data/plugins data/files skills plugins
info "Data directories ready"

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
    dashboard_key=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null \
                    || openssl rand -base64 32 | tr -d '/+=' | head -c 43)
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
        3) base_url="http://host.docker.internal:11434/v1"
           default_model="llama3.2"
           fallback_model="llama3.2" ;;
        4) base_url="http://host.docker.internal:1234/v1"
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
    # API key — local providers may not need one
    if [[ "$base_url" == *"localhost"* ]] || [[ "$base_url" == *"host.docker.internal"* ]]; then
        read -rp "  Enter LLM API key (press Enter to skip for local models): " llm_key
        llm_key=${llm_key:-no-key-needed}
    else
        read -rp "  Enter LLM API key: " llm_key
        while [ -z "$llm_key" ]; do
            warn "LLM API key is required for remote providers."
            read -rp "  Enter LLM API key: " llm_key
        done
    fi

    # Update .env with LLM settings
    sed -i.bak "s|^LLM_API_KEY=.*|LLM_API_KEY=${llm_key}|" .env && rm -f .env.bak
    sed -i.bak "s|^LLM_BASE_URL=.*|LLM_BASE_URL=${base_url}|" .env && rm -f .env.bak
    sed -i.bak "s|^LLM_DEFAULT_MODEL=.*|LLM_DEFAULT_MODEL=${default_model}|" .env && rm -f .env.bak
    sed -i.bak "s|^LLM_FALLBACK_MODEL=.*|LLM_FALLBACK_MODEL=${fallback_model}|" .env && rm -f .env.bak
    info "Updated .env with LLM settings"

    # Write config.yaml (settings, no secrets)
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

# ── Build and Start ─────────────────────────────────────────────────
echo ""
read -rp "$(echo -e "${BOLD}Build and start Odigos now? [Y/n]:${NC} ")" start_now
start_now=${start_now:-Y}

if [[ "$start_now" =~ ^[Yy]$ ]]; then
    echo ""
    # Try to pull pre-built image; fall back to local build
    info "Pulling Docker image..."
    if docker compose pull --quiet 2>/dev/null; then
        info "Image pulled"
    else
        warn "Pre-built image not available — building locally..."
        info "This takes a few minutes on first run."
        docker compose build
    fi

    info "Starting Odigos..."
    docker compose up -d

    echo ""
    # Wait for health
    port=$(grep "^ODIGOS_PORT=" .env 2>/dev/null | cut -d= -f2-)
    port=${port:-8000}
    domain=$(grep "^ODIGOS_DOMAIN=" .env 2>/dev/null | cut -d= -f2-)
    domain=${domain:-localhost}

    echo -n "  Waiting for Odigos to start..."
    healthy=false
    for i in $(seq 1 60); do
        if curl -sf "http://localhost:${port}/health" > /dev/null 2>&1; then
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
        if [ "$domain" != "localhost" ]; then
            bold "  Dashboard: https://${domain}"
        else
            bold "  Dashboard: http://localhost:${port}"
        fi
        echo ""
        bold "  API Key: ${dashboard_key}"
        echo ""
        echo "  Use this key to log in to the dashboard."
        echo "  It's saved in config.yaml and .env — change it there anytime."
        echo ""
        echo "  Useful commands:"
        echo "    docker compose logs -f odigos    View logs"
        echo "    docker compose restart odigos    Restart"
        echo "    docker compose down              Stop"
        echo ""
    else
        warn "Odigos did not become healthy within 120s."
        echo "  Check logs: docker compose logs odigos"
    fi
else
    echo ""
    info "Setup complete. To start later:"
    echo ""
    echo "    docker compose up -d --build"
    echo ""
fi
