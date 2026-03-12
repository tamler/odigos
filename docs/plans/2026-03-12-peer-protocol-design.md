# Peer Communication Protocol Upgrade

**Date:** 2026-03-12
**Status:** Approved

## Context

Odigos has basic agent-to-agent communication via AgentClient (WebSocket + HTTP fallback), heartbeat-driven peer announce, and specialist spawning. The protocol is informal: `AgentMessage` has type/from_agent/content/metadata but no `to_agent`, no correlation for request/response pairing, no retry logic, and an HTTP fallback that adds complexity without clear value.

This upgrade makes the protocol reliable and extensible for v1, without over-engineering typed payloads or formal state machines.

## Design Decisions

- **WebSocket only** for messaging. No HTTP fallback. Simpler, real-time, and avoids noisy dual-path logic.
- **Persistent outbox** for failed deliveries. Messages queue in SQLite and flush when the peer reconnects. No message loss.
- **Inert when solo.** If no peers are configured or connected, the entire peer system does nothing. Zero overhead for single-agent deployments.
- **Extensible envelope.** New message types added by using a new string, new payload shapes by putting different keys in the dict. No protocol changes needed.
- **HTTP discovery endpoint kept** for initial peer handshake (exchange WS coordinates). Auth required. Not used for ongoing messaging.

## 1. Envelope Format

Replace `AgentMessage` with `PeerEnvelope`:

```python
@dataclass
class PeerEnvelope:
    id: str                            # UUID, unique per message
    from_agent: str                    # sender name
    to_agent: str                      # recipient name
    type: str                          # message type (extensible string)
    payload: dict                      # flexible content, schema depends on type
    correlation_id: str | None = None  # links request to response
    priority: str = "normal"           # "low" | "normal" | "high"
    timestamp: str                     # ISO8601 UTC
```

- `type` is a string, not an enum. Existing types: `task_request`, `task_response`, `task_stream`, `eval_request`, `eval_response`, `registry_announce`, `status_ping`, `status_pong`.
- `payload` is an unvalidated dict. Each type's handler knows what to expect.
- `correlation_id` is set by the sender on requests. Responder copies it to the response envelope. This matches responses to requests.
- `priority` is advisory. V1 uses FIFO; priority-based ordering is a future option.
- `to_agent` enables future multi-hop routing. V1 uses it for validation ("is this message for me?").

## 2. Transport & Outbox

### Send Flow

1. Serialize `PeerEnvelope` to JSON.
2. If WebSocket to target peer is connected: send immediately, record in `peer_messages` with status `delivered`.
3. If WebSocket is down: record in `peer_messages` with status `queued`. Message sits in the outbox.

### Outbox Flush (Heartbeat Phase)

- New heartbeat phase: scan `peer_messages` for `status = 'queued'`, grouped by peer.
- For each peer with queued messages: if WS is now connected, send in FIFO order, update status to `delivered`.
- If still disconnected, leave queued.
- Messages expire after 24 hours (configurable). Expired messages marked `expired`, never retried.

### Receive Flow

1. Message arrives over WebSocket.
2. Deduplicate by `id`.
3. Validate `to_agent` matches this agent's name.
4. Record in `peer_messages` with status `received`.
5. Route to handler based on `type`.

### Inert When Solo

If `settings.peers` is empty AND `agent_registry` has no online peers, the heartbeat phase returns immediately. No outbox scanning, no announce broadcasts.

### HTTP Discovery

`POST /api/agent/peer/announce` — receives a one-time announcement with the peer's WS coordinates. Adds peer to registry. Requires API key auth. Not used for messaging.

## 3. AgentClient Changes

### Modifications

- `AgentMessage` replaced by `PeerEnvelope`.
- `send()` simplified: WS-only, returns `delivered` or `queued`.
- `handle_incoming()` parses `PeerEnvelope`, validates `to_agent`, routes by `type`.
- `_send_http()` removed entirely.

### New: `send_response()` Helper

```python
async def send_response(self, original: PeerEnvelope, payload: dict, type: str = "task_response"):
    """Send a response that automatically correlates to the original request."""
    # Builds envelope with to_agent=original.from_agent, correlation_id=original.correlation_id
```

### MessagePeerTool Update

- Accepts optional `priority` parameter (defaults to "normal").
- Wraps messages in `PeerEnvelope`.
- Returns delivery status (`delivered` or `queued`).

## 4. Migration & Cleanup

### Database

No schema changes. `peer_messages` table already has the right columns. Usage becomes more consistent:

- `response_to` stores `correlation_id`.
- `status` values: `queued`, `delivered`, `received`, `expired`.
- `metadata_json` stores the full serialized `PeerEnvelope` for audit.

### Remove

- `_send_http()` from AgentClient.
- `POST /api/agent/message` endpoint (replaced by WS-only messaging + announce endpoint).
- HTTP fallback logic in `send()`.

### Keep

- `POST /api/agent/peer/announce` — renamed discovery endpoint, accepts peer WS coordinates.
- `GET /ws/agent` — primary transport, unchanged.
- Registry/heartbeat announce logic — uses new envelope format.

### Config

No changes to `PeerConfig`. The `url` field becomes unused for messaging but remains for the announce endpoint.
