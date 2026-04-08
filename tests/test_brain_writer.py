"""Tests for the brain writer module."""
from __future__ import annotations

import asyncio

import pytest

from odigos.memory.brain_writer import BrainWriter


@pytest.fixture
def writer(tmp_path):
    return BrainWriter(brain_dir=tmp_path)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestWriteEntityPage:
    def test_write_entity_page(self, writer, tmp_path):
        entity = {
            "id": "a1b2c3d4e5f6",
            "type": "person",
            "name": "Jacob",
            "aliases_json": '["Jake", "J"]',
            "confidence": 0.95,
            "source_type": "conv",
            "source_id": "abc123",
        }
        facts = [
            {"id": "f1", "fact": "Prefers Groq for STT", "category": "preference",
             "source_type": "conv", "source_id": "abc123"},
            {"id": "f2", "fact": "Tests with Bob on odigos.one", "category": "behavior",
             "source_type": "conv", "source_id": "def456"},
        ]
        relationships = [
            {"from": "Jacob", "relationship": "owns", "to": "Odigos"},
            {"from": "Odigos", "relationship": "owned_by", "to": "Jacob",
             "direction": "backlink"},
        ]

        path = _run(writer.write_entity_page(entity, facts, relationships))

        filepath = tmp_path / "entities" / "jacob.md"
        assert filepath.exists()
        assert path == str(filepath)

        content = filepath.read_text()
        # Frontmatter checks
        assert "id: a1b2c3d4e5f6" in content
        assert "type: person" in content
        assert "aliases: [Jake, J]" in content
        assert "confidence: 0.95" in content
        assert "sources: [" in content
        assert "conv:abc123" in content
        assert "updated_at:" in content

        # Body checks
        assert "# Jacob" in content
        assert "## Facts" in content
        assert "- Prefers Groq for STT [conv:abc123]" in content
        assert "## Relationships" in content
        assert "- **owns** -> Odigos" in content
        assert "## Backlinks" in content
        assert "Odigos **owned_by** -> Jacob" in content


class TestWriteTopicIndex:
    def test_write_topic_index(self, writer, tmp_path):
        graduated = [
            {"name": "Kie.ai", "description": "Music generation API"},
        ]
        indexed = [
            {"name": "Groq", "description": "LLM provider",
             "source_type": "conv", "source_id": "abc123"},
            {"name": "OpenRouter", "description": "Multi-model routing",
             "source_type": "conv", "source_id": "def456"},
        ]

        path = _run(writer.write_topic_index("tool", graduated, indexed))

        filepath = tmp_path / "topics" / "tool.md"
        assert filepath.exists()
        assert path == str(filepath)

        content = filepath.read_text()
        assert "type: topic_index" in content
        assert "entity_type: tool" in content
        assert "# Tool" in content

        # Graduated entity with link
        assert "## Full Pages" in content
        assert "[Kie.ai](../entities/kieai.md)" in content
        assert "Music generation API" in content

        # Indexed entities inline
        assert "## Index" in content
        assert "**Groq** -- LLM provider [conv:abc123]" in content
        assert "**OpenRouter** -- Multi-model routing [conv:def456]" in content


class TestWriteIndex:
    def test_write_index_md(self, writer, tmp_path):
        entities = [
            {"name": "Jacob", "type": "person", "description": "Project owner",
             "has_page": True},
            {"name": "Odigos", "type": "project", "description": "AI agent platform",
             "has_page": True},
            {"name": "Groq", "type": "tool", "description": "LLM provider",
             "has_page": False},
        ]
        topic_types = ["person", "project", "tool"]

        path = _run(writer.write_index(entities, topic_types))

        filepath = tmp_path / "index.md"
        assert filepath.exists()
        assert path == str(filepath)

        content = filepath.read_text()
        assert "entity_count: 3" in content
        assert "# Knowledge Base Index" in content

        # Topics section
        assert "## Topics" in content
        assert "[Person](topics/person.md) -- 1 entities" in content
        assert "[Project](topics/project.md) -- 1 entities" in content
        assert "[Tool](topics/tool.md) -- 1 entities" in content

        # All entities
        assert "## All Entities" in content
        assert "**Jacob** (person) -- Project owner [entities/jacob.md]" in content
        assert "**Odigos** (project) -- AI agent platform [entities/odigos.md]" in content
        # Groq has no page, so no file link
        assert "**Groq** (tool) -- LLM provider" in content
        assert "Groq" in content and "entities/groq.md" not in content


class TestAppendLog:
    def test_append_log(self, writer, tmp_path):
        _run(writer.append_log("extraction", "Extracted 2 entities from conversation abc123"))
        _run(writer.append_log("maintenance", "Updated 3 entities"))

        filepath = tmp_path / "log.md"
        assert filepath.exists()

        content = filepath.read_text()
        lines = content.strip().split("\n")

        # Both entries present, most recent first
        assert "## [" in lines[0]
        assert "maintenance" in lines[0]
        assert "Updated 3 entities" in lines[1]

        # Earlier entry below
        assert any("extraction" in line for line in lines)
        assert any("Extracted 2 entities" in line for line in lines)


class TestWriteConversationSummary:
    def test_write_conversation_summary(self, writer, tmp_path):
        path = _run(writer.write_conversation_summary(
            conv_id="abc123def456",
            title="Capabilities and Horror Story",
            summary="User asked about agent capabilities. Then requested a short horror story.",
            message_count=4,
            created_at="2026-04-07T08:14:00Z",
            facts_extracted=["User exploring agent capabilities"],
        ))

        filepath = tmp_path / "conversations" / "2026-04-07-capabilities-and-horror-story.md"
        assert filepath.exists()
        assert path == str(filepath)

        content = filepath.read_text()
        assert "id: abc123def456" in content
        assert "message_count: 4" in content
        assert "created_at: 2026-04-07T08:14:00Z" in content
        assert "# Capabilities and Horror Story" in content
        assert "User asked about agent capabilities" in content
        assert "## Key Facts Extracted" in content
        assert "- User exploring agent capabilities" in content


class TestShouldGraduate:
    def test_entity_graduation(self, writer):
        assert writer.should_graduate(2, 1) is False
        assert writer.should_graduate(3, 0) is True
        assert writer.should_graduate(1, 2) is True
