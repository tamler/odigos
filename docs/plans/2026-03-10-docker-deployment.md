# Docker Deployment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Package Odigos as a Docker image with docker-compose for one-command deployment, including persistent data volumes and an annotated config template.

**Architecture:** Multi-stage Docker build (build deps → slim runtime). docker-compose.yml orchestrates Odigos + optional SearXNG sidecar. Data persisted via named volumes. Config injected via bind-mounted config.yaml. Auto-generated API key logged on first run.

**Tech Stack:** Docker, docker-compose, Python 3.12-slim, uvicorn

---

### Task 1: .dockerignore

**Files:**
- Create: `.dockerignore`

Keeps the image small by excluding dev artifacts.

```
.venv
.git
.github
__pycache__
*.pyc
*.pyo
.pytest_cache
.ruff_cache
tests
docs
data/*.db
data/chroma
*.egg-info
.worktrees
worktrees
.claude
node_modules
```

**Commit:**
```bash
git add .dockerignore
git commit -m "chore: add .dockerignore"
```

---

### Task 2: Dockerfile

**Files:**
- Create: `Dockerfile`

Multi-stage build. First stage installs deps, second stage copies only what's needed.

```dockerfile
FROM python:3.12-slim AS builder

WORKDIR /build

# System deps for building native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

# --- Runtime stage ---
FROM python:3.12-slim

WORKDIR /app

# Runtime system deps (playwright browsers skipped — headless not needed in container)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY odigos/ odigos/
COPY dashboard/ dashboard/
COPY migrations/ migrations/
COPY plugins/ plugins/
COPY skills/ skills/
COPY pyproject.toml .

# Default data and config directories
RUN mkdir -p /app/data /app/data/plugins /app/data/chroma

# Config file mount point
VOLUME ["/app/data"]

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["python", "-m", "uvicorn", "odigos.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 1: Build test**
```bash
docker build -t odigos:latest .
```

**Step 2: Verify health**
```bash
docker run --rm -d --name odigos-test \
  -p 8000:8000 \
  -e TELEGRAM_BOT_TOKEN=test \
  -e OPENROUTER_API_KEY=test \
  odigos:latest
sleep 5
curl -f http://localhost:8000/health
docker stop odigos-test
```

**Commit:**
```bash
git add Dockerfile
git commit -m "feat(deploy): add multi-stage Dockerfile"
```

---

### Task 3: docker-compose.yml

**Files:**
- Create: `docker-compose.yml`

```yaml
services:
  odigos:
    build: .
    image: odigos:latest
    container_name: odigos
    restart: unless-stopped
    ports:
      - "${ODIGOS_PORT:-8000}:8000"
    volumes:
      - odigos-data:/app/data
      - ./config.yaml:/app/config.yaml:ro
      - ./skills:/app/skills:ro
      - ./data/plugins:/app/data/plugins:ro
    environment:
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

  # Optional: local search engine
  # Uncomment to enable SearXNG
  # searxng:
  #   image: searxng/searxng:latest
  #   container_name: odigos-searxng
  #   restart: unless-stopped
  #   ports:
  #     - "8888:8080"
  #   volumes:
  #     - searxng-data:/etc/searxng
  #   environment:
  #     - SEARXNG_SECRET=change-me

volumes:
  odigos-data:
  # searxng-data:
```

**Commit:**
```bash
git add docker-compose.yml
git commit -m "feat(deploy): add docker-compose.yml with data volumes"
```

---

### Task 4: Update config.yaml.example

**Files:**
- Modify: `config.yaml.example`

Add all the fields that are now available, with clear comments.

```yaml
# Odigos Configuration
# Copy this to config.yaml and fill in your values.

# API key for authenticating dashboard and API requests.
# If not set, a random key is generated on each startup and logged.
# api_key: "your-secret-api-key-here"

agent:
  name: "Odigos"
  max_tool_turns: 10
  run_timeout_seconds: 120

database:
  path: "data/odigos.db"

# LLM provider (OpenRouter)
openrouter:
  default_model: "anthropic/claude-sonnet-4"
  fallback_model: "google/gemini-2.0-flash-001"
  max_tokens: 4096
  temperature: 0.7

# Budget limits (USD)
budget:
  daily_limit_usd: 5.0
  monthly_limit_usd: 50.0
  warn_threshold: 0.8

# Telegram bot
telegram:
  mode: "polling"
  webhook_url: ""

# Web server
server:
  host: "0.0.0.0"
  port: 8000

# Heartbeat (autonomous loop)
heartbeat:
  interval_seconds: 300
  max_todos_per_tick: 3
  idle_think_interval: 0

# Peer agents (agent-to-agent messaging)
# peers:
#   - name: "researcher"
#     url: "http://researcher:8000"
#     api_key: "peer-secret"

# SearXNG search (optional)
# searxng_url: "http://searxng:8080"
# searxng_username: ""
# searxng_password: ""

# Google Workspace CLI (optional)
gws:
  enabled: false
  timeout: 30

# Agent Browser CLI (optional)
browser:
  enabled: false
  timeout: 120

# Tool approval gate (optional)
approval:
  enabled: false
  timeout: 300
  tools: []

# MCP servers (optional)
# mcp:
#   servers:
#     myserver:
#       command: "npx"
#       args: ["-y", "@my/mcp-server"]

# Skills directory
skills:
  path: "skills"

# Model router free pool (optional, for cost savings)
# router:
#   free_pool: ["google/gemini-2.0-flash-001"]
#   rate_limit_rpm: 10
```

**Commit:**
```bash
git add config.yaml.example
git commit -m "docs: expand config.yaml.example with all available options"
```

---

### Task 5: Makefile updates + install.sh

**Files:**
- Modify: `Makefile`
- Create: `install.sh`

Update Makefile with Docker targets:

```makefile
.PHONY: test audit build up down logs

test:
	.venv/bin/python -m pytest tests/ -x -q

audit:
	.venv/bin/pip-audit

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f odigos
```

Create `install.sh` — a quick-start script for first-time users:

```bash
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
```

**Commit:**
```bash
chmod +x install.sh
git add Makefile install.sh
git commit -m "feat(deploy): add Docker make targets and install.sh quick-start"
```

---

### Task 6: Build and smoke test

**Step 1: Build the image**
```bash
docker compose build
```

**Step 2: Verify image size**
```bash
docker images odigos:latest --format "{{.Size}}"
```

**Step 3: Test health endpoint**
```bash
docker compose up -d
sleep 10
curl -f http://localhost:8000/health
docker compose logs odigos | head -30
docker compose down
```

**Step 4: Final commit (if any fixups needed)**
```bash
git add -u
git commit -m "fix(deploy): docker build adjustments"
```
