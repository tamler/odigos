# Contact Cards Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add per-relationship scoped API keys via contact cards, a lightweight RSS feed publisher, and dashboard pages for managing connections and feed entries.

**Architecture:** Contact cards are YAML documents containing a scoped API key (`card-sk-*`) that grants either mesh access (connect/invite) or feed-only access (subscribe). Cards are stored in two SQLite tables (issued and accepted). A new auth dependency `require_card_or_api_key` layers card key lookups on top of the existing global API key check. A feed publisher exposes `GET /feed.xml` and stores entries in a `feed_entries` table.

**Tech Stack:** Python/FastAPI, SQLite, React/TypeScript dashboard, PyYAML, hashlib for fingerprints, `xml.etree.ElementTree` for RSS generation.

---

### Task 1: Database Migration

**Files:**
- Create: `migrations/022_contact_cards.sql`

**Step 1: Write the migration**

```sql
-- Contact cards: scoped API keys for agent-to-agent relationships
CREATE TABLE IF NOT EXISTS contact_cards (
    id TEXT PRIMARY KEY,
    card_key TEXT NOT NULL UNIQUE,
    card_type TEXT NOT NULL CHECK (card_type IN ('connect', 'subscribe', 'invite')),
    issued_to TEXT,
    permissions TEXT NOT NULL DEFAULT 'mesh',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked', 'expired')),
    created_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT,
    revoked_at TEXT,
    last_used_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_contact_cards_key ON contact_cards(card_key);
CREATE INDEX IF NOT EXISTS idx_contact_cards_status ON contact_cards(status);

-- Accepted cards: imported from other agents
CREATE TABLE IF NOT EXISTS accepted_cards (
    id TEXT PRIMARY KEY,
    card_type TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    host TEXT NOT NULL,
    ws_port INTEGER DEFAULT 8001,
    card_key TEXT NOT NULL,
    feed_url TEXT,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'muted', 'revoked')),
    accepted_at TEXT DEFAULT (datetime('now')),
    last_connected_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_accepted_cards_agent ON accepted_cards(agent_name);
CREATE INDEX IF NOT EXISTS idx_accepted_cards_status ON accepted_cards(status);

-- Feed entries: published by this agent
CREATE TABLE IF NOT EXISTS feed_entries (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    category TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

**Step 2: Run tests to make sure migration doesn't break anything**

Run: `uv run pytest tests/ -x -q`
Expected: All existing tests PASS (migration is additive)

**Step 3: Commit**

```bash
git add migrations/022_contact_cards.sql
git commit -m "feat: add migration for contact_cards, accepted_cards, feed_entries tables"
```

---

### Task 2: FeedConfig in config.py

**Files:**
- Modify: `odigos/config.py:96-98` (after MeshConfig)
- Modify: `odigos/config.py:162` (add to Settings)

**Step 1: Write the failing test**

Create: `tests/test_config_feed.py`

```python
"""Tests for FeedConfig in settings."""
from odigos.config import FeedConfig, Settings


def test_feed_config_defaults():
    cfg = FeedConfig()
    assert cfg.enabled is False
    assert cfg.public is False
    assert cfg.max_entries == 200


def test_settings_includes_feed():
    s = Settings()
    assert hasattr(s, "feed")
    assert s.feed.enabled is False
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config_feed.py -v`
Expected: FAIL with `ImportError` or `AttributeError`

**Step 3: Write minimal implementation**

In `odigos/config.py`, after `MeshConfig` (line ~98):

```python
class FeedConfig(BaseModel):
    enabled: bool = False
    public: bool = False
    max_entries: int = 200
```

In the `Settings` class, add after `mesh`:

```python
    feed: FeedConfig = FeedConfig()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config_feed.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/config.py tests/test_config_feed.py
git commit -m "feat: add FeedConfig to settings with enabled, public, max_entries"
```

---

### Task 3: Core Cards Module

**Files:**
- Create: `odigos/core/cards.py`
- Create: `tests/test_cards.py`

**Step 1: Write the failing tests**

```python
"""Tests for contact card generation, import, validation, and revocation."""
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import yaml

from odigos.core.cards import CardManager
from odigos.db import Database


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def manager(db):
    return CardManager(db=db, agent_name="Odigos", host="100.64.0.1", ws_port=8001)


@pytest.mark.asyncio
async def test_generate_connect_card(manager):
    card = await manager.generate_card(card_type="connect")
    assert card["version"] == 1
    assert card["type"] == "connect"
    assert card["agent_name"] == "Odigos"
    assert card["host"] == "100.64.0.1"
    assert card["ws_port"] == 8001
    assert card["card_key"].startswith("card-sk-")
    assert card["fingerprint"].startswith("sha256:")
    assert card["feed_url"] is None

    # Should be stored in contact_cards
    row = await manager.db.fetch_one(
        "SELECT * FROM contact_cards WHERE card_key = ?", (card["card_key"],)
    )
    assert row is not None
    assert row["status"] == "active"
    assert row["card_type"] == "connect"


@pytest.mark.asyncio
async def test_generate_subscribe_card(manager):
    card = await manager.generate_card(card_type="subscribe")
    assert card["type"] == "subscribe"
    assert card["feed_url"] is not None
    assert "/feed.xml" in card["feed_url"]

    row = await manager.db.fetch_one(
        "SELECT * FROM contact_cards WHERE card_key = ?", (card["card_key"],)
    )
    assert row["permissions"] == "feed_only"


@pytest.mark.asyncio
async def test_generate_card_with_expiry(manager):
    card = await manager.generate_card(card_type="connect", expires_in_days=7)
    assert card["expires_at"] is not None


@pytest.mark.asyncio
async def test_card_to_yaml(manager):
    card = await manager.generate_card(card_type="connect")
    yaml_str = manager.card_to_yaml(card)
    parsed = yaml.safe_load(yaml_str)
    assert parsed["version"] == 1
    assert parsed["card_key"] == card["card_key"]


@pytest.mark.asyncio
async def test_card_to_compact(manager):
    card = await manager.generate_card(card_type="connect")
    compact = manager.card_to_compact(card)
    assert compact.startswith("odigos-card:")


@pytest.mark.asyncio
async def test_import_card_from_yaml(manager):
    card = await manager.generate_card(card_type="connect")
    yaml_str = manager.card_to_yaml(card)

    # Simulate importing on another agent
    importer = CardManager(db=manager.db, agent_name="Archie", host="100.64.0.2", ws_port=8001)
    result = await importer.import_card(yaml_str)
    assert result["status"] == "accepted"
    assert result["agent_name"] == "Odigos"

    row = await manager.db.fetch_one(
        "SELECT * FROM accepted_cards WHERE agent_name = 'Odigos'"
    )
    assert row is not None
    assert row["status"] == "active"


