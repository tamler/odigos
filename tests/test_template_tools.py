"""Tests for agent template browse and adopt tools."""
import os
import tempfile
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest
import pytest_asyncio

from odigos.core.template_index import AgentTemplateIndex
from odigos.db import Database
from odigos.skills.registry import SkillRegistry
from odigos.tools.template_tools import BrowseTemplates, AdoptTemplate


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def template_index(db):
    return AgentTemplateIndex(db=db)


@pytest.fixture
def skill_registry():
    reg = SkillRegistry()
    with tempfile.TemporaryDirectory() as tmpdir:
        reg.skills_dir = tmpdir
        yield reg


@pytest_asyncio.fixture
async def seeded_index(template_index):
    """Index with a few templates pre-loaded."""
    await template_index.create_custom_template(
        name="backend architect", content="# Backend Architect\nYou design APIs.", division="engineering",
    )
    await template_index.create_custom_template(
        name="seo specialist", content="# SEO Specialist\nYou optimize search.", division="marketing",
    )
    await template_index.create_custom_template(
        name="ux researcher", content="# UX Researcher\nYou study users.", division="design",
    )
    return template_index


# --- BrowseTemplates ---


@pytest.mark.asyncio
async def test_browse_list_all(seeded_index):
    tool = BrowseTemplates(template_index=seeded_index)
    result = await tool.execute({})

    assert result.success
    assert "3 templates" in result.data
    assert "backend architect" in result.data
    assert "seo specialist" in result.data
    assert "ux researcher" in result.data


@pytest.mark.asyncio
async def test_browse_filter_by_division(seeded_index):
    tool = BrowseTemplates(template_index=seeded_index)
    result = await tool.execute({"division": "engineering"})

    assert result.success
    assert "1 templates" in result.data
    assert "backend architect" in result.data
    assert "seo" not in result.data


@pytest.mark.asyncio
async def test_browse_search(seeded_index):
    tool = BrowseTemplates(template_index=seeded_index)
    result = await tool.execute({"search": "seo"})

    assert result.success
    assert "1 templates" in result.data
    assert "seo specialist" in result.data


@pytest.mark.asyncio
async def test_browse_search_no_results(seeded_index):
    tool = BrowseTemplates(template_index=seeded_index)
    result = await tool.execute({"search": "quantum"})

    assert result.success
    assert "No templates found" in result.data


@pytest.mark.asyncio
async def test_browse_preview(seeded_index):
    tool = BrowseTemplates(template_index=seeded_index)
    result = await tool.execute({"preview": "backend"})

    assert result.success
    assert "Backend Architect" in result.data
    assert "You design APIs" in result.data


@pytest.mark.asyncio
async def test_browse_preview_not_found(seeded_index):
    tool = BrowseTemplates(template_index=seeded_index)
    result = await tool.execute({"preview": "nonexistent"})

    assert not result.success
    assert "No template matching" in result.error


# --- AdoptTemplate ---


@pytest.mark.asyncio
async def test_adopt_creates_skill(seeded_index, skill_registry):
    tool = AdoptTemplate(template_index=seeded_index, skill_registry=skill_registry)
    result = await tool.execute({"template_name": "backend architect"})

    assert result.success
    assert "adopted as skill" in result.data

    # Verify skill was created
    skill = skill_registry.get("backend-architect")
    assert skill is not None
    assert "Backend Architect" in skill.system_prompt
    assert "agency-agents" in skill.description


@pytest.mark.asyncio
async def test_adopt_custom_skill_name(seeded_index, skill_registry):
    tool = AdoptTemplate(template_index=seeded_index, skill_registry=skill_registry)
    result = await tool.execute({
        "template_name": "seo specialist",
        "skill_name": "my-seo-skill",
    })

    assert result.success
    skill = skill_registry.get("my-seo-skill")
    assert skill is not None
    assert "SEO Specialist" in skill.system_prompt


@pytest.mark.asyncio
async def test_adopt_template_not_found(seeded_index, skill_registry):
    tool = AdoptTemplate(template_index=seeded_index, skill_registry=skill_registry)
    result = await tool.execute({"template_name": "nonexistent"})

    assert not result.success
    assert "No template matching" in result.error


@pytest.mark.asyncio
async def test_adopt_missing_name(seeded_index, skill_registry):
    tool = AdoptTemplate(template_index=seeded_index, skill_registry=skill_registry)
    result = await tool.execute({})

    assert not result.success
    assert "required" in result.error


@pytest.mark.asyncio
async def test_adopt_refuses_overwrite_builtin(seeded_index, skill_registry):
    """Should not overwrite a built-in skill."""
    from odigos.skills.registry import Skill
    skill_registry._skills["backend-architect"] = Skill(
        name="backend-architect", description="built-in", tools=[], complexity="standard",
        system_prompt="original", builtin=True,
    )

    tool = AdoptTemplate(template_index=seeded_index, skill_registry=skill_registry)
    result = await tool.execute({"template_name": "backend architect"})

    assert not result.success
    assert "built-in" in result.error


@pytest.mark.asyncio
async def test_adopt_sanitize_name():
    """Should produce valid skill names from template names."""
    assert AdoptTemplate._sanitize_name("Backend Architect") == "backend-architect"
    assert AdoptTemplate._sanitize_name("UX/UI Designer") == "ux-ui-designer"
    assert AdoptTemplate._sanitize_name("SEO Specialist (Advanced)") == "seo-specialist-advanced"
