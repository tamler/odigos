#!/usr/bin/env bash
# Fresh install — wipe any existing config.yaml + .env and write new ones from
# scratch. Not a migration. Not idempotent. Destructive by design.
#
# Usage:
#   OPENROUTER_API_KEY=sk-or-v1-... bash scripts/fresh-install.sh [install_dir] [agent_name]
#
# Environment:
#   OPENROUTER_API_KEY  (required) key written into .env
#   AGENT_NAME          (optional) overrides the derived agent name
#   DASHBOARD_KEY       (optional) pre-set dashboard auth key; otherwise random
#
# Agent name derivation when AGENT_NAME is unset:
#   /opt/odigos           → Odigos
#   /opt/odigos-rachel    → Rachel
#   /opt/odigos/testers/florence → Florence

set -euo pipefail

DIR="${1:-.}"
CLI_NAME="${2:-}"
cd "$DIR"

if [ -z "${OPENROUTER_API_KEY:-}" ]; then
    echo "ERROR: OPENROUTER_API_KEY must be set in the environment." >&2
    exit 1
fi

# Agent name: CLI arg > env var > derived from directory
if [ -n "$CLI_NAME" ]; then
    NAME="$CLI_NAME"
elif [ -n "${AGENT_NAME:-}" ]; then
    NAME="$AGENT_NAME"
else
    base=$(basename "$(pwd)")
    base=${base#odigos-}
    base=${base#odigos}
    if [ -z "$base" ]; then
        NAME="Odigos"
    else
        # Title-case first letter, portable across BSD/GNU
        NAME="$(printf '%s' "$base" | awk '{print toupper(substr($0,1,1)) substr($0,2)}')"
    fi
fi

DASH_KEY="${DASHBOARD_KEY:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')}"
SESSION_SECRET_VAL=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')

# Nuke anything stale
rm -f config.yaml .env config.yaml.*.bak .env.*.bak

# Write .env
cat > .env <<ENV
OPENROUTER_API_KEY=$OPENROUTER_API_KEY

SESSION_SECRET=$SESSION_SECRET_VAL
ENV

# Write config.yaml
cat > config.yaml <<CFG
# Odigos — fresh install $(date -u +%Y-%m-%dT%H:%M:%SZ)

api_key: "$DASH_KEY"

agent:
  name: "$NAME"

providers:
  openrouter:
    base_url: "https://openrouter.ai/api/v1"
    api_key: "\${OPENROUTER_API_KEY}"

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
  max_tokens: 4096
  temperature: 0.7
  auto_route: true

budget:
  daily_limit_usd: 1.00
  monthly_limit_usd: 20.00
  warn_threshold: 0.80

heartbeat:
  interval_seconds: 30
  max_todos_per_tick: 3
  morning_briefing: true

voice:
  stt_provider: "disabled"
  tts_provider: "disabled"

server:
  host: "0.0.0.0"
  port: 8000
CFG

echo "  Fresh install written to $DIR (agent: $NAME, dashboard key: $DASH_KEY)"
