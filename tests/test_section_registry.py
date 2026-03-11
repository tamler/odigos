"""Tests for the prompt section registry."""
import os
import tempfile
from pathlib import Path

import pytest

from odigos.personality.section_registry import SectionRegistry, PromptSection


@pytest.fixture
def sections_dir():
    with tempfile.TemporaryDirectory() as d:
        Path(d, "identity.md").write_text(
            "---\npriority: 10\nalways_include: true\n---\nYou are a test agent."
        )
        Path(d, "voice.md").write_text(
            "---\npriority: 20\nalways_include: true\n---\n## Voice\nBe concise."
        )
        Path(d, "optional.md").write_text(
            "---\npriority: 50\nalways_include: false\n---\nOptional context."
        )
        yield d


def test_load_all_sections(sections_dir):
    registry = SectionRegistry(sections_dir)
    sections = registry.load_all()
    assert len(sections) == 3
    assert sections[0].name == "identity"
    assert sections[1].name == "voice"
    assert sections[2].name == "optional"


def test_section_content_strips_frontmatter(sections_dir):
    registry = SectionRegistry(sections_dir)
    sections = registry.load_all()
    identity = sections[0]
    assert identity.content == "You are a test agent."
    assert "---" not in identity.content


def test_section_properties(sections_dir):
    registry = SectionRegistry(sections_dir)
    sections = registry.load_all()
    assert sections[0].priority == 10
    assert sections[0].always_include is True
    assert sections[2].always_include is False


def test_caching_by_mtime(sections_dir):
    registry = SectionRegistry(sections_dir)
    s1 = registry.load_all()
    s2 = registry.load_all()
    assert s1[0].content == s2[0].content


def test_override_merging(sections_dir):
    registry = SectionRegistry(sections_dir)
    overrides = {"identity": "You are an evolved agent."}
    sections = registry.load_all(overrides=overrides)
    identity = [s for s in sections if s.name == "identity"][0]
    assert identity.content == "You are an evolved agent."


def test_missing_dir_returns_empty():
    registry = SectionRegistry("/nonexistent/path")
    assert registry.load_all() == []
