#!/usr/bin/env bash
set -euo pipefail

# Deploy latest code to all Odigos installs.
# Usage:
#   bash deploy.sh                        # normal deploy
#   bash deploy.sh --skip-build           # skip dashboard rebuild
#   OPENROUTER_API_KEY=sk-... bash deploy.sh --fresh
#       Wipes config.yaml + .env on every install and writes a fresh one.
#       Required once after switching to the providers/models config shape.

SKIP_BUILD=false
FRESH=false
for arg in "$@"; do
    case "$arg" in
        --skip-build) SKIP_BUILD=true ;;
        --fresh) FRESH=true ;;
    esac
done

if [ "$FRESH" = "true" ] && [ -z "${OPENROUTER_API_KEY:-}" ]; then
    echo "ERROR: --fresh requires OPENROUTER_API_KEY to be exported." >&2
    echo "  Example: OPENROUTER_API_KEY=sk-or-v1-... bash deploy.sh --fresh" >&2
    exit 1
fi

ODIGOS_ONE="root@82.25.91.86"
UXRLS="root@100.89.147.103"

# Bare metal installs on odigos.one (systemd services)
# Format: "directory:service_name:service_user"
BARE_METAL=(
  "/opt/odigos:odigos:odigos_agent"
  "/opt/odigos-rachel:odigos-rachel:odigos_agent"
  "/opt/odigos-sales:odigos-sales:odigos_sales"
  "/opt/odigos-honey:odigos-honey:odigos_agent"
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
  IFS=':' read -r dir service user <<< "$entry"
  log "  $service ($dir) [user: $user]"

  ssh "$ODIGOS_ONE" bash -s "$dir" "$service" "$SKIP_BUILD" "$user" "$FRESH" \
      "${OPENROUTER_API_KEY:-}" "${GROQ_API_KEY:-}" "${KIE_AI_API_KEY:-}" <<'REMOTE'
    set -euo pipefail
    DIR="$1"; SVC="$2"; SKIP="$3"; SVC_USER="$4"; FRESH="$5"
    OR_KEY="$6"; GROQ_KEY="$7"; KIE_KEY="$8"
    cd "$DIR"

    # Pull latest (always — fresh-install runs after so it gets the new script)
    git fetch origin main
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/main)
    if [ "$LOCAL" = "$REMOTE" ] && [ "$FRESH" != "true" ]; then
      echo "  Already up to date."
      exit 0
    fi
    git reset --hard origin/main

    # Fix ownership IMMEDIATELY — git reset as root makes everything root-owned.
    # Must happen before uv sync, npm build, or anything else touches the files.
    chown -R "$SVC_USER:$SVC_USER" . 2>/dev/null || true

    # Fresh-install mode: wipe config.yaml + .env and regenerate from scratch.
    # Service user owns the result so it can read its own config.
    if [ "$FRESH" = "true" ]; then
      OPENROUTER_API_KEY="$OR_KEY" GROQ_API_KEY="$GROQ_KEY" KIE_AI_API_KEY="$KIE_KEY" \
        sudo -u "$SVC_USER" -E bash scripts/fresh-install.sh .
    fi

    # Sync dependencies (new packages from pyproject.toml)
    sudo -u "$SVC_USER" uv sync --quiet 2>&1 | tail -3 || echo "  uv sync skipped"


    # Ensure TextBlob NLTK data is present
    sudo -u "$SVC_USER" bash -c "cd $DIR && source .venv/bin/activate && python -m textblob.download_corpora lite" &>/dev/null || true

    # Rebuild dashboard if ANY frontend file changed (auto-detect)
    if [ -d dashboard ]; then
      # awk instead of grep -c: always exits 0, always prints a single integer,
      # so no "0\n0" artifact from a falling-through `|| echo 0` clause.
      FRONTEND_CHANGED=$(git diff "$LOCAL"..HEAD --name-only 2>/dev/null | awk '/^dashboard\// {c++} END {print c+0}')
      if [ "$SKIP" = "true" ] && [ "$FRONTEND_CHANGED" -gt 0 ]; then
        echo "  WARNING: --skip-build but $FRONTEND_CHANGED frontend files changed. Building anyway."
      fi
      if [ "$FRONTEND_CHANGED" -gt 0 ] || [ "$SKIP" != "true" ]; then
        cd dashboard
        if git diff "$LOCAL"..HEAD --name-only 2>/dev/null | grep -q 'package-lock.json'; then
          npm ci --no-audit --no-fund 2>&1 | tail -3
        fi
        npm run build 2>&1 | tail -3
        cd ..
      else
        echo "  No frontend changes, skipping build."
      fi
    fi

    # Fix ownership again after build
    chown -R "$SVC_USER:$SVC_USER" . 2>/dev/null || true

    # Restart service
    systemctl restart "$SVC"

    # Wait and verify startup
    sleep 3
    if systemctl is-active --quiet "$SVC"; then
      echo "  $SVC is running"
    else
      echo "  WARNING: $SVC failed to start!"
      journalctl -u "$SVC" -n 5 --no-pager 2>&1 | tail -5
      exit 1
    fi
