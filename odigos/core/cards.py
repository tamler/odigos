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
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
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
        if row.get("expires_at"):
            try:
                exp = datetime.fromisoformat(row["expires_at"])
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
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

        return row

    async def revoke_issued(self, card_key: str) -> None:
        """Revoke a card this agent issued."""
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            "UPDATE contact_cards SET status = 'revoked', revoked_at = ? "
            "WHERE card_key = ? AND status = 'active'",
            (now, card_key),
        )

    async def revoke_accepted(self, card_id: str) -> None:
        """Revoke an accepted card (cut ties with a peer)."""
        await self.db.execute(
            "UPDATE accepted_cards SET status = 'revoked' WHERE id = ? AND status IN ('active', 'muted')",
            (card_id,),
        )

    async def mute_accepted(self, card_id: str) -> None:
        """Mute an accepted card (silence a noisy peer)."""
        await self.db.execute(
            "UPDATE accepted_cards SET status = 'muted' WHERE id = ? AND status = 'active'",
            (card_id,),
        )

    async def unmute_accepted(self, card_id: str) -> None:
        """Unmute a previously muted card."""
        await self.db.execute(
            "UPDATE accepted_cards SET status = 'active' WHERE id = ? AND status = 'muted'",
            (card_id,),
        )

    async def list_issued(self) -> list[dict]:
        """List all cards this agent has issued."""
        return await self.db.fetch_all(
            "SELECT * FROM contact_cards ORDER BY created_at DESC"
        )

    async def list_accepted(self) -> list[dict]:
        """List all cards this agent has imported."""
        return await self.db.fetch_all(
            "SELECT * FROM accepted_cards ORDER BY accepted_at DESC"
        )
