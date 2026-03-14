"""Tests for AgentTemplateIndex -- dynamic GitHub template indexing and caching."""
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest
import pytest_asyncio

from odigos.core.template_index import (
    AgentTemplateIndex,
    _parse_agent_name,
    _tokenize,
)
from odigos.db import Database


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def template_index(db):
    idx = AgentTemplateIndex(db=db)
    return idx


# --- Unit tests for helpers ---


def test_parse_agent_name_standard():
    assert _parse_agent_name("engineering-backend-architect.md") == "backend architect"


def test_parse_agent_name_no_prefix():
    assert _parse_agent_name("standalone.md") == "standalone"


def test_parse_agent_name_deep_hyphen():
    assert _parse_agent_name("design-ux-researcher.md") == "ux researcher"


def test_tokenize():
    tokens = _tokenize("Backend Architect DevOps")
    assert tokens == {"backend", "architect", "devops"}


def test_tokenize_empty():
    assert _tokenize("") == set()


# --- GitHub tree response mock ---

_MOCK_TREE = {
    "tree": [
        {"path": "README.md", "type": "blob"},
        {"path": "engineering", "type": "tree"},
        {"path": "engineering/engineering-backend-architect.md", "type": "blob"},
        {"path": "engineering/engineering-frontend-developer.md", "type": "blob"},
        {"path": "design/design-ux-researcher.md", "type": "blob"},
        {"path": "marketing/marketing-seo-specialist.md", "type": "blob"},
        {"path": "examples/workflow-landing-page.md", "type": "blob"},  # not an agent dir
        {"path": "game-development/blender/blender-addon-engineer.md", "type": "blob"},
    ]
}