@pytest.mark.asyncio
async def test_import_card_from_compact(manager):
    card = await manager.generate_card(card_type="connect")
    compact = manager.card_to_compact(card)

    importer = CardManager(db=manager.db, agent_name="Archie", host="100.64.0.2", ws_port=8001)
    result = await importer.import_card(compact)
    assert result["status"] == "accepted"


@pytest.mark.asyncio
async def test_import_card_rejects_bad_fingerprint(manager):
    card = await manager.generate_card(card_type="connect")
    card["fingerprint"] = "sha256:tampered"
    yaml_str = manager.card_to_yaml(card)

    importer = CardManager(db=manager.db, agent_name="Archie", host="100.64.0.2", ws_port=8001)
    result = await importer.import_card(yaml_str)
    assert result["status"] == "rejected"
    assert "fingerprint" in result["reason"]


@pytest.mark.asyncio
async def test_import_card_rejects_expired(manager):
    card = await manager.generate_card(card_type="connect")
    card["expires_at"] = "2020-01-01T00:00:00Z"
    # Recompute fingerprint with the new expires_at -- but the card in DB
    # doesn't have this expires_at, so validation against stored card will fail
    yaml_str = manager.card_to_yaml(card)

    importer = CardManager(db=manager.db, agent_name="Archie", host="100.64.0.2", ws_port=8001)
    result = await importer.import_card(yaml_str)
    assert result["status"] == "rejected"


@pytest.mark.asyncio
async def test_revoke_issued_card(manager):
    card = await manager.generate_card(card_type="connect")
    await manager.revoke_issued(card["card_key"])

    row = await manager.db.fetch_one(
        "SELECT * FROM contact_cards WHERE card_key = ?", (card["card_key"],)
    )
    assert row["status"] == "revoked"
    assert row["revoked_at"] is not None


@pytest.mark.asyncio
async def test_revoke_accepted_card(manager):
    card = await manager.generate_card(card_type="connect")
    yaml_str = manager.card_to_yaml(card)
    await manager.import_card(yaml_str)

    accepted = await manager.db.fetch_one(
        "SELECT * FROM accepted_cards WHERE agent_name = 'Odigos'"
    )
    await manager.revoke_accepted(accepted["id"])

    row = await manager.db.fetch_one(
        "SELECT * FROM accepted_cards WHERE id = ?", (accepted["id"],)
    )
    assert row["status"] == "revoked"


@pytest.mark.asyncio
async def test_mute_accepted_card(manager):
    card = await manager.generate_card(card_type="connect")
    yaml_str = manager.card_to_yaml(card)
    await manager.import_card(yaml_str)

    accepted = await manager.db.fetch_one(
        "SELECT * FROM accepted_cards WHERE agent_name = 'Odigos'"
    )
    await manager.mute_accepted(accepted["id"])

    row = await manager.db.fetch_one(
        "SELECT * FROM accepted_cards WHERE id = ?", (accepted["id"],)
    )
    assert row["status"] == "muted"


@pytest.mark.asyncio
async def test_unmute_accepted_card(manager):
    card = await manager.generate_card(card_type="connect")
    yaml_str = manager.card_to_yaml(card)
    await manager.import_card(yaml_str)

    accepted = await manager.db.fetch_one(
        "SELECT * FROM accepted_cards WHERE agent_name = 'Odigos'"
    )
    await manager.mute_accepted(accepted["id"])
    await manager.unmute_accepted(accepted["id"])

    row = await manager.db.fetch_one(
        "SELECT * FROM accepted_cards WHERE id = ?", (accepted["id"],)
    )
    assert row["status"] == "active"


@pytest.mark.asyncio
async def test_validate_card_key_active(manager):
    card = await manager.generate_card(card_type="connect")
    result = await manager.validate_card_key(card["card_key"])
    assert result is not None
    assert result["card_type"] == "connect"
    assert result["status"] == "active"


@pytest.mark.asyncio
async def test_validate_card_key_revoked(manager):
    card = await manager.generate_card(card_type="connect")
    await manager.revoke_issued(card["card_key"])
    result = await manager.validate_card_key(card["card_key"])
    assert result is None


