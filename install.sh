#!/usr/bin/env bash
set -euo pipefail

echo "=== Odigos Quick Setup ==="
echo ""

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is required. Install it from https://docs.docker.com/get-docker/"
    exit 1
fi

# Create config from example if missing
if [ ! -f config.yaml ]; then
    cp config.yaml.example config.yaml
    echo "Created config.yaml from example."
else
    echo "config.yaml already exists."
fi

# Create .env from example if missing
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from example."
    echo ""
    echo "  IMPORTANT: Edit .env and set your LLM_API_KEY before starting."
else
    echo ".env already exists."
fi

# Create data directories
mkdir -p data data/plugins

echo ""
echo "Setup complete. Next steps:"
echo ""
echo "  1. Edit .env — set your LLM_API_KEY (required)"
echo "     Optional: set TELEGRAM_BOT_TOKEN to enable Telegram"
echo "  2. Edit config.yaml — customize agent name, budget limits, etc."
echo "  3. Build and start:"
echo "       docker compose up -d --build"
echo "  4. View logs:"
echo "       docker compose logs -f odigos"
echo "  5. Open dashboard:"
echo "       http://localhost:8000"
echo ""
