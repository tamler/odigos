#!/usr/bin/env bash
set -euo pipefail

# Deploy latest code to all Odigos installs.
# Usage:
#   bash deploy.sh                        # normal deploy
#   bash deploy.sh --skip-build           # skip dashboard rebuild
#   OPENROUTER_API_KEY=sk-... bash deploy.sh --fresh
#       Wipes config.yaml + .env on every install and writes a fresh one.
#       Required once after switching to the providers/models config shape.
#
# Target host is the ssh alias `odigos` (OVH VPS 51.81.82.221, reachable on
# Tailscale at 100.80.26.2, public SSH firewalled). Override with ODIGOS_HOST.
# We connect as an unprivileged user and escalate with sudo on the remote side.

SKIP_BUILD=false
FRESH=false
for arg in "$@"; do
    case "$arg" in
        --skip-build) SKIP_BUILD=true ;;
        --fresh) FRESH=true ;;
    esac
done

if [ "$FRESH" = "true" ] && [ -z "${OPENROUTER_API_KEY:-}" ] && [ -z "${GROQ_API_KEY:-}" ]; then
    echo "ERROR: --fresh requires at least one provider key (OPENROUTER_API_KEY or GROQ_API_KEY)." >&2
    echo "  Example: OPENROUTER_API_KEY=sk-or-v1-... bash deploy.sh --fresh" >&2
    echo "           GROQ_API_KEY=gsk_... bash deploy.sh --fresh" >&2
    exit 1
fi

ODIGOS_HOST="${ODIGOS_HOST:-odigos}"

# Hosted installs on the OVH VPS (systemd services).
# Format: "directory:service_name:service_user:branch"
#
# Every install MUST have its own service user. A shared user means each install
# can read every sibling's .env, DB and data dir, which makes the "separate
# filesystem root per account" isolation fiction. See
# docs/deployment/2026-05-29-os-isolation-checklist.md. The preflight below
# enforces this.
#
# Retired 2026-05-27: Rachel, HomeRun, old Bob, Jessica-on-uxrls.
# Retired 2026-05-28: Sales (replaced by a static FAQ).
# Bob and Jessica are not currently installed on this box; re-add rows here
# when they are rebuilt, each with its own odigos_<name> user.
INSTALLS=(
  "/opt/odigos-honey:odigos-honey:odigos_honey:security/hardening-hosted-launch"
)

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[deploy]${NC} $1"; }
warn() { echo -e "${YELLOW}[deploy]${NC} $1"; }
fail() { echo -e "${RED}[deploy]${NC} $1"; }

# ── Preflight: no two installs may share a service user ─────────────

dupes=$(printf '%s\n' "${INSTALLS[@]}" | cut -d: -f3 | sort | uniq -d)
if [ -n "$dupes" ]; then
  fail "Service user(s) shared across installs: $(echo "$dupes" | tr '\n' ' ')"
  fail "Each install needs its own Unix user, or they can read each other's secrets."
  exit 1
fi

# ── Deploy ──────────────────────────────────────────────────────────

log "Deploying to $ODIGOS_HOST..."

FAILURES=0

