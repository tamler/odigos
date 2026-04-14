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

# Set a key=value in .env (works on macOS and Linux, handles missing keys)
set_env() {
    local key="$1" val="$2" file="${3:-.env}"
    if grep -q "^${key}=" "$file" 2>/dev/null; then
        # Key exists — replace (portable sed -i)
        if [[ "$OSTYPE" == darwin* ]]; then
            sed -i '' "s|^${key}=.*|${key}=${val}|" "$file"
        else
            sed -i "s|^${key}=.*|${key}=${val}|" "$file"
        fi
    else
        echo "${key}=${val}" >> "$file"
    fi
}

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
mkdir -p data data/agent data/prompts data/plugins data/files skills plugins
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
    set_env "API_KEY" "$dashboard_key"
    info "Generated API_KEY"
else
    dashboard_key=$(grep "^API_KEY=" .env | cut -d= -f2-)
    info "API_KEY already set"
fi

# ── Generate SESSION_SECRET if not set ────────────────────────────
if ! grep -q "^SESSION_SECRET=.\+" .env 2>/dev/null; then
    session_secret=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
    echo "SESSION_SECRET=${session_secret}" >> .env
    info "Generated SESSION_SECRET"
fi

# ── LLM Configuration ──────────────────────────────────────────────
# Detect existing install: any *_API_KEY env var used by a provider.
if grep -qE "^(OPENROUTER|OPENAI|ANTHROPIC|GROQ)_API_KEY=.\S" .env 2>/dev/null; then
    info "LLM provider key already configured"
else
    echo ""
    bold "LLM Provider Setup"
    echo ""
    echo "  Odigos uses named providers + models + intelligence routing."
    echo "  The installer seeds sensible defaults — you can add more from the dashboard later."
    echo ""
    echo "  Choose your primary provider:"
    echo "    1) OpenRouter  — recommended, multi-model, Scout + DeepSeek + nano routing"
    echo "    2) OpenAI      — gpt-4o + gpt-4o-mini routing"
    echo "    3) Ollama      — local models on host"
    echo "    4) LM Studio   — local models on host"
    echo "    5) Custom      — single OpenAI-compatible endpoint"
    echo ""

    read -rp "  Choose provider [1-5] (default: 1): " provider_choice
    provider_choice=${provider_choice:-1}

    # provider_kind drives both env-var naming and the yaml template emitted below.
    case $provider_choice in
        1) provider_kind="openrouter" ;;
        2) provider_kind="openai" ;;
        3) provider_kind="ollama" ;;
        4) provider_kind="lmstudio" ;;
        5) provider_kind="custom" ;;
        *) provider_kind="openrouter" ;;
    esac

    # Collect API key. Local endpoints may not need one.
    echo ""
    case $provider_kind in
        openrouter)
            key_var="OPENROUTER_API_KEY"
            read -rp "  Enter OpenRouter API key: " llm_key
            while [ -z "$llm_key" ]; do
                warn "An OpenRouter API key is required."
                read -rp "  Enter OpenRouter API key: " llm_key
            done
            ;;
        openai)
            key_var="OPENAI_API_KEY"
            read -rp "  Enter OpenAI API key: " llm_key
            while [ -z "$llm_key" ]; do
                warn "An OpenAI API key is required."
                read -rp "  Enter OpenAI API key: " llm_key
            done
            ;;
        ollama|lmstudio)
            key_var=""
            llm_key=""
            ;;
        custom)
            read -rp "  Provider name (e.g. groq, anthropic): " custom_name
            custom_name=${custom_name:-custom}
            read -rp "  Base URL: " custom_url
            read -rp "  Model id (e.g. moonshotai/kimi-k2): " custom_model
            read -rp "  API key (press Enter if the endpoint doesn't need one): " llm_key
            # Upper-case provider name for the env var
            key_var="$(echo "$custom_name" | tr '[:lower:]' '[:upper:]')_API_KEY"
            ;;
    esac

    if [ -n "$key_var" ] && [ -n "$llm_key" ]; then
        set_env "$key_var" "$llm_key"
        info "Saved $key_var to .env"
    fi

    # ── Agent Name ────────────────────────────────────────────────────
    echo ""
    read -rp "  What would you like to name your agent? (default: Odigos): " agent_name
    agent_name=${agent_name:-Odigos}

    # ── Voice Setup (optional) ────────────────────────────────────────
    echo ""
    read -rp "$(echo -e "${BOLD}Enable voice mode? [y/N]:${NC} ")" enable_voice
    enable_voice=${enable_voice:-N}

    voice_stt="disabled"
    voice_tts="disabled"
    voice_tts_voice=""
    if [[ "$enable_voice" =~ ^[Yy]$ ]]; then
        read -rp "  Enter your Groq API key (get one at https://console.groq.com/keys): " groq_key
        while [ -z "$groq_key" ]; do
            warn "Groq API key is required for voice STT."
            read -rp "  Enter your Groq API key: " groq_key
        done
        set_env "GROQ_API_KEY" "$groq_key"
        info "Added GROQ_API_KEY to .env"
        voice_stt="groq"
        voice_tts="edge"
        voice_tts_voice="en-US-AriaNeural"
    fi

    # ── Auto-Update (optional) ────────────────────────────────────────
    echo ""
    read -rp "$(echo -e "${BOLD}Enable automatic updates? [y/N]:${NC} ")" enable_autoupdate
    enable_autoupdate=${enable_autoupdate:-N}

    autoupdate_enabled="false"
    autoupdate_auto_apply="false"
    if [[ "$enable_autoupdate" =~ ^[Yy]$ ]]; then
        autoupdate_enabled="true"
        autoupdate_auto_apply="true"
    fi

    # Write config.yaml — header (agent + api key)
    cat > config.yaml << EOF