def _mock_tree_response():
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = _MOCK_TREE
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_refresh_index_populates_db(template_index):
    """refresh_index should insert templates from agent directories only."""
    with patch.object(template_index._http, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _mock_tree_response()

        count = await template_index.refresh_index(force=True)

    # Should have 5 agent files (excludes README.md and examples/)
    assert count == 5
    rows = await template_index.db.fetch_all("SELECT * FROM agent_templates ORDER BY name")
    assert len(rows) == 5
    names = {r["name"] for r in rows}
    assert "backend architect" in names
    assert "frontend developer" in names
    assert "ux researcher" in names
    assert "seo specialist" in names
    assert "addon engineer" in names


@pytest.mark.asyncio
async def test_refresh_index_skips_if_recent(template_index):
    """Should not re-fetch if index was refreshed recently."""
    template_index._index_refreshed_at = datetime.now(timezone.utc)

    with patch.object(template_index._http, "get", new_callable=AsyncMock) as mock_get:
        count = await template_index.refresh_index()

    assert count == 0
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_index_removes_deleted(template_index):
    """Templates removed from repo should be deleted from the index."""
    with patch.object(template_index._http, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _mock_tree_response()
        await template_index.refresh_index(force=True)

    # Now refresh with a tree missing one file
    smaller_tree = {
        "tree": [
            {"path": "engineering/engineering-backend-architect.md", "type": "blob"},
        ]
    }
    smaller_resp = MagicMock(spec=httpx.Response)
    smaller_resp.json.return_value = smaller_tree
    smaller_resp.raise_for_status = MagicMock()

    with patch.object(template_index._http, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = smaller_resp
        await template_index.refresh_index(force=True)

    rows = await template_index.db.fetch_all("SELECT * FROM agent_templates")
    assert len(rows) == 1
    assert rows[0]["name"] == "backend architect"


@pytest.mark.asyncio
async def test_refresh_index_handles_github_failure(template_index):
    """Should gracefully return 0 if GitHub API fails."""
    with patch.object(template_index._http, "get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.HTTPError("rate limited")

        count = await template_index.refresh_index(force=True)

    assert count == 0


@pytest.mark.asyncio
async def test_match_template_keyword_overlap(template_index):
    """Should match based on keyword overlap between query and template name."""
    with patch.object(template_index._http, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _mock_tree_response()
        await template_index.refresh_index(force=True)

    match = await template_index.match_template(role="backend architect", specialty="api design")
    assert match is not None
    assert "backend" in match["name"]


@pytest.mark.asyncio
async def test_match_template_no_match(template_index):
    """Should return None when no keywords overlap."""
    with patch.object(template_index._http, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _mock_tree_response()
        await template_index.refresh_index(force=True)

    match = await template_index.match_template(role="quantum physicist", specialty="entanglement")
    assert match is None


@pytest.mark.asyncio
async def test_match_template_empty_index(template_index):
    """Should return None when the index is empty."""
    with patch.object(template_index, "refresh_index", new_callable=AsyncMock):
        match = await template_index.match_template(role="developer")
    assert match is None


@pytest.mark.asyncio
async def test_fetch_template_from_github(template_index):
    """Should fetch raw content from GitHub and cache it."""
    # Insert a template entry
    await template_index.db.execute(
        "INSERT INTO agent_templates (name, division, github_path) VALUES (?, ?, ?)",
        ("backend architect", "engineering", "engineering/engineering-backend-architect.md"),
    )

    template_content = "# Backend Architect\nYou are a backend architect..."

    raw_resp = MagicMock(spec=httpx.Response)
    raw_resp.text = template_content
    raw_resp.raise_for_status = MagicMock()

    with patch.object(template_index._http, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = raw_resp
        content = await template_index.fetch_template("engineering/engineering-backend-architect.md")

    assert content == template_content

    # Verify it was cached
    row = await template_index.db.fetch_one(
        "SELECT cached_content, cached_at FROM agent_templates WHERE github_path = ?",
        ("engineering/engineering-backend-architect.md",),
    )
    assert row["cached_content"] == template_content
    assert row["cached_at"] is not None


@pytest.mark.asyncio
async def test_fetch_template_uses_cache(template_index):
    """Should return cached content when it's fresh enough."""
    now = datetime.now(timezone.utc).isoformat()
    await template_index.db.execute(
        "INSERT INTO agent_templates (name, division, github_path, cached_content, cached_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("backend architect", "engineering", "engineering/engineering-backend-architect.md",
         "cached content here", now),
    )

    with patch.object(template_index._http, "get", new_callable=AsyncMock) as mock_get:
        content = await template_index.fetch_template("engineering/engineering-backend-architect.md")

    assert content == "cached content here"
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_template_refreshes_stale_cache(template_index):
    """Should re-fetch when cache is older than TTL."""
    old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    await template_index.db.execute(
        "INSERT INTO agent_templates (name, division, github_path, cached_content, cached_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("backend architect", "engineering", "engineering/engineering-backend-architect.md",
         "old content", old_time),
    )

    raw_resp = MagicMock(spec=httpx.Response)
    raw_resp.text = "new content from github"
    raw_resp.raise_for_status = MagicMock()

    with patch.object(template_index._http, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = raw_resp
        content = await template_index.fetch_template("engineering/engineering-backend-architect.md")

    assert content == "new content from github"


@pytest.mark.asyncio
async def test_fetch_template_fallback_to_stale_cache(template_index):
    """Should return stale cache when GitHub fetch fails."""
    old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    await template_index.db.execute(
        "INSERT INTO agent_templates (name, division, github_path, cached_content, cached_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("backend architect", "engineering", "engineering/engineering-backend-architect.md",
         "stale but usable", old_time),
    )

    with patch.object(template_index._http, "get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.HTTPError("network down")
        content = await template_index.fetch_template("engineering/engineering-backend-architect.md")

    assert content == "stale but usable"


@pytest.mark.asyncio
async def test_fetch_template_no_cache_no_github(template_index):
    """Should return None when there's no cache and GitHub fails."""
    await template_index.db.execute(
        "INSERT INTO agent_templates (name, division, github_path) VALUES (?, ?, ?)",
        ("backend architect", "engineering", "engineering/engineering-backend-architect.md"),
    )

    with patch.object(template_index._http, "get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.HTTPError("network down")
        content = await template_index.fetch_template("engineering/engineering-backend-architect.md")

    assert content is None


@pytest.mark.asyncio
async def test_list_templates(template_index):
    """Should list all templates or filter by division."""
    with patch.object(template_index._http, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _mock_tree_response()
        await template_index.refresh_index(force=True)

    all_templates = await template_index.list_templates()
    assert len(all_templates) == 5

    eng_templates = await template_index.list_templates(division="engineering")
    assert len(eng_templates) == 2
    assert all(t["division"] == "engineering" for t in eng_templates)


# --- Custom template tests ---


@pytest.mark.asyncio
async def test_create_custom_template(template_index):
    """Should create a custom template stored locally."""
    content = "# Philosopher Agent\nYou contemplate the nature of code."
    tid = await template_index.create_custom_template(
        name="Philosopher",
        content=content,
        division="custom",
    )
    assert tid > 0

    row = await template_index.db.fetch_one(
        "SELECT * FROM agent_templates WHERE id = ?", (tid,),
    )
    assert row["name"] == "Philosopher"
    assert row["division"] == "custom"
    assert row["github_path"].startswith("custom:")
    assert row["cached_content"] == content


@pytest.mark.asyncio
async def test_create_custom_template_upsert(template_index):
    """Should update if a custom template with the same path already exists."""
    tid1 = await template_index.create_custom_template(
        name="Philosopher", content="v1", division="custom",
    )
    tid2 = await template_index.create_custom_template(
        name="Philosopher", content="v2", division="custom",
    )
    assert tid1 == tid2

    row = await template_index.db.fetch_one(
        "SELECT cached_content FROM agent_templates WHERE id = ?", (tid1,),
    )
    assert row["cached_content"] == "v2"


@pytest.mark.asyncio
async def test_delete_custom_template(template_index):
    """Should delete custom templates but refuse to delete GitHub ones."""
    tid = await template_index.create_custom_template(
        name="Deletable", content="bye", division="custom",
    )
    assert await template_index.delete_custom_template(tid) is True

    row = await template_index.db.fetch_one(
        "SELECT * FROM agent_templates WHERE id = ?", (tid,),
    )
    assert row is None


@pytest.mark.asyncio
async def test_delete_github_template_refused(template_index):
    """Should refuse to delete GitHub-sourced templates."""
    await template_index.db.execute(
        "INSERT INTO agent_templates (name, division, github_path) VALUES (?, ?, ?)",
        ("backend architect", "engineering", "engineering/engineering-backend-architect.md"),
    )
    row = await template_index.db.fetch_one(
        "SELECT id FROM agent_templates WHERE name = ?", ("backend architect",),
    )
    assert await template_index.delete_custom_template(row["id"]) is False


@pytest.mark.asyncio
async def test_fetch_custom_template(template_index):
    """Custom templates should be served from cache, not GitHub."""
    await template_index.create_custom_template(
        name="Finance Specialist", content="You analyze markets.", division="finance",
    )

    with patch.object(template_index._http, "get", new_callable=AsyncMock) as mock_get:
        content = await template_index.fetch_template("custom:finance/finance-specialist.md")

    assert content == "You analyze markets."
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_custom_templates_survive_refresh(template_index):
    """Custom templates should not be pruned when GitHub index refreshes."""
    await template_index.create_custom_template(
        name="Philosopher", content="I think therefore I am", division="custom",
    )

    # Refresh with a tree that has no custom templates
    with patch.object(template_index._http, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _mock_tree_response()
        await template_index.refresh_index(force=True)

    # Custom template should still exist
    row = await template_index.db.fetch_one(
        "SELECT * FROM agent_templates WHERE github_path LIKE 'custom:%'",
    )
    assert row is not None
    assert row["name"] == "Philosopher"


@pytest.mark.asyncio
async def test_match_includes_custom_templates(template_index):
    """match_template should consider custom templates alongside GitHub ones."""
    await template_index.create_custom_template(
        name="philosopher thinker", content="Deep thoughts", division="custom",
    )

    with patch.object(template_index, "refresh_index", new_callable=AsyncMock):
        match = await template_index.match_template(role="philosopher", specialty="ethics")

    assert match is not None
    assert "philosopher" in match["name"]
