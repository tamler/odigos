import json

import pytest
from odigos.skills.registry import SkillRegistry, Skill
from odigos.tools.skill_tool import ActivateSkillTool


@pytest.fixture
def skill_registry():
    registry = SkillRegistry()
    registry._skills = {
        "research": Skill(
            name="research",
            description="In-depth research",
            tools=["web_search", "read_page"],
            complexity="standard",
            system_prompt="You are a thorough research assistant.\n1. Search\n2. Read\n3. Synthesize",
        ),
    }
    return registry


class TestActivateSkillTool:
    @pytest.mark.asyncio
    async def test_activate_existing_skill(self, skill_registry):
        tool = ActivateSkillTool(skill_registry=skill_registry)
        result = await tool.execute({"name": "research"})

        assert result.success is True
        payload = json.loads(result.data)
        assert payload["skill_name"] == "research"
        assert "activated" in payload["message"].lower()

    @pytest.mark.asyncio
    async def test_activate_nonexistent_skill(self, skill_registry):
        tool = ActivateSkillTool(skill_registry=skill_registry)
        result = await tool.execute({"name": "nonexistent"})

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_activate_missing_name(self, skill_registry):
        tool = ActivateSkillTool(skill_registry=skill_registry)
        result = await tool.execute({})

        assert result.success is False

    @pytest.mark.asyncio
    async def test_tool_metadata(self, skill_registry):
        tool = ActivateSkillTool(skill_registry=skill_registry)

        assert tool.name == "activate_skill"
        assert "skill" in tool.description.lower()
        assert "name" in tool.parameters_schema["properties"]

    @pytest.mark.asyncio
    async def test_payload_contains_skill_info(self, skill_registry):
        """Activation returns structured JSON with skill info."""
        tool = ActivateSkillTool(skill_registry=skill_registry)
        result = await tool.execute({"name": "research"})

        payload = json.loads(result.data)
        assert payload["__skill_activation__"] is True
        assert payload["skill_name"] == "research"
        assert payload["skill_prompt"] == "You are a thorough research assistant.\n1. Search\n2. Read\n3. Synthesize"
        assert payload["skill_tools"] == ["web_search", "read_page"]

    @pytest.mark.asyncio
    async def test_no_shared_state(self, skill_registry):
        """Tool has no mutable instance state — safe for concurrent use."""
        tool = ActivateSkillTool(skill_registry=skill_registry)
        await tool.execute({"name": "research"})

        assert not hasattr(tool, "last_activated_name")
        assert not hasattr(tool, "last_activated_prompt")
        assert not hasattr(tool, "last_activated_tools")
