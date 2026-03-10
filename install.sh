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

if ! docker info &> /dev/null; then
    echo "Error: Docker daemon is not running. Start Docker and try again."
    exit 1
fi
info "Docker daemon running"

# ── Create directories ──────────────────────────────────────────────
mkdir -p data data/plugins data/chroma skills plugins
info "Data directories ready"

# ── LLM Configuration ──────────────────────────────────────────────
if [ -f .env ] && grep -q "LLM_API_KEY=" .env && ! grep -q "your-api-key" .env; then
    info ".env already configured"
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
           fallback_model="google/gemini-2.0-flash-001" ;;
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
           fallback_model="google/gemini-2.0-flash-001" ;;
    esac

    echo ""
    # API key — local providers may not need one
    if [[ "$base_url" == *"localhost"* ]] || [[ "$base_url" == *"host.docker.internal"* ]]; then
        read -rp "  Enter API key (press Enter to skip for local models): " api_key
        api_key=${api_key:-no-key-needed}
    else
        read -rp "  Enter API key: " api_key
        while [ -z "$api_key" ]; do
            warn "API key is required for remote providers."
            read -rp "  Enter API key: " api_key
        done
    fi

    # Write .env (secrets only)
    cat > .env << EOF
LLM_API_KEY=${api_key}
EOF
    info "Wrote .env (API key)"

    # Write config.yaml (settings only, no secrets)
    cat > config.yaml << EOF
# Odigos Configuration
# See config.yaml.example for all available options.

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
    echo -n "  Waiting for Odigos to start..."
    healthy=false
    for i in $(seq 1 60); do
        if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
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
        bold "  Dashboard: http://localhost:8000"
        echo ""
        echo "  Useful commands:"
        echo "    docker compose logs -f odigos    View logs"
        echo "    docker compose restart odigos    Restart"
        echo "    docker compose down              Stop"
        echo ""
        # Show auto-generated API key from logs
        api_key_line=$(docker compose logs odigos 2>&1 | grep "generated a random key" | tail -1 || true)
        if [ -n "$api_key_line" ]; then
            warn "Dashboard API key (from logs):"
            echo "    $api_key_line"
            echo ""
            echo "  Set 'api_key' in config.yaml for a persistent key."
            echo ""
        fi
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