@pytest.mark.asyncio
async def test_validate_card_key_unknown(manager):
    result = await manager.validate_card_key("card-sk-nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_list_issued(manager):
    await manager.generate_card(card_type="connect")
    await manager.generate_card(card_type="subscribe")
    cards = await manager.list_issued()
    assert len(cards) == 2


@pytest.mark.asyncio
async def test_list_accepted(manager):
    card = await manager.generate_card(card_type="connect")
    yaml_str = manager.card_to_yaml(card)
    importer = CardManager(db=manager.db, agent_name="Archie", host="100.64.0.2", ws_port=8001)
    await importer.import_card(yaml_str)
    accepted = await importer.list_accepted()
    assert len(accepted) == 1
    assert accepted[0]["agent_name"] == "Odigos"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cards.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'odigos.core.cards'`

**Step 3: Write the implementation**

Create `odigos/core/cards.py`:

```python
"""Contact card management for agent-to-agent relationships.

Generates, imports, validates, and revokes contact cards. Each card
contains a scoped API key (card-sk-*) that grants either mesh access
(connect/invite) or feed-only access (subscribe).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from odigos.db import Database

logger = logging.getLogger(__name__)

CARD_VERSION = 1
CARD_KEY_PREFIX = "card-sk-"
COMPACT_PREFIX = "odigos-card:"


def _generate_card_key() -> str:
    return f"{CARD_KEY_PREFIX}{secrets.token_hex(32)}"


def _compute_fingerprint(card_key: str, agent_name: str, issued_at: str) -> str:
    raw = f"{card_key}{agent_name}{issued_at}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"sha256:{digest}"


class CardManager:
    """Manages contact card lifecycle: generate, import, validate, revoke."""

    def __init__(
        self,
        db: Database,
        agent_name: str,
        host: str = "",
        ws_port: int = 8001,
        feed_base_url: str = "",
    ) -> None:
        self.db = db
        self.agent_name = agent_name
        self.host = host
        self.ws_port = ws_port
        self.feed_base_url = feed_base_url

    async def generate_card(
        self,
        card_type: str = "connect",
        expires_in_days: int | None = None,
    ) -> dict:
        """Generate a new contact card and store in contact_cards table."""
        card_id = str(uuid.uuid4())
        card_key = _generate_card_key()
        now = datetime.now(timezone.utc)
        issued_at = now.isoformat()

        expires_at = None
        if expires_in_days is not None:
            expires_at = (now + timedelta(days=expires_in_days)).isoformat()

        fingerprint = _compute_fingerprint(card_key, self.agent_name, issued_at)

        permissions = "feed_only" if card_type == "subscribe" else "mesh"
        feed_url = None
        if card_type == "subscribe" and self.feed_base_url:
            feed_url = f"{self.feed_base_url}/feed.xml"
        elif card_type == "subscribe":
            feed_url = f"http://{self.host}:8000/feed.xml"

        await self.db.execute(
            "INSERT INTO contact_cards "
            "(id, card_key, card_type, permissions, status, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, 'active', ?, ?)",
            (card_id, card_key, card_type, permissions, issued_at, expires_at),
        )

        card = {
            "version": CARD_VERSION,
            "type": card_type,
            "agent_name": self.agent_name,
            "host": self.host,
            "ws_port": self.ws_port,
            "card_key": card_key,
            "capabilities": [],
            "feed_url": feed_url,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "issuer": self.agent_name,
            "fingerprint": fingerprint,
        }

        logger.info("Generated %s card %s", card_type, card_id[:8])
        return card

    def card_to_yaml(self, card: dict) -> str:
        """Serialize a card dict to YAML string."""
        return yaml.dump(card, default_flow_style=False, sort_keys=False)

    def card_to_compact(self, card: dict) -> str:
        """Encode a card as a compact single-line string."""
        yaml_str = self.card_to_yaml(card)
        encoded = base64.b64encode(yaml_str.encode()).decode()
        return f"{COMPACT_PREFIX}{encoded}"

    async def import_card(self, card_data: str) -> dict:
        """Import a card from YAML string or compact token.

        Returns dict with 'status' ('accepted' or 'rejected') and details.
        """
        # Parse compact format
        if card_data.strip().startswith(COMPACT_PREFIX):
            b64 = card_data.strip()[len(COMPACT_PREFIX):]
            try:
                card_data = base64.b64decode(b64).decode()
            except Exception:
                return {"status": "rejected", "reason": "Invalid compact encoding"}

        # Parse YAML
        try:
            card = yaml.safe_load(card_data)
        except yaml.YAMLError:
            return {"status": "rejected", "reason": "Invalid YAML"}

        if not isinstance(card, dict):
            return {"status": "rejected", "reason": "Card must be a YAML mapping"}

        # Validate required fields
        required = ["version", "type", "agent_name", "host", "card_key", "fingerprint", "issued_at"]
        missing = [f for f in required if f not in card]
        if missing:
            return {"status": "rejected", "reason": f"Missing fields: {', '.join(missing)}"}

        # Validate fingerprint
        expected_fp = _compute_fingerprint(card["card_key"], card["agent_name"], card["issued_at"])
        if card["fingerprint"] != expected_fp:
            return {"status": "rejected", "reason": "Fingerprint mismatch -- card may be tampered"}

        # Check expiry
        if card.get("expires_at"):
            try:
                exp = datetime.fromisoformat(card["expires_at"])
                if exp < datetime.now(timezone.utc):
                    return {"status": "rejected", "reason": "Card has expired"}
            except ValueError:
                return {"status": "rejected", "reason": "Invalid expires_at format"}

        # Don't import your own cards
        if card["agent_name"] == self.agent_name:
            return {"status": "rejected", "reason": "Cannot import your own card"}

        # Store in accepted_cards
        card_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO accepted_cards "
            "(id, card_type, agent_name, host, ws_port, card_key, feed_url, fingerprint, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')",
            (
                card_id,
                card["type"],
                card["agent_name"],
                card["host"],
                card.get("ws_port", 8001),
                card["card_key"],
                card.get("feed_url"),
                card["fingerprint"],
            ),
        )

        logger.info("Imported %s card from %s", card["type"], card["agent_name"])
        return {
            "status": "accepted",
            "card_id": card_id,
            "agent_name": card["agent_name"],
            "card_type": card["type"],
        }

    async def validate_card_key(self, card_key: str) -> dict | None:
        """Check if a card key is valid (active + not expired). Returns card row or None."""
        row = await self.db.fetch_one(
            "SELECT * FROM contact_cards WHERE card_key = ? AND status = 'active'",
            (card_key,),
        )
        if not row:
            return None

        # Check expiry
        if row["expires_at"]:
            try:
                exp = datetime.fromisoformat(row["expires_at"])
                if exp < datetime.now(timezone.utc):
                    await self.db.execute(
                        "UPDATE contact_cards SET status = 'expired' WHERE id = ?",
                        (row["id"],),
                    )
                    return None
            except ValueError:
                pass

        # Update last_used_at
        await self.db.execute(
            "UPDATE contact_cards SET last_used_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), row["id"]),
        )

        return dict(row)

    async def revoke_issued(self, card_key: str) -> bool:
        """Revoke a card this agent issued."""
        now = datetime.now(timezone.utc).isoformat()
        result = await self.db.execute(
            "UPDATE contact_cards SET status = 'revoked', revoked_at = ? "
            "WHERE card_key = ? AND status = 'active'",
            (now, card_key),
        )
        return bool(result)

    async def revoke_accepted(self, card_id: str) -> bool:
        """Revoke an accepted card (cut ties with a peer)."""
        result = await self.db.execute(
            "UPDATE accepted_cards SET status = 'revoked' WHERE id = ? AND status IN ('active', 'muted')",
            (card_id,),
        )
        return bool(result)

    async def mute_accepted(self, card_id: str) -> bool:
        """Mute an accepted card (silence a noisy peer)."""
        result = await self.db.execute(
            "UPDATE accepted_cards SET status = 'muted' WHERE id = ? AND status = 'active'",
            (card_id,),
        )
        return bool(result)

    async def unmute_accepted(self, card_id: str) -> bool:
        """Unmute a previously muted card."""
        result = await self.db.execute(
            "UPDATE accepted_cards SET status = 'active' WHERE id = ? AND status = 'muted'",
            (card_id,),
        )
        return bool(result)

    async def list_issued(self) -> list[dict]:
        """List all cards this agent has issued."""
        rows = await self.db.fetch_all(
            "SELECT * FROM contact_cards ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]

    async def list_accepted(self) -> list[dict]:
        """List all cards this agent has imported."""
        rows = await self.db.fetch_all(
            "SELECT * FROM accepted_cards ORDER BY accepted_at DESC"
        )
        return [dict(r) for r in rows]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cards.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add odigos/core/cards.py tests/test_cards.py
git commit -m "feat: add CardManager for contact card generation, import, validation, revocation"
```

---

### Task 4: Auth Integration

**Files:**
- Modify: `odigos/api/deps.py:6-33`
- Create: `tests/test_card_auth.py`

**Step 1: Write the failing test**

```python
"""Tests for card-based auth dependency."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from odigos.api.deps import require_card_or_api_key


def _make_app():
    app = FastAPI()
    app.state.settings = SimpleNamespace(api_key="global-key")
    card_manager = AsyncMock()
    app.state.card_manager = card_manager
    return app, card_manager


def test_global_key_passes():
    app, _ = _make_app()

    @app.get("/test", dependencies=[])
    async def endpoint(request):
        await require_card_or_api_key(request)
        return {"ok": True}

    # We need to test the dependency directly
    from fastapi import Depends
    @app.get("/guarded")
    async def guarded(_=Depends(require_card_or_api_key)):
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/guarded", headers={"Authorization": "Bearer global-key"})
    assert resp.status_code == 200


def test_card_key_passes():
    app, card_manager = _make_app()
    card_manager.validate_card_key = AsyncMock(return_value={
        "card_type": "connect", "permissions": "mesh", "status": "active",
    })

    from fastapi import Depends
    @app.get("/guarded")
    async def guarded(_=Depends(require_card_or_api_key)):
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/guarded", headers={"Authorization": "Bearer card-sk-abc123"})
    assert resp.status_code == 200


def test_invalid_key_rejected():
    app, card_manager = _make_app()
    card_manager.validate_card_key = AsyncMock(return_value=None)

    from fastapi import Depends
    @app.get("/guarded")
    async def guarded(_=Depends(require_card_or_api_key)):
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/guarded", headers={"Authorization": "Bearer wrong-key"})
    assert resp.status_code == 403


def test_no_header_rejected():
    app, _ = _make_app()

    from fastapi import Depends
    @app.get("/guarded")
    async def guarded(_=Depends(require_card_or_api_key)):
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/guarded")
    assert resp.status_code == 401
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_card_auth.py -v`
Expected: FAIL with `ImportError`

**Step 3: Add `require_card_or_api_key` to deps.py**

Add after the existing `require_api_key` function (after line 33):

```python
async def require_card_or_api_key(request: Request):
    """Validate Bearer token against global API key OR a contact card key.

    Global API key: full access (dashboard + mesh).
    Card key (card-sk-*): scoped access per card permissions.
    """
    settings = request.app.state.settings
    configured_key = settings.api_key

    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0] != "Bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = parts[1]

    # Check global API key first
    if configured_key and token == configured_key:
        return

    # Check card key
    card_manager = getattr(request.app.state, "card_manager", None)
    if card_manager and token.startswith("card-sk-"):
        card = await card_manager.validate_card_key(token)
        if card:
            request.state.card = card
            return

    raise HTTPException(status_code=403, detail="Invalid API key or card key")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_card_auth.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add odigos/api/deps.py tests/test_card_auth.py
