#!/usr/bin/env bash
set -euo pipefail

# Deploy latest code to all Odigos installs.
# Usage: bash deploy.sh [--skip-build]

SKIP_BUILD=false
[[ "${1:-}" == "--skip-build" ]] && SKIP_BUILD=true

ODIGOS_ONE="root@82.25.91.86"
UXRLS="root@100.89.147.103"

# Bare metal installs on odigos.one (systemd services)
BARE_METAL=(
  "/opt/odigos:odigos"
  "/opt/odigos-honey:odigos-honey"
  "/opt/odigos-rachel:odigos-rachel"
  "/opt/odigos-sales:odigos-sales"
)

# Docker installs on uxrls.com
DOCKER_DIR="/opt/odigos"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[deploy]${NC} $1"; }
warn() { echo -e "${YELLOW}[deploy]${NC} $1"; }
fail() { echo -e "${RED}[deploy]${NC} $1"; }

# ── odigos.one: bare metal ──────────────────────────────────────────

log "Deploying to odigos.one (bare metal)..."

for entry in "${BARE_METAL[@]}"; do
  dir="${entry%%:*}"
  service="${entry##*:}"
  log "  $service ($dir)"

  ssh "$ODIGOS_ONE" bash -s "$dir" "$service" "$SKIP_BUILD" <<'REMOTE'
    set -euo pipefail
    DIR="$1"; SVC="$2"; SKIP="$3"
    cd "$DIR"

    # Pull latest
    git fetch origin main
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/main)
    if [ "$LOCAL" = "$REMOTE" ]; then
      echo "  Already up to date."
      exit 0
    fi
    git reset --hard origin/main

    # Rebuild dashboard
    if [ "$SKIP" != "true" ] && [ -d dashboard ]; then
      cd dashboard
      npm run build 2>&1 | tail -3
      cd ..
    fi

    # Restart service
    systemctl restart "$SVC"
    echo "  Restarted $SVC"
REMOTE

  if [ $? -eq 0 ]; then
    log "  $service done"
  else
    fail "  $service FAILED"
  fi
done

# ── uxrls.com: docker ───────────────────────────────────────────────

log "Deploying to uxrls.com (Docker)..."

ssh "$UXRLS" bash -s "$DOCKER_DIR" "$SKIP_BUILD" <<'REMOTE'
  set -euo pipefail
  DIR="$1"; SKIP="$2"
  cd "$DIR"

  # Pull latest
  git fetch origin main
  LOCAL=$(git rev-parse HEAD)
  REMOTE=$(git rev-parse origin/main)
  if [ "$LOCAL" = "$REMOTE" ]; then
    echo "  Already up to date."
    exit 0
  fi
  git reset --hard origin/main

  # Rebuild and restart the odigos service only (system Caddy handles TLS)
  docker compose up -d --build --no-deps odigos 2>&1 | tail -5

  # Recreate user containers with new image
  IMAGE=$(docker compose images -q odigos 2>/dev/null || docker images ghcr.io/tamler/odigos:latest -q)
  for user in florence jessica jason klint; do
    CONTAINER="odigos-$user"
    if docker inspect "$CONTAINER" &>/dev/null; then
      PORT=$(docker inspect "$CONTAINER" --format '{{(index (index .NetworkSettings.Ports "8000/tcp") 0).HostPort}}')
      docker stop "$CONTAINER" && docker rm "$CONTAINER"
      docker run -d \
        --name "$CONTAINER" \
        --restart unless-stopped \
        --privileged \
        --add-host host.docker.internal:host-gateway \
        -p "127.0.0.1:$PORT:8000" \
        -v "/opt/odigos/testers/$user/data:/app/data" \
        -v "/opt/odigos/testers/$user/config.yaml:/app/config.yaml" \
        -v "/opt/odigos/testers/$user/.env:/app/.env" \
        -v "/opt/odigos/testers/$user/skills:/app/skills" \
        -v "/opt/odigos/testers/$user/plugins:/app/plugins" \
        --health-cmd "curl -f http://localhost:8000/health" \
        --health-interval 30s \
        --health-timeout 5s \
        --health-retries 3 \
        --health-start-period 120s \
        ghcr.io/tamler/odigos:latest
      echo "  Recreated $CONTAINER on port $PORT"
    fi
  done
REMOTE

if [ $? -eq 0 ]; then
  log "uxrls.com done"
else
  fail "uxrls.com FAILED"
fi

# ── Verify ───────────────────────────────────────────────────────────

log "Verifying services..."

echo ""
log "odigos.one:"
ssh "$ODIGOS_ONE" 'for s in odigos odigos-honey odigos-rachel odigos-sales; do
  printf "  %-20s %s\n" "$s" "$(systemctl is-active $s)"
done'

echo ""
log "uxrls.com:"
ssh "$UXRLS" 'docker ps --format "  {{.Names}}\t{{.Status}}" | grep odigos'

echo ""
log "Deploy complete."
