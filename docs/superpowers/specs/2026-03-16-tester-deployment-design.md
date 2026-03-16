# Tester Deployment Design

## Goal

Deploy 3 isolated Odigos instances on an existing Ubuntu VPS (85.31.224.187) for UX testers. Each tester gets a subdomain URL and API key. Instances share an LLM API key and SearXNG instance.

## Context

The VPS (8 CPU, 32GB RAM) runs Ubuntu with:
- System-level Caddy at `/etc/caddy/Caddyfile` serving `*.klyption.com` and `*.uxrls.com` subdomains
- Docker with SearXNG on `127.0.0.1:8083` (no app-level auth, Caddy handles auth for external access)
- Existing services on ports 3000, 8001, 8002, 8083
- Tailscale for SSH access (port 22 via `100.89.147.103`)
- Services live under `/opt/`

## Testers

| Tester | Subdomain | Host Port | Container Port | Data dir |
|---|---|---|---|---|
| Jessica | `jessica.uxrls.com` | 8010 | 8000 | `/opt/odigos/testers/jessica/` |
| Florence | `florence.uxrls.com` | 8011 | 8000 | `/opt/odigos/testers/florence/` |
| Jason | `jason.uxrls.com` | 8012 | 8000 | `/opt/odigos/testers/jason/` |

Jason's slot is recyclable after testing:
```bash
docker compose -f /opt/odigos/docker-compose.yml stop odigos-jason
rm -rf /opt/odigos/testers/jason/data
# Edit docker-compose.yml and config.yaml to rename
docker compose -f /opt/odigos/docker-compose.yml up -d odigos-<new-name>
```

## Prerequisites (manual)

Add 3 DNS A records pointing to `85.31.224.187`:
- `jessica.uxrls.com`
- `florence.uxrls.com`
- `jason.uxrls.com`

## Architecture

### Directory layout

```
/opt/odigos/
  repo/                         # Full git clone of odigos (build context)
  docker-compose.yml            # 3 Odigos services
  .env                          # Shared LLM_API_KEY
  testers/
    jessica/
      config.yaml               # Agent name, unique API key, SearXNG config
      .env                      # Symlink to /opt/odigos/.env
      data/                     # SQLite DB, uploads, prompt files
        agent/                  # Agent identity prompt sections
        prompts/                # Infrastructure prompt templates
        plugins/                # User-installed plugins
        files/                  # Uploaded files
      skills/                   # Empty (uses built-in skills from image)
      plugins/                  # Empty (uses built-in plugins from image)
    florence/
      ...same structure...
    jason/
      ...same structure...
```

### Docker Compose

Single `docker-compose.yml` with 3 services. Each service:
- Builds from `/opt/odigos/repo/` (the cloned repo serves as build context)
- Runs privileged (for bubblewrap sandbox)
- Adds `extra_hosts: ["host.docker.internal:host-gateway"]` for SearXNG access
- Restart policy: `unless-stopped`
- Binds tester-specific volumes:
  - `./testers/{name}/config.yaml:/app/config.yaml:ro`
  - `./testers/{name}/.env:/app/.env:ro`
  - `./testers/{name}/data:/app/data`
  - `./testers/{name}/skills:/app/skills:ro`
  - `./testers/{name}/plugins:/app/plugins:ro`
- Port mapping: `127.0.0.1:{host_port}:8000` (Caddy handles HTTPS)
- Environment: `LLM_API_KEY` from shared `.env`

### File ownership

The Dockerfile creates a non-root `odigos` user and runs as that user. Host-created `data/` directories will be root-owned and unwritable from inside the container. The deploy script must fix this by running `chown` after creating each tester's directories:

```bash
# Get the UID/GID the container will use
ODIGOS_UID=$(docker run --rm ghcr.io/tamler/odigos:latest id -u)
ODIGOS_GID=$(docker run --rm ghcr.io/tamler/odigos:latest id -g)
chown -R $ODIGOS_UID:$ODIGOS_GID /opt/odigos/testers/$name/data
```

If the image isn't pulled yet (building locally), the script should build first, then extract the UID. Alternatively, run the chown after the first `docker compose up` via `docker compose exec`.

### Caddy

Append 3 blocks to `/etc/caddy/Caddyfile`, guarded by a check to avoid duplicates on re-run:

```bash
if ! grep -q "jessica.uxrls.com" /etc/caddy/Caddyfile; then
  cat >> /etc/caddy/Caddyfile << 'EOF'

# Odigos tester instances
jessica.uxrls.com {
    reverse_proxy 127.0.0.1:8010
}

florence.uxrls.com {
    reverse_proxy 127.0.0.1:8011
}

jason.uxrls.com {
    reverse_proxy 127.0.0.1:8012
}
EOF
fi
systemctl reload caddy
```

Caddy auto-provisions Let's Encrypt certificates for each subdomain.

### Config per tester

Each `config.yaml` includes:
- `agent.name` set to tester's name (e.g., "Jessica's Agent")
- `api_key` auto-generated unique key
- `searxng_url: "http://host.docker.internal:8083"` (direct access, no auth needed from inside Docker)
- `searxng_username` and `searxng_password` omitted (not needed)
- Shared LLM config (OpenRouter, same model for all)

### SearXNG access

SearXNG runs on `127.0.0.1:8083` with no app-level auth. Docker containers reach it via `host.docker.internal:8083`. No credentials needed in config.yaml since Caddy auth only applies to external `search.uxrls.com` access.

## Deploy script

A single `deploy-testers.sh` script that:

1. Clones the Odigos repo to `/opt/odigos/repo/` (skip if already exists)
2. Builds the Docker image from `/opt/odigos/repo/`
3. Creates directory structure under `/opt/odigos/testers/`
4. Generates unique API key per tester
5. Writes `config.yaml` per tester
6. Creates `.env` symlinks per tester pointing to shared `/opt/odigos/.env`
7. Writes `docker-compose.yml`
8. Writes shared `.env` (prompts for LLM_API_KEY if not set)
9. Fixes data directory ownership (chown to container's odigos user)
10. Appends Caddy blocks to `/etc/caddy/Caddyfile` (idempotent, checks before appending) and reloads
11. Starts containers with `docker compose up -d`
12. Prints summary: URL + API key per tester

Run once on the VPS: `bash deploy-testers.sh`

## Resource estimate

- Each Odigos instance: ~1.5-2GB RAM (embeddings model loaded into RAM per container + Python runtime)
- 3 instances: ~4.5-6GB of 32GB available (29GB currently free)
- CPU: minimal idle usage, spikes during LLM calls (external API, not local)
- Disk: ~500MB for shared Docker image layers + ~50MB per tester data dir

## What testers receive

Each tester gets a message like:

```
Your Odigos agent is ready!

URL: https://jessica.uxrls.com
API Key: <key>

Open the URL, enter the API key when prompted, and start chatting.
The agent can search the web, run code, read documents, and more.
```

## Out of scope

- Path-based routing (future improvement, noted for later)
- Per-tester LLM keys
- Monitoring/alerting
- Automatic scaling
- Backup/restore
