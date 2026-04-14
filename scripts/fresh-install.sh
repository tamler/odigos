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

# Optional service keys — written to .env if provided, referenced from
# config.yaml's services block via ${VAR} interpolation. Safe to leave empty;
# the services dict will resolve to "" and the validator will flag them as
# optional features that aren't configured yet.
GROQ_KEY="${GROQ_API_KEY:-}"
KIE_KEY="${KIE_AI_API_KEY:-}"

# Nuke anything stale
rm -f config.yaml .env config.yaml.*.bak .env.*.bak

# Write .env
cat > .env <<ENV
OPENROUTER_API_KEY=$OPENROUTER_API_KEY
GROQ_API_KEY=$GROQ_KEY
KIE_AI_API_KEY=$KIE_KEY

SESSION_SECRET=$SESSION_SECRET_VAL
ENV

# Write config.yaml
cat > config.yaml <<CFG
# Odigos — fresh install $(date -u +%Y-%m-%dT%H:%M:%SZ)

api_key: "$DASH_KEY"

agent:
  name: "$NAME"

# External service keys — resolved from .env at load time.
# Empty values just disable the feature until you fill them in.
services:
  groq: "\${GROQ_API_KEY}"
  kie_ai: "\${KIE_AI_API_KEY}"

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
  max_tokens: 2048
  temperature: 0.7
  auto_route: true

# Starter defaults — tuned for hosted multi-tenant use.
# Adjust daily/monthly limits per your pricing tier.
budget:
  daily_limit_usd: 0.50
  monthly_limit_usd: 10.00
  warn_threshold: 0.80

agent:
  max_tool_turns: 15
  run_timeout_seconds: 180

heartbeat:
  interval_seconds: 60
  max_todos_per_tick: 2
  idle_think_interval: 0
  morning_briefing: false

# Proactive autonomous research is OFF by default — enable in the dashboard
# for Pro-tier users who want the agent to research topics when idle.
proactive:
  enabled: false

voice:
  stt_provider: "$([ -n "$GROQ_KEY" ] && echo groq || echo disabled)"
  tts_provider: "$([ -n "$GROQ_KEY" ] && echo edge || echo disabled)"
  tts_voice: "en-US-AriaNeural"
  groq_model: "whisper-large-v3-turbo"

# Image generation — kie.ai Z-Image. Auto-enabled when KIE_AI_API_KEY is set.
image_generation:
  default_aspect_ratio: "1:1"
  nsfw_filter: true
  max_poll_seconds: 120

# Music generation — kie.ai Suno. Auto-enabled when KIE_AI_API_KEY is set.
music_generation:
  model: "V5_5"
  max_poll_seconds: 180

server:
  host: "0.0.0.0"
  port: 8000
CFG

echo "  Fresh install written to $DIR (agent: $NAME, dashboard key: $DASH_KEY)"
