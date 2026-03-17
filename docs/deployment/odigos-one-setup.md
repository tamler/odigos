# odigos.one Production Deployment

## Overview

The odigos.one VPS (82.25.91.86) runs three services:

| Service | Port | URL | Purpose |
|---|---|---|---|
| Node website | 3000 | odigos.one | Company landing page |
| Sales agent | 8001 | odigos.one/api/*, /ws | Public-facing sales/demo agent |
| Jacob's agent | 8000 | jacob.odigos.one | Private personal agent |

Caddy handles TLS and routing. Wildcard DNS (*.odigos.one) is configured.

## VPS Details

- **IP:** 82.25.91.86
- **SSH:** `ssh root@82.25.91.86` (via Tailscale: `ssh root@100.89.147.103`)
- **OS:** Ubuntu 24.04, 4 CPU, 16GB RAM
- **DNS:** `*.odigos.one` CNAME → `odigos.one` → `82.25.91.86`

## Caddy Configuration

```
/etc/caddy/Caddyfile
```

Routes:
- `odigos.one /api/*` → sales agent (localhost:8001)
- `odigos.one /ws` → sales agent WebSocket (localhost:8001)
- `odigos.one /health` → sales agent health check
- `odigos.one /*` (everything else) → Node website (localhost:3000)
- `jacob.odigos.one` → personal agent (localhost:8000)

## Sales Agent

**Location:** `/opt/odigos-sales/`
**Service:** `systemctl {start|stop|restart|status} odigos-sales`
**Logs:** `journalctl -u odigos-sales -f`

### Directory Layout
```
/opt/odigos-sales/
  repo/                    # Git clone of odigos (code)
  config.yaml              # Agent config
  .env                     # LLM_API_KEY + SESSION_SECRET
  data/
    agent/identity.md      # Sales agent identity prompt
    prompts/               # Infrastructure prompts (from repo)
    files/                 # Uploaded files
    odigos.db              # SQLite database
  skills/
    product-demo.md        # Product walkthrough skill
    handle-objections.md   # Objection handling skill
    qualify-lead.md        # Lead qualification skill
```

### Config
- **Models:** Gemini 3 Flash (default), DeepSeek V3.2 (fallback), Gemini 3.1 Flash Lite (background)
- **Budget:** $5/day, $50/month
- **Mesh:** Enabled, peers with Jacob's personal agent
- **API Key:** `y8nsWkQ1yKSR76Tb7MIEogJUJXV9pvM7ZRfEfeg1_5c`
- **Admin:** username `admin`, temp password `odigos-sales-2026` (forced change)

### Website Integration
The Node website at odigos.one can reach the sales agent via:
- **REST:** `POST https://odigos.one/api/agent/message`
- **WebSocket:** `wss://odigos.one/ws`
- **Auth:** `Authorization: Bearer y8nsWkQ1yKSR76Tb7MIEogJUJXV9pvM7ZRfEfeg1_5c`

## Jacob's Personal Agent

**Location:** `/opt/odigos/`
**Service:** `systemctl {start|stop|restart|status} odigos`
**Logs:** `journalctl -u odigos -f`
**URL:** https://jacob.odigos.one

### Config
- **Models:** Gemini 3 Flash (default + reasoning), DeepSeek V3.2 (fallback), Gemini 3.1 Flash Lite (background)
- **Budget:** $10/day, $100/month
- **Mesh:** Enabled, peers with sales agent
- **Voice:** TTS + STT enabled

## Mesh Networking

Both agents are peers:
- Sales agent → can message Jacob's agent for questions it can't answer
- Jacob's agent → can message sales agent (e.g., check on visitor interactions)

## Tester Deployment (separate VPS)

See `deploy-testers.sh` for the 3-instance tester setup on 85.31.224.187.

## Updating

```bash
# Update sales agent
cd /opt/odigos-sales/repo && git pull
systemctl restart odigos-sales

# Update personal agent
cd /opt/odigos && git pull
systemctl restart odigos

# Update both
cd /opt/odigos-sales/repo && git pull && cd /opt/odigos && git pull
systemctl restart odigos odigos-sales
```