REMOTE

  if [ $? -eq 0 ]; then
    log "  $service done"
  else
    fail "  $service FAILED"
  fi
done

# ── uxrls.com: docker ───────────────────────────────────────────────

log "Deploying to uxrls.com (Docker)..."

ssh "$UXRLS" bash -s "$DOCKER_DIR" "$SKIP_BUILD" "$FRESH" \
    "${OPENROUTER_API_KEY:-}" "${GROQ_API_KEY:-}" "${KIE_AI_API_KEY:-}" <<'REMOTE'
  set -euo pipefail
  DIR="$1"; SKIP="$2"; FRESH="$3"
  OR_KEY="$4"; GROQ_KEY="$5"; KIE_KEY="$6"
  cd "$DIR"

  # Pull latest
  git fetch origin main
  LOCAL=$(git rev-parse HEAD)
  REMOTE=$(git rev-parse origin/main)
  if [ "$LOCAL" = "$REMOTE" ] && [ "$FRESH" != "true" ]; then
    echo "  Already up to date."
    exit 0
  fi
  git reset --hard origin/main

  # Fresh-install mode: wipe + regenerate. The main /opt/odigos container
  # uses this directory's own config.yaml + .env; the testers each live in
  # their own subdirectory with bind-mounted configs.
  if [ "$FRESH" = "true" ]; then
    OPENROUTER_API_KEY="$OR_KEY" GROQ_API_KEY="$GROQ_KEY" KIE_AI_API_KEY="$KIE_KEY" \
      bash "$DIR/scripts/fresh-install.sh" "$DIR"
    for user in florence jessica; do
      TDIR="/opt/odigos/testers/$user"
      [ -d "$TDIR" ] || continue
      OPENROUTER_API_KEY="$OR_KEY" GROQ_API_KEY="$GROQ_KEY" KIE_AI_API_KEY="$KIE_KEY" \
        bash "$DIR/scripts/fresh-install.sh" "$TDIR"
    done
  fi

  # Clean old images and build cache BEFORE building to prevent disk-full failures.
  # Keeps images used by running containers; prunes everything else.
  echo "  Cleaning stale Docker images and build cache..."
  docker image prune -af --filter "until=24h" 2>/dev/null | tail -1
  docker builder prune -af --keep-storage 5GB 2>/dev/null | tail -1

  # Rebuild and restart the odigos service only (system Caddy handles TLS)
  # Touch a file to bust Docker layer cache for code changes
  date +%s > .docker-build-stamp
  docker compose build --build-arg CACHE_BUST="$(cat .docker-build-stamp)" odigos 2>&1 | tail -5
  docker compose up -d --no-deps odigos 2>&1 | tail -5

  # Brief pause for image to be ready, don't block on health check
  sleep 5

  # Recreate user containers with new image
  for user in florence jessica; do
    CONTAINER="odigos-$user"
    if docker inspect "$CONTAINER" &>/dev/null; then
      PORT=$(docker inspect "$CONTAINER" --format '{{(index (index .NetworkSettings.Ports "8000/tcp") 0).HostPort}}' 2>/dev/null || echo "")
      if [ -z "$PORT" ]; then
        echo "  WARNING: Could not get port for $CONTAINER, skipping"
        continue
      fi
      docker stop "$CONTAINER" 2>/dev/null || true
      docker rm "$CONTAINER" 2>/dev/null || true
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
FAILURES=0
while IFS= read -r line; do
  if echo "$line" | grep -q "active"; then
    echo -e "  ${GREEN}$line${NC}"
  else
    echo -e "  ${RED}$line${NC}"
    FAILURES=$((FAILURES + 1))
  fi
done < <(ssh "$ODIGOS_ONE" 'for s in odigos odigos-rachel odigos-sales odigos-honey; do
  printf "%-20s %s\n" "$s" "$(systemctl is-active $s)"
done')

echo ""
log "uxrls.com:"
ssh "$UXRLS" 'docker ps --format "  {{.Names}}\t{{.Status}}" | grep odigos'

echo ""
if [ $FAILURES -gt 0 ]; then
  fail "$FAILURES service(s) failed. Check logs above."
  exit 1
fi
log "Deploy complete. All services running."
