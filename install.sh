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
    echo "Edit config.yaml with your API keys before starting."
else
    echo "config.yaml already exists."
fi

# Create data directories
mkdir -p data data/plugins

echo ""
echo "Setup complete. Next steps:"
echo ""
echo "  1. Edit config.yaml — set your TELEGRAM_BOT_TOKEN and OPENROUTER_API_KEY"
echo "  2. Export env vars:"
echo "       export TELEGRAM_BOT_TOKEN=your-token"
echo "       export OPENROUTER_API_KEY=your-key"
echo "  3. Start Odigos:"
echo "       docker compose up -d"
echo "  4. View logs:"
echo "       docker compose logs -f odigos"
echo "  5. Open dashboard:"
echo "       http://localhost:8000"
echo ""
