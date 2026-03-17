# Odigos Integration API

Quick reference for embedding Odigos in third-party applications (websites, bots, custom UIs).

## Authentication

All endpoints require one of:
- **Session cookie** (browser-based, set by `/api/auth/login`)
- **Bearer token** (API key): `Authorization: Bearer <api_key>`

## Core Chat Endpoints

### WebSocket (real-time, recommended)

```
wss://<host>/api/ws?token=<api_key>
```

Or connect without query param and send auth as first message:
```json
{"type": "auth", "token": "<api_key>"}
```

**Incoming messages (server → client):**
```json
{"type": "connected", "session_id": "...", "conversation_id": "web:..."}
{"type": "status", "text": "Thinking..."}
{"type": "status", "text": "Using search_documents..."}
{"type": "chat_response", "content": "The answer is...", "conversation_id": "web:..."}
{"type": "notification", "title": "Update", "body": "Task completed", "priority": "info"}
{"type": "title_updated", "conversation_id": "web:...", "title": "Auto-generated title"}
```

**Outgoing messages (client → server):**
```json
{"type": "chat", "content": "Hello, what can you do?"}
{"type": "chat", "content": "Tell me about Odigos", "conversation_id": "web:abc123"}
```

### REST (simple, one-shot)

```
POST /api/message
Content-Type: application/json
Authorization: Bearer <api_key>

{
  "content": "Hello, what can you do?",
  "conversation_id": "optional-existing-id"
}
```

**Response:**
```json
{
  "response": "I can help you with...",
  "conversation_id": "api:abc123def456"
}
```

**Note:** The request body field is `content` (not `message`). The response field is `response` (not `message` or `content`).

## Other Useful Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Health check (no auth) |
| `/api/auth/status` | GET | Check auth state (no auth) |
| `/api/auth/login` | POST | Login with username/password |
| `/api/conversations` | GET | List conversations |
| `/api/conversations/{id}` | GET | Get conversation with messages |
| `/api/documents` | GET | List uploaded documents |
| `/api/upload` | POST | Upload a file (multipart) |
| `/api/analytics/overview` | GET | Agent analytics summary |
| `/api/settings` | GET | Current settings (masked secrets) |

## Full API Reference

All endpoints use the `/api` prefix. See `odigos/api/` source files for complete documentation.

## Embedding in a Website

For public-facing chat widgets:

1. **Don't embed the API key in client-side JavaScript.** Use a server-side proxy.
2. Your backend holds the API key and proxies requests to Odigos.
3. Or implement a session token system on your server that issues short-lived tokens.

Example server-side proxy (Node.js):
```javascript
// Your server holds the key
const ODIGOS_KEY = process.env.ODIGOS_API_KEY;

app.post('/chat', async (req, res) => {
  const response = await fetch('http://localhost:8001/api/message', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${ODIGOS_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ content: req.body.message }),
  });
  const data = await response.json();
  res.json({ reply: data.response });
});
```

For WebSocket proxying, use a library like `ws` to bridge client connections to the Odigos WebSocket.
