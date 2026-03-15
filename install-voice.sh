#!/usr/bin/env bash
set -euo pipefail

# Odigos voice setup — installs STT/TTS dependencies and downloads models.
# Works in Docker, bare-metal with uv, or bare-metal with .venv.

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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
bold "=== Odigos Voice Setup ==="
echo ""

# ── Detect environment ─────────────────────────────────────────────
PIP_CMD=""
PYTHON_CMD=""

if command -v uv &> /dev/null; then
    PIP_CMD="uv pip install"
    PYTHON_CMD="uv run python"
    info "Detected uv environment"
elif [ -f .venv/bin/pip ]; then
    PIP_CMD=".venv/bin/pip install"
    PYTHON_CMD=".venv/bin/python"
    info "Detected .venv environment"
elif [ -f /.dockerenv ] || grep -q docker /proc/1/cgroup 2>/dev/null; then
    PIP_CMD="pip install"
    PYTHON_CMD="python"
    info "Detected Docker environment"
else
    # Fallback: try pip directly
    if command -v pip &> /dev/null; then
        PIP_CMD="pip install"
        PYTHON_CMD="python3"
        warn "No uv or .venv found — using system pip"
    else
        err "No package installer found. Install uv or create a .venv first."
        echo "  uv:   curl -LsSf https://astral.sh/uv/install.sh | sh"
        echo "  venv: python3 -m venv .venv && source .venv/bin/activate"
        exit 1
    fi
fi

# ── Install voice packages ────────────────────────────────────────
info "Installing voice packages (moonshine-voice, pocket-tts, scipy)..."
$PIP_CMD moonshine-voice pocket-tts scipy
info "Voice packages installed"

# ── Download Moonshine English model ──────────────────────────────
info "Downloading Moonshine English STT model (one-time)..."
$PYTHON_CMD -m moonshine_voice.download --language en
info "Moonshine English model ready"

# ── Update config.yaml ────────────────────────────────────────────
CONFIG_FILE="config.yaml"

if [ ! -f "$CONFIG_FILE" ]; then
    warn "config.yaml not found — creating minimal voice config"
    cat > "$CONFIG_FILE" << 'EOF'
# Odigos Configuration — created by install-voice.sh

stt:
  enabled: true

tts:
  enabled: true
EOF
    info "Created $CONFIG_FILE with voice settings"
else
    info "Updating $CONFIG_FILE with voice settings..."
    $PYTHON_CMD - "$CONFIG_FILE" << 'PYEOF'
import sys
import yaml

config_path = sys.argv[1]

with open(config_path, "r") as f:
    config = yaml.safe_load(f) or {}

if "stt" not in config:
    config["stt"] = {}
config["stt"]["enabled"] = True

if "tts" not in config:
    config["tts"] = {}
config["tts"]["enabled"] = True

with open(config_path, "w") as f:
    yaml.dump(config, f, default_flow_style=False, sort_keys=True)

print("  stt.enabled: true")
print("  tts.enabled: true")
PYEOF
    info "config.yaml updated"
fi

# ── Done ──────────────────────────────────────────────────────────
echo ""
bold "Voice setup complete!"
echo ""
echo "  Available voice features:"
echo "    STT (Speech-to-Text):  Moonshine — fast, local, English"
echo "    TTS (Text-to-Speech):  Pocket TTS — lightweight, offline"
echo ""
echo "  Voice is now enabled in config.yaml."
echo "  Restart Odigos to activate voice capabilities."
echo ""