# Odigos Configuration
# See config.yaml.example for all available options.

api_key: "${dashboard_key}"

agent:
  name: "${agent_name}"

EOF

    # Providers + Models + LLM routing — per-provider templates.
    case $provider_kind in
        openrouter)
            cat >> config.yaml << 'EOF'
providers:
  openrouter:
    base_url: "https://openrouter.ai/api/v1"
    api_key: "${OPENROUTER_API_KEY}"

models:
  scout:
    provider: openrouter
    id: "meta-llama/llama-4-scout"
    cost_in_per_mtok: 0.08
    cost_out_per_mtok: 0.30
    vision: true
    context_window: 131072
    notes: "Cheap + vision default"
  deepseek-v3.2:
    provider: openrouter
    id: "deepseek/deepseek-v3.2"
    cost_in_per_mtok: 0.27
    cost_out_per_mtok: 1.10
    vision: false
    context_window: 163840
    notes: "Reasoning tier"
  gpt-5-nano:
    provider: openrouter
    id: "openai/gpt-5-nano"
    cost_in_per_mtok: 0.05
    cost_out_per_mtok: 0.40
    vision: false
    context_window: 128000
    notes: "Fallback safety net"

llm:
  fast: scout
  smart: deepseek-v3.2
  background: scout
  fallback: gpt-5-nano
  max_tokens: 2048
  temperature: 0.7
  auto_route: true
EOF
            ;;
        openai)
            cat >> config.yaml << 'EOF'
providers:
  openai:
    base_url: "https://api.openai.com/v1"
    api_key: "${OPENAI_API_KEY}"

models:
  gpt-4o-mini:
    provider: openai
    id: "gpt-4o-mini"
    cost_in_per_mtok: 0.15
    cost_out_per_mtok: 0.60
    vision: true
    context_window: 128000
    notes: "Cheap + vision default"
  gpt-4o:
    provider: openai
    id: "gpt-4o"
    cost_in_per_mtok: 2.50
    cost_out_per_mtok: 10.00
    vision: true
    context_window: 128000
    notes: "Reasoning tier"

llm:
  fast: gpt-4o-mini
  smart: gpt-4o
  background: gpt-4o-mini
  fallback: gpt-4o-mini
  max_tokens: 2048
  temperature: 0.7
  auto_route: true
EOF
            ;;
        ollama)
            read -rp "  Local model id (default: llama3.2): " local_model
            local_model=${local_model:-llama3.2}
            cat >> config.yaml << EOF
providers:
  ollama:
    base_url: "http://host.docker.internal:11434/v1"
    api_key: ""

models:
  local:
    provider: ollama
    id: "${local_model}"
    cost_in_per_mtok: 0.0
    cost_out_per_mtok: 0.0
    vision: false
    context_window: 8192
    notes: "Local Ollama model"