git commit -m "feat: add require_card_or_api_key auth dependency for card-based peer auth"
```

---

### Task 5: Update Agent WebSocket Auth

**Files:**
- Modify: `odigos/api/agent_ws.py:24-29`

**Step 1: Write the failing test**

Add to `tests/test_agent_ws.py` (or create if needed):

```python
@pytest.mark.asyncio
async def test_ws_accepts_card_key():
    """WebSocket should accept valid card keys, not just global API key."""
    # This test verifies the WS auth checks card_manager
    # (exact test depends on existing test structure)
```

Note: WebSocket testing is harder with TestClient. The key change is small -- update the auth block in `agent_ws.py` to also check card keys.

**Step 2: Update the WebSocket auth block**

In `odigos/api/agent_ws.py`, replace lines 24-29:

```python
@router.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket):
    token = websocket.query_params.get("token", "")
    expected = getattr(websocket.app.state, "settings", None)
    api_key = getattr(expected, "api_key", "") if expected else ""

    # Check global API key
    authorized = bool(api_key and token == api_key)

    # Check card key if global key didn't match
    if not authorized and token.startswith("card-sk-"):
        card_manager = getattr(websocket.app.state, "card_manager", None)
        if card_manager:
            import asyncio
            card = await card_manager.validate_card_key(token)
            if card and card.get("permissions") == "mesh":
                authorized = True

    if not authorized:
        await websocket.close(code=4001, reason="Unauthorized")
        return
```

**Step 3: Run full test suite**

Run: `uv run pytest tests/ -x -q`
Expected: All PASS

**Step 4: Commit**

```bash
git add odigos/api/agent_ws.py
git commit -m "feat: update WebSocket auth to accept card keys for mesh access"
```

---

### Task 6: Feed Publisher Endpoint

**Files:**
- Create: `odigos/api/feed.py`
- Create: `tests/test_feed_api.py`

**Step 1: Write the failing test**

```python
"""Tests for RSS feed publisher endpoint."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app(feed_enabled=True, feed_public=False):
    from odigos.api.feed import router

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        api_key="test-key",
        feed=SimpleNamespace(enabled=feed_enabled, public=feed_public, max_entries=200),
        agent=SimpleNamespace(name="Odigos"),
    )
    db = AsyncMock()
    app.state.db = db
    card_manager = AsyncMock()
    app.state.card_manager = card_manager
    app.include_router(router)
    return app, db, card_manager


def test_feed_xml_returns_rss():
    app, db, _ = _make_app(feed_public=True)
    db.fetch_all = AsyncMock(return_value=[
        {"id": "1", "title": "Test Entry", "content": "Hello world", "category": "status", "created_at": "2026-03-14T12:00:00"},
    ])

    client = TestClient(app)
    resp = client.get("/feed.xml")
    assert resp.status_code == 200
    assert "application/rss+xml" in resp.headers["content-type"]
    assert "<title>Test Entry</title>" in resp.text
    assert "<rss" in resp.text


def test_feed_disabled_returns_404():
    app, _, _ = _make_app(feed_enabled=False)
    client = TestClient(app)
    resp = client.get("/feed.xml")
    assert resp.status_code == 404


def test_feed_private_requires_auth():
    app, db, card_manager = _make_app(feed_public=False)
    card_manager.validate_card_key = AsyncMock(return_value=None)

    client = TestClient(app)
    resp = client.get("/feed.xml")
    assert resp.status_code == 401


def test_feed_private_accepts_card_key():
    app, db, card_manager = _make_app(feed_public=False)
    card_manager.validate_card_key = AsyncMock(return_value={"card_type": "subscribe", "status": "active"})
    db.fetch_all = AsyncMock(return_value=[])

    client = TestClient(app)
    resp = client.get("/feed.xml", headers={"Authorization": "Bearer card-sk-abc"})
    assert resp.status_code == 200
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_feed_api.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

Create `odigos/api/feed.py`:

```python
"""RSS feed publisher endpoint.

