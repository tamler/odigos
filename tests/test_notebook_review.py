"""Tests for notebook review heartbeat phase."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from odigos.db import Database


def _make_llm_response(content: str):
    from odigos.providers.base import LLMResponse
    return LLMResponse(
        content=content, model="test/model",
        tokens_in=100, tokens_out=200, cost_usd=0.001,
    )


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


async def _seed_shared_notebook(db, title: str = "Journal", content: str = "My entry") -> str:
    nb_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO notebooks (id, title, share_with_agent, created_at, updated_at) "
        "VALUES (?, ?, 1, datetime('now'), datetime('now'))",
        (nb_id, title),
    )
    entry_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO notebook_entries (id, notebook_id, content, entry_type, created_at, updated_at) "
        "VALUES (?, ?, ?, 'user', datetime('now'), datetime('now'))",
        (entry_id, nb_id, content),
    )
    return nb_id


def _make_hb(db, llm_response, tmp_path: Path):
    hb = MagicMock()
    hb.db = db
    hb.llm_provider = AsyncMock()
    hb.llm_provider.complete = AsyncMock(return_value=llm_response)
    hb.background_model = "test/model"
    hb.current_phase = None
    hb.current_activity = None
    hb.notifier = MagicMock()
    hb.notifier.create = AsyncMock()
    hb.message_bus = MagicMock()
    hb.message_bus.publish = AsyncMock()
    return hb


class TestReviewGating:
    async def test_skips_short_notebook(self, db, tmp_path, monkeypatch):
        from odigos.api import notebooks as nb_module
        monkeypatch.setattr(nb_module, "BACKUP_DIR", tmp_path)
        from odigos.core.heartbeat import notes_review

        # 100 chars, well under MIN_CONTENT_CHARS
        await _seed_shared_notebook(db, content="Too short to review")
        hb = _make_hb(db, _make_llm_response('{"observations":[]}'), tmp_path)

        reviewed = await notes_review.review_notebooks(hb)
        assert reviewed == 0
        hb.llm_provider.complete.assert_not_called()

    async def test_skips_non_shared_notebook(self, db, tmp_path, monkeypatch):
        from odigos.api import notebooks as nb_module
        monkeypatch.setattr(nb_module, "BACKUP_DIR", tmp_path)
        from odigos.core.heartbeat import notes_review

        # Create a non-shared notebook with lots of content
        nb_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO notebooks (id, title, share_with_agent, created_at, updated_at) "
            "VALUES (?, ?, 0, datetime('now'), datetime('now'))",
            (nb_id, "Private"),
        )
        await db.execute(
            "INSERT INTO notebook_entries (id, notebook_id, content, entry_type, created_at, updated_at) "
            "VALUES (?, ?, ?, 'user', datetime('now'), datetime('now'))",
            (str(uuid.uuid4()), nb_id, "A" * 1000),
        )

        hb = _make_hb(db, _make_llm_response('{"observations":[]}'), tmp_path)
        reviewed = await notes_review.review_notebooks(hb)
        assert reviewed == 0

    async def test_skips_recently_reviewed(self, db, tmp_path, monkeypatch):
        from odigos.api import notebooks as nb_module
        monkeypatch.setattr(nb_module, "BACKUP_DIR", tmp_path)
        from odigos.core.heartbeat import notes_review

        nb_id = await _seed_shared_notebook(db, content="A" * 1000)
        await db.execute(
            "UPDATE notebooks SET last_reviewed_at = datetime('now') WHERE id = ?",
            (nb_id,),
        )

        hb = _make_hb(db, _make_llm_response('{"observations":[]}'), tmp_path)
        reviewed = await notes_review.review_notebooks(hb)
        assert reviewed == 0

    async def test_skips_notebook_with_max_notes(self, db, tmp_path, monkeypatch):
        from odigos.api import notebooks as nb_module
        monkeypatch.setattr(nb_module, "BACKUP_DIR", tmp_path)
        from odigos.core.heartbeat import notes_review

        nb_id = await _seed_shared_notebook(db, content="A" * 1000)
        for i in range(10):
            await db.execute(
                "INSERT INTO notebook_entries "
                "(id, notebook_id, content, entry_type, status, trigger_type, created_at, updated_at) "
                "VALUES (?, ?, ?, 'agent', 'active', 'heartbeat', datetime('now'), datetime('now'))",
                (str(uuid.uuid4()), nb_id, f"Note {i}"),
            )

        hb = _make_hb(db, _make_llm_response('{"observations":[]}'), tmp_path)
        reviewed = await notes_review.review_notebooks(hb)
        assert reviewed == 0


class TestReviewExecution:
    async def test_review_inserts_entries_and_updates_timestamp(
        self, db, tmp_path, monkeypatch
    ):
        from odigos.api import notebooks as nb_module
        monkeypatch.setattr(nb_module, "BACKUP_DIR", tmp_path)
        from odigos.core.heartbeat import notes_review

        content = "I am really struggling with the deployment process. " * 20
        nb_id = await _seed_shared_notebook(db, content=content)

        response = json.dumps({
            "observations": [
                {
                    "quote": "struggling with the deployment",
                    "comment": "You've mentioned this before — consider breaking it down into smaller steps.",
                }
            ]
        })
        hb = _make_hb(db, _make_llm_response(response), tmp_path)

        reviewed = await notes_review.review_notebooks(hb)
        assert reviewed == 1

        # Agent entry was created
        rows = await db.fetch_all(
            "SELECT * FROM notebook_entries WHERE notebook_id = ? AND entry_type = 'agent'",
            (nb_id,),
        )
        assert len(rows) == 1
        assert "smaller steps" in rows[0]["content"]
        assert rows[0]["quote"] == "struggling with the deployment"
        assert rows[0]["trigger_type"] == "heartbeat"

        # last_reviewed_at was updated
        nb_row = await db.fetch_one(
            "SELECT last_reviewed_at FROM notebooks WHERE id = ?", (nb_id,),
        )
        assert nb_row["last_reviewed_at"] is not None

    async def test_review_skips_hallucinated_quotes(
        self, db, tmp_path, monkeypatch
    ):
        from odigos.api import notebooks as nb_module
        monkeypatch.setattr(nb_module, "BACKUP_DIR", tmp_path)
        from odigos.core.heartbeat import notes_review

        content = "A real sentence in the notebook. " * 30
        nb_id = await _seed_shared_notebook(db, content=content)

        response = json.dumps({
            "observations": [
                {
                    "quote": "This text is not in the notebook at all",
                    "comment": "Hallucinated comment.",
                },
                {
                    "quote": "A real sentence",
                    "comment": "Valid comment.",
                },
            ]
        })
        hb = _make_hb(db, _make_llm_response(response), tmp_path)

        await notes_review.review_notebooks(hb)

        rows = await db.fetch_all(
            "SELECT * FROM notebook_entries WHERE notebook_id = ? AND entry_type = 'agent'",
            (nb_id,),
        )
        assert len(rows) == 1  # Only the valid one inserted
        assert "Valid comment" in rows[0]["content"]

    async def test_review_marks_stale_quotes(self, db, tmp_path, monkeypatch):
        from odigos.api import notebooks as nb_module
        monkeypatch.setattr(nb_module, "BACKUP_DIR", tmp_path)
        from odigos.core.heartbeat import notes_review

        content = "Current notebook content that says nothing important. " * 20
        nb_id = await _seed_shared_notebook(db, content=content)

        # Pre-seed an existing agent note with a quote that's NOT in the current content
        stale_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO notebook_entries "
            "(id, notebook_id, content, entry_type, trigger_type, quote, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'agent', 'heartbeat', ?, 'active', datetime('now'), datetime('now'))",
            (stale_id, nb_id, "Old observation", "this text is gone now"),
        )

        hb = _make_hb(db, _make_llm_response('{"observations":[]}'), tmp_path)
        await notes_review.review_notebooks(hb)

        # Stale note should be marked status='stale'
        row = await db.fetch_one(
            "SELECT status FROM notebook_entries WHERE id = ?", (stale_id,),
        )
        assert row["status"] == "stale"