llm:
  fast: local
  smart: local
  background: local
  fallback: local
  max_tokens: 2048
  temperature: 0.7
  auto_route: false
EOF
            ;;
        lmstudio)
            read -rp "  Local model id (default: default): " local_model
            local_model=${local_model:-default}
            cat >> config.yaml << EOF
providers:
  lmstudio:
    base_url: "http://host.docker.internal:1234/v1"
    api_key: ""

models:
  local:
    provider: lmstudio
    id: "${local_model}"
    cost_in_per_mtok: 0.0
    cost_out_per_mtok: 0.0
    vision: false
    context_window: 8192
    notes: "Local LM Studio model"

llm:
  fast: local
  smart: local
  background: local
  fallback: local
  max_tokens: 2048
  temperature: 0.7
  auto_route: false
EOF
            ;;
        custom)
            api_key_yaml=""
            if [ -n "$key_var" ] && [ -n "$llm_key" ]; then
                api_key_yaml="\"\${${key_var}}\""
            else
                api_key_yaml='""'
            fi
            cat >> config.yaml << EOF
providers:
  ${custom_name}:
    base_url: "${custom_url}"
    api_key: ${api_key_yaml}

models:
  primary:
    provider: ${custom_name}
    id: "${custom_model}"
    cost_in_per_mtok: 0.0
    cost_out_per_mtok: 0.0
    vision: false
    context_window: 0
    notes: "Configured during install"

llm:
  fast: primary
  smart: primary
  background: primary
  fallback: primary
  max_tokens: 2048
  temperature: 0.7
  auto_route: false
EOF
            ;;
    esac

    # Remaining sections — Starter-tier defaults tuned for the $15/mo hosted
    # tier. Personal users can loosen them in the dashboard or by editing
    # config.yaml directly.
    cat >> config.yaml << EOF

agent:
  max_tool_turns: 15
  run_timeout_seconds: 180

budget:
  daily_limit_usd: 0.50
  monthly_limit_usd: 10.00
  warn_threshold: 0.80

heartbeat:
  interval_seconds: 60
  max_todos_per_tick: 2
  idle_think_interval: 0
  morning_briefing: false

proactive:
  enabled: false

voice:
  stt_provider: "${voice_stt}"
  tts_provider: "${voice_tts}"
EOF

    if [ -n "$voice_tts_voice" ]; then
        echo "  tts_voice: \"${voice_tts_voice}\"" >> config.yaml
    fi

    cat >> config.yaml << EOF

auto_update:
  enabled: ${autoupdate_enabled}
  auto_apply: ${autoupdate_auto_apply}

server:
  host: "0.0.0.0"
  port: 8000
EOF
    info "Wrote config.yaml"
fi

# ── Account Setup (optional) ──────────────────────────────────────
echo ""
read -rp "$(echo -e "${BOLD}Create owner account now? [Y/n]:${NC} ")" create_account
create_account=${create_account:-Y}

if [[ "$create_account" =~ ^[Yy]$ ]]; then
    read -rp "  Username: " owner_username
    while [ -z "$owner_username" ]; do
        read -rp "  Username: " owner_username
    done
    read -srp "  Password (min 8 chars): " owner_password
    echo ""
    while [ ${#owner_password} -lt 8 ]; do
        read -srp "  Password too short. Try again (min 8 chars): " owner_password
        echo ""
    done
    mkdir -p data
    cat > data/seed_user.json << SEEDEOF
{"username": "$owner_username", "password": "$owner_password", "must_change_password": false}
SEEDEOF
    info "Account will be created on first startup"
    warn "Note: data/seed_user.json contains your password in plaintext."
    warn "It will be consumed and deleted on first startup."
fi

# ── Build and Start ─────────────────────────────────────────────────
echo ""
read -rp "$(echo -e "${BOLD}Build and start Odigos now? [Y/n]:${NC} ")" start_now
start_now=${start_now:-Y}

if [[ "$start_now" =~ ^[Yy]$ ]]; then
    echo ""
    # Always build locally from your working copy. Skipping the ghcr.io pull
    # because a stale registry image would overwrite fresher local code and
    # mislead users. First build takes ~5 minutes (embedding model download);
    # subsequent builds are cached.
    info "Building Docker image (first build takes ~5 minutes)..."
    docker compose build odigos

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