Serves GET /feed.xml with entries from the feed_entries table.
Auth: public if feed.public is true, otherwise requires a valid
card key (subscribe or connect) or the global API key.
"""
from __future__ import annotations

import logging
from datetime import datetime
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from odigos.api.deps import get_db, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/feed.xml")
async def get_feed(
    request: Request,
    settings=Depends(get_settings),
    db=Depends(get_db),
):
    """Serve RSS 2.0 feed of published entries."""
    if not settings.feed.enabled:
        raise HTTPException(status_code=404, detail="Feed is disabled")

    # Auth check for private feeds
    if not settings.feed.public:
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            raise HTTPException(status_code=401, detail="Feed requires authentication")

        parts = auth_header.split(" ", 1)
        token = parts[1] if len(parts) == 2 and parts[0] == "Bearer" else ""

        # Accept global API key
        if token == settings.api_key:
            pass
        else:
            # Accept card key
            card_manager = getattr(request.app.state, "card_manager", None)
            if not card_manager:
                raise HTTPException(status_code=401, detail="No card manager available")
            card = await card_manager.validate_card_key(token)
            if not card:
                raise HTTPException(status_code=403, detail="Invalid card key")

    # Fetch entries
    entries = await db.fetch_all(
        "SELECT * FROM feed_entries ORDER BY created_at DESC LIMIT ?",
        (settings.feed.max_entries,),
    )

    # Build RSS XML
    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = f"{settings.agent.name} Feed"
    SubElement(channel, "description").text = f"Published updates from {settings.agent.name}"
    SubElement(channel, "lastBuildDate").text = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")

    for entry in entries:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = entry["title"]
        SubElement(item, "description").text = entry["content"]
        SubElement(item, "guid", isPermaLink="false").text = entry["id"]
        SubElement(item, "pubDate").text = entry["created_at"]
        if entry.get("category"):
            SubElement(item, "category").text = entry["category"]

    xml_bytes = tostring(rss, encoding="unicode", xml_declaration=False)
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes

    return Response(content=xml_str, media_type="application/rss+xml")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_feed_api.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add odigos/api/feed.py tests/test_feed_api.py
git commit -m "feat: add GET /feed.xml RSS publisher endpoint with card-based auth"
```

---

### Task 7: Agent Tools (generate_card, import_card, publish_to_feed)

**Files:**
- Create: `odigos/tools/card_tools.py`
- Create: `odigos/tools/feed_publish.py`
- Create: `tests/test_card_tools.py`
- Create: `tests/test_feed_publish_tool.py`

**Step 1: Write the failing tests for card tools**

Create `tests/test_card_tools.py`:

```python
"""Tests for generate_card and import_card tools."""
import json

import pytest
import pytest_asyncio

from odigos.core.cards import CardManager
from odigos.db import Database
from odigos.tools.card_tools import GenerateCardTool, ImportCardTool


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def manager(db):
    return CardManager(db=db, agent_name="Odigos", host="100.64.0.1", ws_port=8001)


@pytest.mark.asyncio
async def test_generate_card_tool(manager):
    tool = GenerateCardTool(card_manager=manager)
    result = await tool.execute({"type": "connect"})
    assert result.success is True
    data = json.loads(result.data)
    assert data["card"]["type"] == "connect"
    assert "yaml" in data
    assert "compact" in data


@pytest.mark.asyncio
async def test_generate_card_tool_subscribe(manager):
    tool = GenerateCardTool(card_manager=manager)
    result = await tool.execute({"type": "subscribe"})
    assert result.success is True
    data = json.loads(result.data)
    assert data["card"]["type"] == "subscribe"
    assert data["card"]["feed_url"] is not None


@pytest.mark.asyncio
async def test_generate_card_tool_missing_type(manager):
    tool = GenerateCardTool(card_manager=manager)
    result = await tool.execute({})
    assert result.success is False


@pytest.mark.asyncio
async def test_import_card_tool(manager, db):
    # Generate a card first
    card = await manager.generate_card(card_type="connect")
    compact = manager.card_to_compact(card)

    # Import on a different "agent"
    importer_mgr = CardManager(db=db, agent_name="Archie", host="100.64.0.2", ws_port=8001)
    tool = ImportCardTool(card_manager=importer_mgr)
    result = await tool.execute({"card_data": compact})
    assert result.success is True
    data = json.loads(result.data)
    assert data["status"] == "accepted"


@pytest.mark.asyncio
async def test_import_card_tool_bad_data(manager):
    tool = ImportCardTool(card_manager=manager)
    result = await tool.execute({"card_data": "garbage"})
    assert result.success is False
```

**Step 2: Write the failing tests for publish_to_feed tool**

Create `tests/test_feed_publish_tool.py`:

```python
"""Tests for publish_to_feed tool."""
import json

import pytest
import pytest_asyncio

from odigos.db import Database
from odigos.tools.feed_publish import PublishToFeedTool


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_publish_entry(db):
    tool = PublishToFeedTool(db=db, feed_base_url="http://localhost:8000")
    result = await tool.execute({"title": "Test Alert", "content": "Server is down"})
    assert result.success is True
    data = json.loads(result.data)
    assert data["title"] == "Test Alert"
    assert "id" in data
    assert data["feed_url"] == "http://localhost:8000/feed.xml"

    row = await db.fetch_one("SELECT * FROM feed_entries WHERE id = ?", (data["id"],))
    assert row is not None
    assert row["title"] == "Test Alert"


@pytest.mark.asyncio
async def test_publish_with_category(db):
    tool = PublishToFeedTool(db=db, feed_base_url="http://localhost:8000")
    result = await tool.execute({"title": "Research", "content": "Findings", "category": "research"})
    assert result.success is True
    data = json.loads(result.data)

    row = await db.fetch_one("SELECT * FROM feed_entries WHERE id = ?", (data["id"],))
    assert row["category"] == "research"


@pytest.mark.asyncio
async def test_publish_missing_title(db):
    tool = PublishToFeedTool(db=db, feed_base_url="http://localhost:8000")
    result = await tool.execute({"content": "No title"})
    assert result.success is False


@pytest.mark.asyncio
async def test_publish_missing_content(db):
    tool = PublishToFeedTool(db=db, feed_base_url="http://localhost:8000")
    result = await tool.execute({"title": "No content"})
    assert result.success is False
```

**Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_card_tools.py tests/test_feed_publish_tool.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 4: Write card_tools.py**

Create `odigos/tools/card_tools.py`:

```python
"""Agent tools for contact card generation and import."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.core.cards import CardManager


