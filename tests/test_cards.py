"""Tests for contact card generation, import, validation, and revocation."""
import uuid

import pytest
import pytest_asyncio
import yaml

from odigos.core.cards import CardManager
from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path):
    d = Database(tmp_db_path, migrations_dir="migrations")
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
    assert "fingerprint" in result["reason"].lower()


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

    # Import with a different agent to avoid self-import rejection
    importer = CardManager(db=manager.db, agent_name="Archie", host="100.64.0.2", ws_port=8001)
    await importer.import_card(yaml_str)

    accepted = await manager.db.fetch_one(
        "SELECT * FROM accepted_cards WHERE agent_name = 'Odigos'"
    )
    await importer.revoke_accepted(accepted["id"])

    row = await manager.db.fetch_one(
        "SELECT * FROM accepted_cards WHERE id = ?", (accepted["id"],)
    )
    assert row["status"] == "revoked"


@pytest.mark.asyncio
async def test_mute_accepted_card(manager):
    card = await manager.generate_card(card_type="connect")
    yaml_str = manager.card_to_yaml(card)

    importer = CardManager(db=manager.db, agent_name="Archie", host="100.64.0.2", ws_port=8001)
    await importer.import_card(yaml_str)

    accepted = await manager.db.fetch_one(
        "SELECT * FROM accepted_cards WHERE agent_name = 'Odigos'"
    )
    await importer.mute_accepted(accepted["id"])

    row = await manager.db.fetch_one(
        "SELECT * FROM accepted_cards WHERE id = ?", (accepted["id"],)
    )
    assert row["status"] == "muted"


@pytest.mark.asyncio
async def test_unmute_accepted_card(manager):
    card = await manager.generate_card(card_type="connect")
    yaml_str = manager.card_to_yaml(card)

    importer = CardManager(db=manager.db, agent_name="Archie", host="100.64.0.2", ws_port=8001)
    await importer.import_card(yaml_str)

    accepted = await manager.db.fetch_one(
        "SELECT * FROM accepted_cards WHERE agent_name = 'Odigos'"
    )
    await importer.mute_accepted(accepted["id"])
    await importer.unmute_accepted(accepted["id"])

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
