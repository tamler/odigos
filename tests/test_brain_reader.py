"""Tests for brain_reader: parse brain files and rebuild DB tables."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio

from odigos.memory.brain_reader import parse_entity_page, parse_topic_index, rebuild_from_brain
from tests.conftest import FakeDB

try:
    import aiosqlite
except ImportError:
    aiosqlite = None


@pytest.fixture
def wiki_entity_file(tmp_path: Path) -> Path:
    """Create a sample entity page matching wiki_writer.py output format."""
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    filepath = entities_dir / "jacob.md"
    filepath.write_text(
        "---\n"
        "id: abc123def456\n"
        "type: person\n"
        "aliases: [Jake, J]\n"
        "confidence: 0.95\n"
        "sources: [conv:aaa111, doc:bbb222]\n"
        "updated_at: 2026-04-07T08:30:00Z\n"
        "---\n"
        "\n"
        "# Jacob\n"
        "\n"
        "## Facts\n"
        "- Jacob prefers Groq [conv:aaa111]\n"
        "- Jacob lives in Amsterdam [doc:bbb222]\n"
        "- Jacob is a developer\n"
        "\n"
        "## Relationships\n"
        "- **owns** -> Odigos\n"
        "- **works_on** -> MusicGen\n"
        "\n"
        "## Backlinks\n"
        "- Kie.ai **uses** -> Jacob\n"
        "\n"
    )
    return filepath


@pytest.fixture
def wiki_topic_file(tmp_path: Path) -> Path:
    """Create a sample topic index matching wiki_writer.py output format."""
    topics_dir = tmp_path / "topics"
    topics_dir.mkdir()
    filepath = topics_dir / "tool.md"
    filepath.write_text(
        "---\n"
        "type: topic_index\n"
        "entity_type: tool\n"
        "updated_at: 2026-04-07T08:30:00Z\n"
        "---\n"
        "\n"
        "# Tool\n"
        "\n"
        "## Full Pages\n"
        "- [Scrapling](../entities/scrapling.md) -- web scraper\n"
        "\n"
        "## Index\n"
        "- **HTTPx** -- async HTTP client [conv:ccc333]\n"
        "- **Ruff** -- Python linter [doc:ddd444]\n"
        "\n"
    )
    return filepath


def test_parse_entity_page(wiki_entity_file: Path):
    result = parse_entity_page(wiki_entity_file)

    assert result["id"] == "abc123def456"
    assert result["type"] == "person"
    assert result["name"] == "Jacob"
    assert result["aliases"] == ["Jake", "J"]
    assert result["confidence"] == 0.95
    assert result["sources"] == ["conv:aaa111", "doc:bbb222"]

    assert len(result["facts"]) == 3
    assert result["facts"][0]["fact"] == "Jacob prefers Groq"
    assert result["facts"][0]["source_type"] == "conv"
    assert result["facts"][0]["source_id"] == "aaa111"
    assert result["facts"][2]["fact"] == "Jacob is a developer"
    assert result["facts"][2]["source_type"] is None

    rels = result["relationships"]
    assert len(rels) == 3
    forward = [r for r in rels if r["direction"] == "forward"]
    backlinks = [r for r in rels if r["direction"] == "backlink"]
    assert len(forward) == 2
    assert forward[0]["relationship"] == "owns"
    assert forward[0]["to"] == "Odigos"
    assert len(backlinks) == 1
    assert backlinks[0]["from"] == "Kie.ai"
    assert backlinks[0]["relationship"] == "uses"


def test_parse_topic_index(wiki_topic_file: Path):
    result = parse_topic_index(wiki_topic_file)

    assert len(result) == 2
    assert result[0]["name"] == "HTTPx"
    assert result[0]["type"] == "tool"
    assert result[0]["summary"] == "async HTTP client"
    assert result[0]["sources"] == ["conv:ccc333"]

    assert result[1]["name"] == "Ruff"
    assert result[1]["type"] == "tool"
    assert result[1]["summary"] == "Python linter"
    assert result[1]["sources"] == ["doc:ddd444"]


def test_parse_facts_with_sources(tmp_path: Path):
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    filepath = entities_dir / "test-entity.md"
    filepath.write_text(
        "---\n"
        "id: fact_test_001\n"
        "type: preference\n"
        "aliases: []\n"
        "confidence: 0.8\n"
        "sources: [conv:abc123]\n"
        "updated_at: 2026-04-07T08:30:00Z\n"
        "---\n"
        "\n"
        "# Test Entity\n"
        "\n"
        "## Facts\n"
        "- Jacob prefers Groq [conv:abc123]\n"
        "- Uses dark mode always [doc:xyz789]\n"
        "- Likes coffee\n"
        "\n"
    )

    result = parse_entity_page(filepath)
    facts = result["facts"]

    assert len(facts) == 3
    assert facts[0]["fact"] == "Jacob prefers Groq"
    assert facts[0]["source_type"] == "conv"
    assert facts[0]["source_id"] == "abc123"

    assert facts[1]["fact"] == "Uses dark mode always"
    assert facts[1]["source_type"] == "doc"
    assert facts[1]["source_id"] == "xyz789"

    assert facts[2]["fact"] == "Likes coffee"
    assert facts[2]["source_type"] is None
    assert facts[2]["source_id"] is None


def test_parse_relationships(tmp_path: Path):
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    filepath = entities_dir / "odigos.md"
    filepath.write_text(
        "---\n"
        "id: rel_test_001\n"
        "type: project\n"
        "aliases: []\n"
        "confidence: 0.9\n"
        "sources: []\n"
        "updated_at: 2026-04-07T08:30:00Z\n"
        "---\n"
        "\n"
        "# Odigos\n"
        "\n"
        "## Relationships\n"
        "- **owns** -> GitHub Repo\n"
        "- **depends_on** -> FastAPI\n"
        "\n"
        "## Backlinks\n"
        "- Jacob **created** -> Odigos\n"
        "- Kie.ai **uses** -> Odigos\n"
        "\n"
    )

    result = parse_entity_page(filepath)
    rels = result["relationships"]

    forward = [r for r in rels if r["direction"] == "forward"]
    backlinks = [r for r in rels if r["direction"] == "backlink"]

    assert len(forward) == 2
    assert forward[0]["relationship"] == "owns"
    assert forward[0]["to"] == "GitHub Repo"
    assert forward[1]["relationship"] == "depends_on"
    assert forward[1]["to"] == "FastAPI"

    assert len(backlinks) == 2
    assert backlinks[0]["from"] == "Jacob"
    assert backlinks[0]["relationship"] == "created"
    assert backlinks[0]["to"] == "Odigos"
    assert backlinks[1]["from"] == "Kie.ai"
    assert backlinks[1]["relationship"] == "uses"


@pytest.mark.asyncio
async def test_rebuild_from_brain(tmp_path: Path):
    """Full integration: create a mini brain, rebuild DB, verify row counts."""
    # Set up brain directory structure
    brain_dir = tmp_path / "brain"
    entities_dir = brain_dir / "entities"
    topics_dir = brain_dir / "topics"
    sources_dir = tmp_path / "sources"  # brain_dir.parent / "sources"
    entities_dir.mkdir(parents=True)
    topics_dir.mkdir(parents=True)
    sources_dir.mkdir(parents=True)

    # Entity page with 2 facts and 1 relationship
    (entities_dir / "jacob.md").write_text(
        "---\n"
        "id: ent001\n"
        "type: person\n"
        "aliases: [Jake]\n"
        "confidence: 0.95\n"
        "sources: [conv:s1]\n"
        "updated_at: 2026-04-07T08:30:00Z\n"
        "---\n"
        "\n"
        "# Jacob\n"
        "\n"
        "## Facts\n"
        "- Jacob prefers Groq [conv:s1]\n"
        "- Jacob lives in Amsterdam\n"
        "\n"
        "## Relationships\n"
        "- **owns** -> Odigos\n"
        "\n"
    )

    # Topic index with 2 indexed entities
    (topics_dir / "tool.md").write_text(
        "---\n"
        "type: topic_index\n"
        "entity_type: tool\n"
        "updated_at: 2026-04-07T08:30:00Z\n"
        "---\n"
        "\n"
        "# Tool\n"
        "\n"
        "## Index\n"
        "- **HTTPx** -- async HTTP client [conv:s2]\n"
        "- **Ruff** -- Python linter\n"
        "\n"
    )

    # Source file
    (sources_dir / "2026-04-07-example.md").write_text(
        "---\n"
        "url: https://example.com/article\n"
        "title: Example Article\n"
        "scraped_at: 2026-04-07T08:00:00Z\n"
        "content_type: article\n"
        "sha256: deadbeef1234\n"
        "---\n"
        "\n"
        "Article content here.\n"
    )

    # Set up in-memory DB with required tables
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        db = FakeDB(conn)

        await conn.execute("""
            CREATE TABLE entities (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                aliases_json TEXT,
                confidence REAL DEFAULT 1.0,
                status TEXT DEFAULT 'active',
                summary TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT REFERENCES entities(id),
                relationship TEXT NOT NULL,
                target_id TEXT REFERENCES entities(id),
                strength REAL DEFAULT 1.0,
                created_at TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE user_facts (
                id TEXT PRIMARY KEY,
                fact TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                source TEXT DEFAULT 'extracted',
                source_type TEXT,
                source_id TEXT,
                content_hash TEXT,
                confidence REAL DEFAULT 0.8,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                source_url TEXT,
                content_hash TEXT,
                status TEXT NOT NULL DEFAULT 'ingested'
            )
        """)
        await conn.commit()

        stats = await rebuild_from_brain(db, brain_dir)

        # 1 entity page (Jacob) + 1 stub (Odigos from relationship) + 2 from topic index
        # = 4 entities total
        entities = await db.fetch_all("SELECT * FROM entities")
        assert len(entities) == 4, f"Expected 4 entities, got {len(entities)}"
        assert stats["entities"] == 3  # 1 from page + 2 from topic (stub doesn't count)

        # 2 facts from Jacob's page
        facts = await db.fetch_all("SELECT * FROM user_facts")
        assert len(facts) == 2
        assert stats["facts"] == 2

        # 1 forward relationship (owns -> Odigos)
        edges = await db.fetch_all("SELECT * FROM edges")
        assert len(edges) == 1
        assert stats["edges"] == 1

        # 1 source document
        docs = await db.fetch_all("SELECT * FROM documents")
        assert len(docs) == 1
        assert stats["sources"] == 1
        assert docs[0]["source_url"] == "https://example.com/article"