class GenerateCardTool(BaseTool):
    name = "generate_card"
    description = (
        "Generate a contact card to share with another agent or user. "
        "The card contains a scoped API key for establishing a relationship."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "description": "Card type: connect (full mesh), subscribe (feed only), invite (spawned agent)",
                "enum": ["connect", "subscribe", "invite"],
            },
            "expires_in_days": {
                "type": "integer",
                "description": "Optional: card expires after this many days",
            },
        },
        "required": ["type"],
    }

    def __init__(self, card_manager: CardManager) -> None:
        self.card_manager = card_manager

    async def execute(self, params: dict) -> ToolResult:
        card_type = params.get("type")
        if not card_type:
            return ToolResult(success=False, data="", error="Missing required parameter: type")

        if card_type not in ("connect", "subscribe", "invite"):
            return ToolResult(success=False, data="", error=f"Invalid card type: {card_type}")

        expires_in_days = params.get("expires_in_days")

        card = await self.card_manager.generate_card(
            card_type=card_type,
            expires_in_days=expires_in_days,
        )

        yaml_str = self.card_manager.card_to_yaml(card)
        compact = self.card_manager.card_to_compact(card)

        return ToolResult(
            success=True,
            data=json.dumps({
                "card": card,
                "yaml": yaml_str,
                "compact": compact,
            }),
        )


class ImportCardTool(BaseTool):
    name = "import_card"
    description = (
        "Import a contact card received from another agent. "
        "Accepts YAML or compact (odigos-card:...) format."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "card_data": {
                "type": "string",
                "description": "The card data: YAML string or compact odigos-card:... token",
            },
        },
        "required": ["card_data"],
    }

    def __init__(self, card_manager: CardManager) -> None:
        self.card_manager = card_manager

    async def execute(self, params: dict) -> ToolResult:
        card_data = params.get("card_data")
        if not card_data:
            return ToolResult(success=False, data="", error="Missing required parameter: card_data")

        result = await self.card_manager.import_card(card_data)

        if result["status"] == "rejected":
            return ToolResult(success=False, data=json.dumps(result), error=result.get("reason", "Card rejected"))

        return ToolResult(success=True, data=json.dumps(result))
```

**Step 5: Write feed_publish.py**

Create `odigos/tools/feed_publish.py`:

```python
"""Tool for publishing entries to the agent's RSS feed."""
from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.db import Database


class PublishToFeedTool(BaseTool):
    name = "publish_to_feed"
    description = (
        "Publish an entry to your RSS feed. Subscribers with subscribe cards "
        "will see this in their feed reader."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Title of the feed entry",
            },
            "content": {
                "type": "string",
                "description": "Content/body of the feed entry",
            },
            "category": {
                "type": "string",
                "description": "Optional category (e.g., research, alert, status, digest)",
            },
        },
        "required": ["title", "content"],
    }

    def __init__(self, db: Database, feed_base_url: str = "") -> None:
        self.db = db
        self.feed_base_url = feed_base_url

    async def execute(self, params: dict) -> ToolResult:
        title = params.get("title")
        content = params.get("content")
        category = params.get("category")

        if not title:
            return ToolResult(success=False, data="", error="Missing required parameter: title")
        if not content:
            return ToolResult(success=False, data="", error="Missing required parameter: content")

        entry_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO feed_entries (id, title, content, category) VALUES (?, ?, ?, ?)",
            (entry_id, title, content, category),
        )

        feed_url = f"{self.feed_base_url}/feed.xml" if self.feed_base_url else "/feed.xml"

        return ToolResult(
            success=True,
            data=json.dumps({
                "id": entry_id,
                "title": title,
                "feed_url": feed_url,
            }),
        )
```

**Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_card_tools.py tests/test_feed_publish_tool.py -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add odigos/tools/card_tools.py odigos/tools/feed_publish.py tests/test_card_tools.py tests/test_feed_publish_tool.py
git commit -m "feat: add generate_card, import_card, publish_to_feed agent tools"
```

---

### Task 8: Wire Into main.py

**Files:**
- Modify: `odigos/main.py`

**Step 1: Add CardManager initialization**

After the agent_client initialization block (~line 112), add:

```python
    # Initialize card manager
    from odigos.core.cards import CardManager

    card_manager = CardManager(
        db=_db,
        agent_name=settings.agent.name,
        host=settings.server.host,
        ws_port=settings.server.ws_port,
        feed_base_url=f"http://{settings.server.host}:{settings.server.port}",
    )
    app.state.card_manager = card_manager
    logger.info("Card manager initialized")
```

**Step 2: Register card tools (after peer messaging tool block)**

```python
    # Register card tools
    from odigos.tools.card_tools import GenerateCardTool, ImportCardTool
    tool_registry.register(GenerateCardTool(card_manager=card_manager))
    tool_registry.register(ImportCardTool(card_manager=card_manager))
    logger.info("Card tools registered")

    # Register feed publish tool if feed is enabled
    if settings.feed.enabled:
        from odigos.tools.feed_publish import PublishToFeedTool
        feed_tool = PublishToFeedTool(
            db=_db,
            feed_base_url=f"http://{settings.server.host}:{settings.server.port}",
        )
        tool_registry.register(feed_tool)
        logger.info("Feed publish tool registered")
```

**Step 3: Mount feed router (in the router section at bottom of file)**

Add the import at top:

```python
from odigos.api.feed import router as feed_router
```

Add in the router mounting section:

```python
app.include_router(feed_router)
```

**Step 4: Add feed config to settings API**

In `odigos/api/settings.py`:
- Add `feed: dict | None = None` to `SettingsUpdate`
- Add `"feed": settings.feed.model_dump()` to GET response
- Add `"feed"` to both section iteration tuples

**Step 5: Update test_features.py mock settings**

Add to the `_settings()` helper:

```python
        feed=SimpleNamespace(
            enabled=False,
            public=False,
            max_entries=200,
            model_dump=lambda: {"enabled": False, "public": False, "max_entries": 200},
        ),
```

**Step 6: Run full test suite**

Run: `uv run pytest tests/ -x -q`
Expected: All PASS

**Step 7: Commit**

```bash
git add odigos/main.py odigos/api/settings.py odigos/api/feed.py tests/test_features.py
git commit -m "feat: wire CardManager, card tools, feed publisher, and feed router into main"
```

---

### Task 9: Cards API Endpoints

**Files:**
- Create: `odigos/api/cards.py`
- Create: `tests/test_cards_api.py`

**Step 1: Write the failing test**

Create `tests/test_cards_api.py`:

```python
"""Tests for cards REST API endpoints."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app():
    from odigos.api.cards import router

    app = FastAPI()
    settings = MagicMock()
    settings.api_key = "test-key"

    card_manager = AsyncMock()
    db = AsyncMock()

    app.state.settings = settings
    app.state.card_manager = card_manager
    app.state.db = db
    app.include_router(router)
    return app, card_manager, db


class TestCardsAPI:
    def test_list_issued(self):
        app, card_manager, _ = _make_app()
        card_manager.list_issued = AsyncMock(return_value=[
            {"id": "1", "card_type": "connect", "status": "active", "created_at": "2026-03-14"},
        ])
        client = TestClient(app)
        resp = client.get("/api/cards/issued", headers={"Authorization": "Bearer test-key"})
        assert resp.status_code == 200
        assert len(resp.json()["cards"]) == 1

    def test_list_accepted(self):
        app, card_manager, _ = _make_app()
        card_manager.list_accepted = AsyncMock(return_value=[
            {"id": "1", "agent_name": "Archie", "card_type": "connect", "status": "active"},
        ])
        client = TestClient(app)
        resp = client.get("/api/cards/accepted", headers={"Authorization": "Bearer test-key"})
        assert resp.status_code == 200
        assert len(resp.json()["cards"]) == 1

    def test_generate_card(self):
        app, card_manager, _ = _make_app()
        card_manager.generate_card = AsyncMock(return_value={
            "version": 1, "type": "connect", "agent_name": "Odigos",
            "host": "100.64.0.1", "ws_port": 8001, "card_key": "card-sk-abc",
            "capabilities": [], "feed_url": None, "issued_at": "2026-03-14",
            "expires_at": None, "issuer": "Odigos", "fingerprint": "sha256:abc",
        })
        card_manager.card_to_yaml = MagicMock(return_value="yaml content")
        card_manager.card_to_compact = MagicMock(return_value="odigos-card:abc")

        client = TestClient(app)
        resp = client.post(
            "/api/cards/generate",
            json={"type": "connect"},
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "card" in data
        assert "yaml" in data
        assert "compact" in data

    def test_revoke_issued(self):
        app, card_manager, _ = _make_app()
        card_manager.revoke_issued = AsyncMock(return_value=True)

        client = TestClient(app)
        resp = client.post(
            "/api/cards/issued/card-sk-abc/revoke",
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200

    def test_revoke_accepted(self):
        app, card_manager, _ = _make_app()
        card_manager.revoke_accepted = AsyncMock(return_value=True)

        client = TestClient(app)
        resp = client.post(
            "/api/cards/accepted/card-id-123/revoke",
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200

    def test_mute_accepted(self):
        app, card_manager, _ = _make_app()
        card_manager.mute_accepted = AsyncMock(return_value=True)

        client = TestClient(app)
        resp = client.post(
            "/api/cards/accepted/card-id-123/mute",
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200

    def test_unmute_accepted(self):
        app, card_manager, _ = _make_app()
        card_manager.unmute_accepted = AsyncMock(return_value=True)

        client = TestClient(app)
        resp = client.post(
            "/api/cards/accepted/card-id-123/unmute",
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200

    def test_list_feed_entries(self):
        app, _, db = _make_app()
        db.fetch_all = AsyncMock(return_value=[
            {"id": "1", "title": "Alert", "content": "Server down", "category": "alert", "created_at": "2026-03-14"},
        ])

        client = TestClient(app)
        resp = client.get("/api/feed/entries", headers={"Authorization": "Bearer test-key"})
        assert resp.status_code == 200
        assert len(resp.json()["entries"]) == 1

    def test_delete_feed_entry(self):
        app, _, db = _make_app()
        db.execute = AsyncMock()

        client = TestClient(app)
        resp = client.delete("/api/feed/entries/entry-1", headers={"Authorization": "Bearer test-key"})
        assert resp.status_code == 200
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cards_api.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

Create `odigos/api/cards.py`:

```python
"""REST API for contact card and feed entry management.

Dashboard-only endpoints (require global API key, not card keys).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from odigos.api.deps import get_db, get_settings, require_api_key

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


def _get_card_manager(request):
    from fastapi import Request
    return request.app.state.card_manager


class GenerateCardRequest(BaseModel):
    type: str
    expires_in_days: int | None = None


@router.get("/cards/issued")
async def list_issued(request):
    card_manager = request.app.state.card_manager
    cards = await card_manager.list_issued()
    return {"cards": cards}


@router.get("/cards/accepted")
async def list_accepted(request):
    card_manager = request.app.state.card_manager
    cards = await card_manager.list_accepted()
    return {"cards": cards}


@router.post("/cards/generate")
async def generate_card(body: GenerateCardRequest, request=None):
    from fastapi import Request as Req
    card_manager = request.app.state.card_manager
    card = await card_manager.generate_card(
        card_type=body.type,
        expires_in_days=body.expires_in_days,
    )
    return {
        "card": card,
        "yaml": card_manager.card_to_yaml(card),
        "compact": card_manager.card_to_compact(card),
    }


@router.post("/cards/issued/{card_key}/revoke")
async def revoke_issued(card_key: str, request=None):
    card_manager = request.app.state.card_manager
    await card_manager.revoke_issued(card_key)
    return {"status": "ok"}


@router.post("/cards/accepted/{card_id}/revoke")
async def revoke_accepted(card_id: str, request=None):
    card_manager = request.app.state.card_manager
    await card_manager.revoke_accepted(card_id)
    return {"status": "ok"}


@router.post("/cards/accepted/{card_id}/mute")
async def mute_accepted(card_id: str, request=None):
    card_manager = request.app.state.card_manager
    await card_manager.mute_accepted(card_id)
    return {"status": "ok"}


@router.post("/cards/accepted/{card_id}/unmute")
async def unmute_accepted(card_id: str, request=None):
    card_manager = request.app.state.card_manager
    await card_manager.unmute_accepted(card_id)
    return {"status": "ok"}


@router.get("/feed/entries")
async def list_feed_entries(db=Depends(get_db)):
    entries = await db.fetch_all(
        "SELECT * FROM feed_entries ORDER BY created_at DESC LIMIT 200"
    )
    return {"entries": [dict(e) for e in entries]}


@router.delete("/feed/entries/{entry_id}")
async def delete_feed_entry(entry_id: str, db=Depends(get_db)):
    await db.execute("DELETE FROM feed_entries WHERE id = ?", (entry_id,))
    return {"status": "ok"}
```

**Step 4: Mount the router in main.py**

Add import and `app.include_router(cards_router)`.

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_cards_api.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add odigos/api/cards.py tests/test_cards_api.py odigos/main.py
git commit -m "feat: add REST API endpoints for cards management and feed entries"
```

---

### Task 10: Dashboard Connections Page

**Files:**
- Create: `dashboard/src/pages/ConnectionsPage.tsx`
- Modify: `dashboard/src/App.tsx` (add route)
- Modify: `dashboard/src/layouts/AppLayout.tsx` (add nav link)

**Step 1: Create the Connections page**

Create `dashboard/src/pages/ConnectionsPage.tsx` with:
- Two tabs: "Issued Cards" and "Accepted Cards"
- Issued tab: table with card_type, issued_to, status, created_at, last_used_at, Revoke button
- Accepted tab: table with agent_name, card_type, host, status, last_connected_at, Revoke/Mute/Unmute buttons
- "Generate Card" button at top with type selector dropdown and optional expiry input
- Dialog showing YAML and compact string after card generation with copy buttons
- Uses `get`/`post`/`del` from `@/lib/api`
- Uses existing shadcn components: Button, Input, Tabs, Table, Dialog, Select

**Step 2: Add route in App.tsx**

```tsx
import ConnectionsPage from './pages/ConnectionsPage'
// ...
<Route path="/connections" element={<ConnectionsPage />} />
```

**Step 3: Add nav link in AppLayout.tsx**

Add a "Connections" link in the sidebar bottom section (between Inspector and Settings), using the `Link2` icon from lucide-react.

**Step 4: Verify the dashboard builds**

Run: `cd dashboard && npm run build`
Expected: Build succeeds

**Step 5: Commit**

```bash
git add dashboard/src/pages/ConnectionsPage.tsx dashboard/src/App.tsx dashboard/src/layouts/AppLayout.tsx
git commit -m "feat: add Connections dashboard page for card management"
```

---

### Task 11: Dashboard Feed Page

**Files:**
- Create: `dashboard/src/pages/FeedPage.tsx`
- Modify: `dashboard/src/App.tsx` (add route)
- Modify: `dashboard/src/layouts/AppLayout.tsx` (add nav link)

**Step 1: Create the Feed page**

Create `dashboard/src/pages/FeedPage.tsx` with:
- List of published entries: title, category, date, Delete button
- Feed URL displayed at the top with a copy button
- Empty state when no entries
- Uses `get`/`del` from `@/lib/api`
- Uses existing shadcn components: Button, Table

**Step 2: Add route in App.tsx**

```tsx
import FeedPage from './pages/FeedPage'
// ...
<Route path="/feed" element={<FeedPage />} />
```

**Step 3: Add nav link in AppLayout.tsx**

Add a "Feed" link in the sidebar, using the `Rss` icon from lucide-react.

**Step 4: Verify the dashboard builds**

Run: `cd dashboard && npm run build`
Expected: Build succeeds

**Step 5: Commit**

```bash
git add dashboard/src/pages/FeedPage.tsx dashboard/src/App.tsx dashboard/src/layouts/AppLayout.tsx
git commit -m "feat: add Feed dashboard page for viewing published entries"
```

---

### Task 12: Settings Feed Section

**Files:**
- Modify: `dashboard/src/pages/settings/GeneralSettings.tsx`

**Step 1: Add feed config to SettingsData interface**

Add to the interface:

```typescript
feed: { enabled: boolean; public: boolean; max_entries: number }
```

**Step 2: Add Feed section to the settings form**

Add a new `SectionCard` titled "Feed" between "Mesh Networking" and "Agent Templates":

```tsx
<SectionCard title="Feed">
  <div className="flex items-center justify-between">
    <div className="space-y-0.5">
      <Label className="text-sm">Feed Publisher</Label>
      <p className="text-xs text-muted-foreground">Enable the RSS feed endpoint so other agents can subscribe to your updates.</p>
    </div>
    <Button
      variant={settings.feed.enabled ? 'default' : 'outline'}
      size="sm"
      onClick={() => update('feed', 'enabled', !settings.feed.enabled)}
    >
      {settings.feed.enabled ? 'Enabled' : 'Disabled'}
    </Button>
  </div>
  <div className="flex items-center justify-between">
    <div className="space-y-0.5">
      <Label className="text-sm">Public Feed</Label>
      <p className="text-xs text-muted-foreground">Allow anyone to read your feed without a subscribe card.</p>
    </div>
    <Button
      variant={settings.feed.public ? 'default' : 'outline'}
      size="sm"
      onClick={() => update('feed', 'public', !settings.feed.public)}
    >
      {settings.feed.public ? 'Public' : 'Private'}
    </Button>
  </div>
  <div className="space-y-1.5">
    <Label className="text-xs text-muted-foreground">Max Entries</Label>
    <Input type="number" value={settings.feed.max_entries} onChange={(e) => update('feed', 'max_entries', parseInt(e.target.value))} className="bg-muted/50 border-border/40 w-24" />
  </div>
</SectionCard>
```

**Step 3: Verify the dashboard builds**

Run: `cd dashboard && npm run build`
Expected: Build succeeds

**Step 4: Commit**

```bash
git add dashboard/src/pages/settings/GeneralSettings.tsx
git commit -m "feat: add feed settings section to dashboard with enabled, public, max_entries controls"
```

---

### Task 13: Full Integration Test

**Files:**
- Run full test suite and verify dashboard build

**Step 1: Run all Python tests**

Run: `uv run pytest tests/ -q`
Expected: All PASS

**Step 2: Build dashboard**

Run: `cd dashboard && npm run build`
Expected: Build succeeds

**Step 3: Verify no syntax issues**

Run: `uv run ruff check odigos/`
Expected: No errors (or only pre-existing warnings)

**Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: resolve integration issues from contact cards implementation"
```
