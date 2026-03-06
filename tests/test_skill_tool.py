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
    async def test_activate_existing_skill(self, skill_registry):
        tool = ActivateSkillTool(skill_registry=skill_registry)
        result = await tool.execute({"name": "research"})

        assert result.success is True
        assert "research" in result.data
        assert "activated" in result.data.lower()

    async def test_activate_nonexistent_skill(self, skill_registry):
        tool = ActivateSkillTool(skill_registry=skill_registry)
        result = await tool.execute({"name": "nonexistent"})

        assert result.success is False
        assert "not found" in result.error.lower()

    async def test_activate_missing_name(self, skill_registry):
        tool = ActivateSkillTool(skill_registry=skill_registry)
        result = await tool.execute({})

        assert result.success is False

    async def test_tool_metadata(self, skill_registry):
        tool = ActivateSkillTool(skill_registry=skill_registry)

        assert tool.name == "activate_skill"
        assert "skill" in tool.description.lower()
        assert "name" in tool.parameters_schema["properties"]

    async def test_last_activated_skill(self, skill_registry):
        """After activation, tool exposes the activated skill info."""
        tool = ActivateSkillTool(skill_registry=skill_registry)
        await tool.execute({"name": "research"})

        assert tool.last_activated_name == "research"
        assert tool.last_activated_prompt == "You are a thorough research assistant.\n1. Search\n2. Read\n3. Synthesize"
        assert tool.last_activated_tools == ["web_search", "read_page"]

    async def test_last_activated_cleared_on_new_call(self, skill_registry):
        """Each call resets the last activated info."""
        tool = ActivateSkillTool(skill_registry=skill_registry)
        await tool.execute({"name": "research"})
        await tool.execute({"name": "nonexistent"})

        assert tool.last_activated_name is None
