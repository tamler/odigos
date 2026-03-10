# Web UI Redesign & Onboarding Flow — Design Document

## Goal

Replace the current minimal Preact+HTM dashboard with a polished, production-grade chat UI with settings-first onboarding, file upload, and plugin-based voice support. The backend remains fully headless — the UI is optional.

## Architecture

**Frontend:** Vite + React + TypeScript + Tailwind CSS + shadcn/ui. Built to `dashboard/dist/`. Output committed to repo. FastAPI serves it as static files with SPA catch-all. Node.js is only needed on dev machines when editing the UI — Docker and Python never touch Node.

**Backend API additions:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/setup-status` | GET | Returns `{configured: bool}` for onboarding routing |
| `/api/settings` | GET | Read all config (secrets masked) |
| `/api/settings` | POST | Write config, hot-reload LLM client |
| `/api/upload` | POST | File upload, stores in `data/uploads/` |
| `/api/plugins` | GET | List plugins with declared capabilities |
| `/api/plugins/stt/stream` | WS | STT audio streaming (plugin-provided) |
| `/api/plugins/tts/generate` | POST | TTS generation (plugin-provided) |
| `/api/ws` | WS | Chat streaming (existing) |

**Auth:** Single API key (config.yaml or auto-generated). Stored in localStorage after first setup. Passed as `?token=` (WebSocket) and `Authorization: Bearer` (REST). No user accounts.

**Deployment:** Behind Caddy for TLS/reverse proxy. We document the Caddyfile pattern but don't build TLS in.

## Onboarding Flow

1. Browser loads SPA, calls `GET /api/setup-status`
2. `{configured: false}` — redirect to `/settings` with setup modal
3. Modal ("Welcome to Odigos") — single screen, three sections:
   - **LLM Provider** — dropdown (OpenRouter, OpenAI, Ollama, LM Studio, Custom), pre-fills base URL
   - **API Key** — password field, skippable for local models
   - **Model** — text input, sensible default per provider
4. "Save & Start" — `POST /api/settings` writes config.yaml/.env, backend hot-reloads LLM client
5. Redirect to chat, WebSocket connects, ready to go

**Returning visits:** `{configured: true}` — straight to chat. API key from localStorage auto-connects. Wrong key shows login prompt (key field only).

## Chat UI

**Layout:** Full-height single-page chat. Collapsible sidebar with conversation history. Header with agent name and connection status indicator.

**Message display:**
- Streaming markdown rendering (syntax-highlighted code blocks, tables, lists)
- User messages right-aligned, agent messages left-aligned
- Subtle timestamps (hover for full datetime)
- Thinking indicator with animated dots

**Input area (bottom):**
- Multi-line text input (auto-grow, shift+enter for newlines, enter to send)
- Attachment button — file picker, thumbnail/filename preview before send
- Mic button — only visible when STT plugin installed
- Speaker button — only visible when TTS plugin installed
- Send button

**File upload:**
- Drag-and-drop onto chat area, or click attachment button
- `POST /api/upload` stores file, returns reference for chat message context
- Image preview for images, filename+size for other types

## Settings Page

All configuration editable from the UI, grouped into sections:

- **LLM** — provider URL, API key, default model, fallback model, max tokens, temperature
- **Budget** — daily limit, monthly limit
- **Agent** — name, max tool turns, run timeout
- **Advanced** — heartbeat interval, sandbox timeout/memory/network, peer configs
- **Plugins** — list of installed plugins with their settings (rendered from manifest)

Changes saved via `POST /api/settings`, hot-reloaded where possible.

## Plugin System for Voice

**Manifest:** Each plugin has a `manifest.json`:

```json
{
  "name": "moonshine-stt",
  "description": "Local speech-to-text using Moonshine",
  "capabilities": ["stt"],
  "settings": {
    "model_size": {
      "type": "select",
      "options": ["tiny", "base", "medium"],
      "default": "base"
    }
  }
}
```

**STT plugin** — exposes WebSocket endpoint. Browser sends mic audio chunks, plugin returns transcribed text inserted into input field.

**TTS plugin** — exposes REST endpoint. Takes text, returns audio. Browser plays it.

Both run in-process (Python, CPU). No separate services.

**UI discovery:** Frontend checks `GET /api/plugins` for `"stt"`/`"tts"` capabilities. Mic/speaker buttons appear only when plugins are installed.

**Installation:** Drop plugin folder into `plugins/`, restart container or hit reload endpoint. Plugin settings rendered in Settings page from manifest.

**Target plugins (CPU, self-hosted):**
- STT: Moonshine (`pip install moonshine-voice`) — 26MB-245MB models, runs on CPU
- TTS: Pocket TTS (`pip install pocket-tts`) — 100M params, CPU-only, ~200ms first chunk

## API-First / Headless

The UI is optional. The backend is fully functional without it:
- Delete `dashboard/dist/` — API-only mode automatically
- Mount a custom frontend to the same static path
- Build a separate app against `/api/*` endpoints
- FastAPI static serving is a catch-all fallback after API routes
