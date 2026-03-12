# Odigos

Self-hosted personal AI agent with a web dashboard, plugin system, and autonomous capabilities.

## Prerequisites

- **Docker** (recommended) -- [docs.docker.com/get-docker](https://docs.docker.com/get-docker/)
- **LLM API Key** -- any OpenAI-compatible provider ([OpenRouter](https://openrouter.ai/keys), OpenAI, Ollama, LM Studio, etc.)

## Quick Start (Docker)

```bash
git clone <repo-url> && cd odigos
./install.sh
```

The install script configures your LLM provider, builds the Docker image, and starts Odigos. Open **http://localhost:8000** when ready.

**Useful commands:**
```bash
docker compose logs -f odigos    # View logs
docker compose restart odigos    # Restart
docker compose down              # Stop
```

## Run Without Docker

```bash
git clone <repo-url> && cd odigos
pip install -e .
cp config.yaml.example config.yaml
```

Create a `.env` file with your API key:
```bash
echo "LLM_API_KEY=your-key-here" > .env
```

Start the agent:
```bash
odigos
```

### Run as a systemd Service

Create `/etc/systemd/system/odigos.service`:

```ini
[Unit]
Description=Odigos AI Agent
After=network.target

[Service]
Type=simple
User=odigos
WorkingDirectory=/opt/odigos
ExecStart=/opt/odigos/.venv/bin/python -m uvicorn odigos.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
EnvironmentFile=/opt/odigos/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now odigos
```

## Configuration

- `.env` -- API keys and secrets (never committed)
- `config.yaml` -- agent settings, model selection, tool configuration

See `config.yaml.example` for all available options.

## Plugins

Odigos uses a plugin system for optional capabilities. Plugins live in the `plugins/` directory and can be configured through the dashboard at **Plugins** or directly in `config.yaml`.

**Available plugins:**

| Plugin | Category | What it adds |
|--------|----------|-------------|
| SearXNG | Search | Web search via a SearXNG instance |
| Google Workspace | Tools | Gmail, Calendar, Drive access via gws CLI |
| Agent Browser | Tools | Browser automation for web interaction |
| Telegram | Channel | Telegram bot interface for your agent |
| Docling | Provider | Deep document extraction (tables, figures, layout) |

Enable a plugin by providing its required configuration (API keys, URLs, etc.) in the dashboard or config.yaml. Restart to apply changes.

## Architecture

- **FastAPI** backend with WebSocket support
- **React** dashboard (built, served from `/dashboard/dist`)
- **SQLite** for all storage (conversations, memory, goals, budget)
- **sqlite-vec + FTS5** for hybrid vector/text search
- **Plugin system** for optional tools, channels, and providers
- **Local embeddings** (nomic-embed-text-v1.5, runs on CPU)
