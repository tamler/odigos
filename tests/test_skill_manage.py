import pytest

from odigos.skills.registry import SkillRegistry
from odigos.tools.skill_manage import CreateSkillTool, UpdateSkillTool


@pytest.fixture
def registry_with_dir(tmp_path):
    registry = SkillRegistry()
    registry.load_all(str(tmp_path))
    return registry


@pytest.fixture
def registry_with_builtin(tmp_path):
    skill_file = tmp_path / "builtin-skill.md"
    skill_file.write_text(
        "---\n"
        "name: builtin-skill\n"
        "description: A built-in skill\n"
        "tools: []\n"
        "complexity: light\n"
        "---\n"
        "Built-in instructions.\n"
    )
    registry = SkillRegistry()
    registry.load_all(str(tmp_path))
    return registry


class TestCreateSkillTool:
    @pytest.mark.asyncio
    async def test_create_skill_success(self, registry_with_dir):
        tool = CreateSkillTool(skill_registry=registry_with_dir)
        result = await tool.execute({
            "name": "daily-digest",
            "description": "Summarize the day",
            "instructions": "Review today's conversations and create a summary.",
        })
        assert result.success is True
        assert "daily-digest" in result.data
        assert registry_with_dir.get("daily-digest") is not None

    @pytest.mark.asyncio
    async def test_create_skill_invalid_name(self, registry_with_dir):
        tool = CreateSkillTool(skill_registry=registry_with_dir)
        result = await tool.execute({
            "name": "Bad Name!",
            "description": "Test",
            "instructions": "Test.",
        })
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_create_skill_missing_fields(self, registry_with_dir):
        tool = CreateSkillTool(skill_registry=registry_with_dir)
        result = await tool.execute({"name": "test"})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_create_skill_with_optional_fields(self, registry_with_dir):
        tool = CreateSkillTool(skill_registry=registry_with_dir)
        result = await tool.execute({
            "name": "research-v2",
            "description": "Better research",
            "instructions": "Search thoroughly.",
            "tools": ["web_search", "read_page"],
            "complexity": "heavy",
        })
        assert result.success is True
        skill = registry_with_dir.get("research-v2")
        assert skill.tools == ["web_search", "read_page"]
        assert skill.complexity == "heavy"

    @pytest.mark.asyncio
    async def test_tool_metadata(self, registry_with_dir):
        tool = CreateSkillTool(skill_registry=registry_with_dir)
        assert tool.name == "create_skill"
        assert "name" in tool.parameters_schema["properties"]
        assert "description" in tool.parameters_schema["properties"]
        assert "instructions" in tool.parameters_schema["properties"]


class TestUpdateSkillTool:
    @pytest.mark.asyncio
    async def test_update_skill_success(self, registry_with_dir):
        create_tool = CreateSkillTool(skill_registry=registry_with_dir)
        await create_tool.execute({
            "name": "my-skill",
            "description": "Original",
            "instructions": "Original instructions.",
        })

        tool = UpdateSkillTool(skill_registry=registry_with_dir)
        result = await tool.execute({
            "name": "my-skill",
            "description": "Updated description",
        })
        assert result.success is True
        assert registry_with_dir.get("my-skill").description == "Updated description"

    @pytest.mark.asyncio
    async def test_update_builtin_rejected(self, registry_with_builtin):
        tool = UpdateSkillTool(skill_registry=registry_with_builtin)
        result = await tool.execute({
            "name": "builtin-skill",
            "description": "Hacked",
        })
        assert result.success is False
        assert "built-in" in result.error.lower()

    @pytest.mark.asyncio
    async def test_update_nonexistent_rejected(self, registry_with_dir):
        tool = UpdateSkillTool(skill_registry=registry_with_dir)
        result = await tool.execute({
            "name": "nonexistent",
            "description": "Nope",
        })
        assert result.success is False

    @pytest.mark.asyncio
    async def test_update_missing_name(self, registry_with_dir):
        tool = UpdateSkillTool(skill_registry=registry_with_dir)
        result = await tool.execute({"description": "No name given"})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_tool_metadata(self, registry_with_dir):
        tool = UpdateSkillTool(skill_registry=registry_with_dir)
        assert tool.name == "update_skill"
        assert "name" in tool.parameters_schema["properties"]