for entry in "${INSTALLS[@]}"; do
  IFS=':' read -r dir service user branch <<< "$entry"
  log "  $service ($dir) [user: $user, branch: $branch]"

  if ssh "$ODIGOS_HOST" sudo -n bash -s "$dir" "$service" "$SKIP_BUILD" "$user" "$FRESH" "$branch" \
      "${OPENROUTER_API_KEY:-}" "${GROQ_API_KEY:-}" "${KIE_AI_API_KEY:-}" <<'REMOTE'
    set -euo pipefail
    DIR="$1"; SVC="$2"; SKIP="$3"; SVC_USER="$4"; FRESH="$5"; BRANCH="$6"
    OR_KEY="$7"; GROQ_KEY="$8"; KIE_KEY="$9"
    cd "$DIR"

    # Pull latest (always — fresh-install runs after so it gets the new script)
    git fetch origin "$BRANCH"
    LOCAL=$(git rev-parse HEAD)
    TARGET=$(git rev-parse "origin/$BRANCH")
    if [ "$LOCAL" = "$TARGET" ] && [ "$FRESH" != "true" ]; then
      echo "  Already up to date."
      exit 0
    fi
    git reset --hard "origin/$BRANCH"

    # Fix ownership IMMEDIATELY — git reset as root makes everything root-owned.
    # Must happen before uv sync, npm build, or anything else touches the files.
    chown -R "$SVC_USER:$SVC_USER" . 2>/dev/null || true

    # Fresh-install mode: wipe config.yaml + .env and regenerate from scratch.
    # Service user owns the result so it can read its own config.
    if [ "$FRESH" = "true" ]; then
      OPENROUTER_API_KEY="$OR_KEY" GROQ_API_KEY="$GROQ_KEY" KIE_AI_API_KEY="$KIE_KEY" \
        sudo -u "$SVC_USER" -E env HOME="$DIR" bash scripts/fresh-install.sh .
    fi

    # Sync dependencies. --frozen so a stale lockfile fails the deploy instead of
    # silently resolving something different from what CI tested.
    sudo -u "$SVC_USER" env HOME="$DIR" uv sync --frozen --quiet 2>&1 | tail -3 || echo "  uv sync skipped"

    # Ensure TextBlob NLTK data is present
    sudo -u "$SVC_USER" env HOME="$DIR" bash -c "cd $DIR && source .venv/bin/activate && python -m textblob.download_corpora lite" &>/dev/null || true

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
          sudo -u "$SVC_USER" env HOME="$DIR" npm ci --no-audit --no-fund 2>&1 | tail -3
        fi
        sudo -u "$SVC_USER" env HOME="$DIR" npm run build 2>&1 | tail -3
        cd ..
      else
        echo "  No frontend changes, skipping build."
      fi
    fi

    # Fix ownership again after build, then re-assert the isolation perms that
    # a recursive chown/reset flattens. Secrets stay owner-only.
    chown -R "$SVC_USER:$SVC_USER" . 2>/dev/null || true
    chmod 700 "$DIR" 2>/dev/null || true
    [ -d "$DIR/data" ] && chmod 700 "$DIR/data"
    [ -f "$DIR/.env" ] && chmod 600 "$DIR/.env"
    [ -f "$DIR/config.yaml" ] && chmod 600 "$DIR/config.yaml"

    # Restart service
    systemctl restart "$SVC"

    # Wait and verify startup
    sleep 3
    if systemctl is-active --quiet "$SVC"; then
      echo "  $SVC is running"
    else
      echo "  WARNING: $SVC failed to start!"
      journalctl -u "$SVC" -n 15 --no-pager 2>&1 | tail -15
      exit 1
    fi
REMOTE
  then
    log "  $service done"
  else
    fail "  $service FAILED"
    FAILURES=$((FAILURES + 1))
  fi
done

# ── Verify ───────────────────────────────────────────────────────────

log "Verifying services..."
echo ""

for entry in "${INSTALLS[@]}"; do
  IFS=':' read -r dir service user branch <<< "$entry"
  state=$(ssh "$ODIGOS_HOST" "systemctl is-active $service" 2>/dev/null || true)
  if [ "$state" = "active" ]; then
    echo -e "  ${GREEN}$(printf '%-20s %s' "$service" "$state")${NC}"
  else
    echo -e "  ${RED}$(printf '%-20s %s' "$service" "$state")${NC}"
    FAILURES=$((FAILURES + 1))
  fi
done

# ── Fleet conformance: hosted installs must really be isolated ───────
#
# `systemctl is-active` says nothing about whether the sandbox came up. A
# hosted install that resolved to the ulimit tier has no filesystem isolation
# between agent-run code and the host, so treat it as a failed deploy.

echo ""
log "Fleet conformance (hosted mode + sandbox tier)..."

for entry in "${INSTALLS[@]}"; do
  IFS=':' read -r dir service user branch <<< "$entry"
  posture=$(ssh "$ODIGOS_HOST" "sudo -n journalctl -u $service --no-pager -n 500 2>/dev/null | grep -o 'security posture: .*' | tail -1" || true)
  if [ -z "$posture" ]; then
    fail "  $service: no security posture line found in recent logs"
    FAILURES=$((FAILURES + 1))
    continue
  fi
  if echo "$posture" | grep -q "mode=hosted" && echo "$posture" | grep -q "isolation=bwrap"; then
    echo -e "  ${GREEN}$(printf '%-20s %s' "$service" "$posture")${NC}"
  else
    fail "  $service: $posture"
    fail "    expected mode=hosted and isolation=bwrap"
    FAILURES=$((FAILURES + 1))
  fi
done

echo ""
if [ "$FAILURES" -gt 0 ]; then
  fail "$FAILURES check(s) failed. Check logs above."
  exit 1
fi
log "Deploy complete. All services running."
