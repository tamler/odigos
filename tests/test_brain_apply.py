"""Tests for brain compilation manifest application."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


class TestApplyManifest:
    async def test_create_writes_file(self, tmp_path):
        from odigos.core.brain_apply import apply_compilation

        brain_dir = tmp_path / "brain"
        brain_dir.mkdir()

        manifest = json.dumps({
            "operations": [
                {
                    "op": "create",
                    "path": "concepts/deployment.md",
                    "content": "---\ntype: concept\ntitle: Deployment\n---\n\n# Deployment\n\nOverview here.",
                },
            ],
            "new_concepts": ["deployment"],
            "updated_articles": [],
            "archived": [],
            "cross_links_added": 0,
            "summary": "Created deployment concept.",
        })

        stats = await apply_compilation(manifest, brain_dir=str(brain_dir))
        assert stats["created"] == 1
        assert stats["errors"] == []

        created = brain_dir / "concepts" / "deployment.md"
        assert created.exists()
        assert "Deployment" in created.read_text()

    async def test_update_overwrites_file(self, tmp_path):
        from odigos.core.brain_apply import apply_compilation

        brain_dir = tmp_path / "brain"
        entities_dir = brain_dir / "entities"
        entities_dir.mkdir(parents=True)
        (entities_dir / "rachel.md").write_text("# Rachel\n\nOld content.")

        manifest = json.dumps({
            "operations": [
                {
                    "op": "update",
                    "path": "entities/rachel.md",
                    "content": "---\ntype: entity\ncompiled_at: 2026-04-10T12:00:00Z\n---\n\n# Rachel\n\nEnriched content.",
                },
            ],
            "new_concepts": [],
            "updated_articles": ["rachel"],
            "archived": [],
            "cross_links_added": 0,
            "summary": "Updated rachel.",
        })

        stats = await apply_compilation(manifest, brain_dir=str(brain_dir))
        assert stats["updated"] == 1

        content = (entities_dir / "rachel.md").read_text()
        assert "Enriched content" in content
        assert "Old content" not in content

    async def test_archive_moves_file(self, tmp_path):
        from odigos.core.brain_apply import apply_compilation

        brain_dir = tmp_path / "brain"
        concepts_dir = brain_dir / "concepts"
        concepts_dir.mkdir(parents=True)
        (concepts_dir / "old-topic.md").write_text("# Old Topic\n\nStale.")

        manifest = json.dumps({
            "operations": [
                {
                    "op": "archive",
                    "path": "concepts/old-topic.md",
                    "reason": "All source facts superseded",
                },
            ],
            "new_concepts": [],
            "updated_articles": [],
            "archived": ["old-topic"],
            "cross_links_added": 0,
            "summary": "Archived old-topic.",
        })

        stats = await apply_compilation(manifest, brain_dir=str(brain_dir))
        assert stats["archived"] == 1

        # Original should be gone
        assert not (concepts_dir / "old-topic.md").exists()
        # Archive should exist
        archived = brain_dir / "archive" / "concepts" / "old-topic.md"
        assert archived.exists()
        assert "archived_at" in archived.read_text().lower() or "archive_reason" in archived.read_text().lower()

    async def test_rejects_path_outside_brain(self, tmp_path):
        from odigos.core.brain_apply import apply_compilation

        brain_dir = tmp_path / "brain"
        brain_dir.mkdir()

        manifest = json.dumps({
            "operations": [
                {"op": "create", "path": "../../../etc/passwd", "content": "evil"},
            ],
            "new_concepts": [],
            "updated_articles": [],
            "archived": [],
            "cross_links_added": 0,
            "summary": "Evil.",
        })

        stats = await apply_compilation(manifest, brain_dir=str(brain_dir))
        assert stats["created"] == 0
        assert len(stats["errors"]) == 1
        assert "path" in stats["errors"][0].lower()

    async def test_operations_applied_in_dependency_order(self, tmp_path):
        """Creates come before updates, updates before archives."""
        from odigos.core.brain_apply import apply_compilation

        brain_dir = tmp_path / "brain"
        concepts_dir = brain_dir / "concepts"
        concepts_dir.mkdir(parents=True)
        (concepts_dir / "existing.md").write_text("# Existing\n\nOld.")

        manifest = json.dumps({
            "operations": [
                # Intentionally out of order
                {"op": "archive", "path": "concepts/existing.md", "reason": "stale"},
                {"op": "create", "path": "concepts/new-topic.md", "content": "# New\n\nFresh."},
                {"op": "update", "path": "concepts/new-topic.md", "content": "# New\n\nFresh + link to existing."},
            ],
            "new_concepts": ["new-topic"],
            "updated_articles": ["new-topic"],
            "archived": ["existing"],
            "cross_links_added": 1,
            "summary": "Test ordering.",
        })

        stats = await apply_compilation(manifest, brain_dir=str(brain_dir))
        # All three should succeed because creates come first
        assert stats["created"] == 1
        assert stats["updated"] == 1
        assert stats["archived"] == 1

        # new-topic should have the update content (not the create content)
        content = (concepts_dir / "new-topic.md").read_text()
        assert "link to existing" in content
