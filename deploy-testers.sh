#!/usr/bin/env bash
set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────
TESTERS=("jessica" "florence" "jason")
PORTS=(8010 8011 8012)
BASE_DIR="/opt/odigos"
REPO_URL="https://github.com/tamler/odigos.git"

GREEN='\033[0;32m'
BOLD='\033[1m'
NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $1"; }
bold()  { echo -e "${BOLD}$1${NC}"; }

bold "=== Odigos Tester Deployment ==="
echo ""

# ── Step 1: Clone repo ──────────────────────────────────────────────
if [ ! -d "$BASE_DIR/repo" ]; then
    info "Cloning Odigos repo..."
    mkdir -p "$BASE_DIR"
    git clone "$REPO_URL" "$BASE_DIR/repo"
else
    info "Repo exists, pulling latest..."
    cd "$BASE_DIR/repo" && git pull && cd -
fi

# ── Step 2: Check LLM key ────────────────────────────────────────────
ENV_FILE="$BASE_DIR/.env"
if [ ! -f "$ENV_FILE" ] || ! grep -q "^LLM_API_KEY=.\+" "$ENV_FILE" 2>/dev/null; then
    echo "ERROR: LLM_API_KEY not configured."
    echo "Create $ENV_FILE first:"
    echo "  echo 'LLM_API_KEY=sk-or-...' > $ENV_FILE"
    exit 1
else
    info "LLM_API_KEY configured"
fi

# ── Step 3: Create tester directories and configs ────────────────────
declare -A API_KEYS

for i in "${!TESTERS[@]}"; do
    name="${TESTERS[$i]}"
    port="${PORTS[$i]}"
    dir="$BASE_DIR/testers/$name"

    mkdir -p "$dir/data/agent" "$dir/data/prompts" "$dir/data/plugins" "$dir/data/files" "$dir/skills" "$dir/plugins"

    # Generate API key if not already set
    if [ -f "$dir/config.yaml" ] && grep -q "^api_key:" "$dir/config.yaml" 2>/dev/null; then
        api_key=$(grep "^api_key:" "$dir/config.yaml" | sed 's/api_key: *"\(.*\)"/\1/')
    else
        api_key=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    fi
    API_KEYS[$name]="$api_key"

    # Capitalize first letter for display name
    display_name="$(echo "${name:0:1}" | tr '[:lower:]' '[:upper:]')${name:1}"

    cat > "$dir/config.yaml" << YAML
api_key: "${api_key}"

agent:
  name: "${display_name}'s Agent"
  max_tool_turns: 15
  run_timeout_seconds: 180

database:
  path: "data/odigos.db"

llm:
  base_url: "https://openrouter.ai/api/v1"
  default_model: "deepseek/deepseek-v3.2"
  fallback_model: "inception/mercury-2"
  max_tokens: 4096
  temperature: 0.7

budget:
  daily_limit_usd: 2.00
  monthly_limit_usd: 20.00
  warn_threshold: 0.8

searxng_url: "http://host.docker.internal:8083"

heartbeat:
  interval_seconds: 300
  max_todos_per_tick: 3
  idle_think_interval: 0

file_access:
  allowed_paths:
    - "data/files"

approval:
  enabled: false

skills:
  path: "skills"
YAML

    # Symlink .env
    ln -sf "$BASE_DIR/.env" "$dir/.env"

    info "Created config for $display_name (port $port)"
done

# ── Step 4: Write docker-compose.yml ─────────────────────────────────
cat > "$BASE_DIR/docker-compose.yml" << 'COMPOSEFILE'
services:
COMPOSEFILE

for i in "${!TESTERS[@]}"; do
    name="${TESTERS[$i]}"
    port="${PORTS[$i]}"

    cat >> "$BASE_DIR/docker-compose.yml" << COMPOSESVC
  odigos-${name}:
    build: ./repo
    container_name: odigos-${name}
    restart: unless-stopped
    privileged: true
    extra_hosts:
      - "host.docker.internal:host-gateway"
    ports:
      - "127.0.0.1:${port}:8000"
    volumes:
      - ./testers/${name}/config.yaml:/app/config.yaml:ro
      - ./testers/${name}/.env:/app/.env:ro
      - ./testers/${name}/data:/app/data
      - ./testers/${name}/skills:/app/skills:ro
      - ./testers/${name}/plugins:/app/plugins:ro
    environment:
      - LLM_API_KEY=\${LLM_API_KEY}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 120s

COMPOSESVC
done

info "Wrote docker-compose.yml"

# ── Step 5: Build image ──────────────────────────────────────────────
info "Building Docker image (this may take a few minutes)..."
cd "$BASE_DIR"
docker compose build --no-cache odigos-jessica
info "Image built"

# ── Step 6: Fix data directory ownership ─────────────────────────────
info "Fixing data directory permissions..."
ODIGOS_IDS=$(docker compose run --rm --no-deps -T odigos-jessica id)
ODIGOS_UID=$(echo "$ODIGOS_IDS" | grep -o 'uid=[0-9]*' | cut -d= -f2)
ODIGOS_GID=$(echo "$ODIGOS_IDS" | grep -o 'gid=[0-9]*' | cut -d= -f2)

for name in "${TESTERS[@]}"; do
    chown -R "$ODIGOS_UID:$ODIGOS_GID" "$BASE_DIR/testers/$name/data"
done
info "Permissions fixed (UID=$ODIGOS_UID, GID=$ODIGOS_GID)"

# ── Step 7: Update Caddy ────────────────────────────────────────────
if ! grep -q "jessica.uxrls.com" /etc/caddy/Caddyfile; then
    info "Adding Caddy reverse proxy blocks..."
    cat >> /etc/caddy/Caddyfile << 'CADDY'

# Odigos tester instances
jessica.uxrls.com {
    reverse_proxy 127.0.0.1:8010
}

florence.uxrls.com {
    reverse_proxy 127.0.0.1:8011
}

jason.uxrls.com {
    reverse_proxy 127.0.0.1:8012
}
CADDY
    systemctl reload caddy
    info "Caddy updated and reloaded"
else
    info "Caddy blocks already exist, skipping"
fi

# ── Step 8: Start containers ─────────────────────────────────────────
info "Starting containers..."
docker compose up -d
info "All containers starting"

# ── Step 9: Print summary ────────────────────────────────────────────
echo ""
bold "=== Deployment Complete ==="
echo ""
echo "Containers are starting (allow ~2 min for health checks)."
echo "Monitor with: cd $BASE_DIR && docker compose logs -f"
echo ""
bold "Tester credentials:"
echo ""
for i in "${!TESTERS[@]}"; do
    name="${TESTERS[$i]}"
    display_name="$(echo "${name:0:1}" | tr '[:lower:]' '[:upper:]')${name:1}"
    echo "  ${display_name}:"
    echo "    URL: https://${name}.uxrls.com"
    echo "    API Key: ${API_KEYS[$name]}"
    echo ""
done
