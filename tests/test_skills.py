import pytest

from odigos.skills.registry import Skill, SkillRegistry


@pytest.fixture
def skills_dir(tmp_path):
    """Create a temp directory with SKILL.md files."""
    skill1 = tmp_path / "research-deep-dive.md"
    skill1.write_text(
        "---\n"
        "name: research-deep-dive\n"
        "description: In-depth research using web search\n"
        "tools: [web_search, read_page]\n"
        "complexity: standard\n"
        "---\n"
        "You are a thorough research assistant.\n"
        "Search and synthesize.\n"
    )

    skill2 = tmp_path / "general-chat.md"
    skill2.write_text(
        "---\n"
        "name: general-chat\n"
        "description: Default conversation\n"
        "tools: []\n"
        "complexity: light\n"
        "---\n"
        "You are a helpful assistant.\n"
    )

    (tmp_path / "README.md").write_text("This is not a skill.")

    return tmp_path


class TestSkillDataclass:
    def test_skill_fields(self):
        skill = Skill(
            name="test",
            description="A test skill",
            tools=["web_search"],
            complexity="standard",
            system_prompt="You are a test.",
        )
        assert skill.name == "test"
        assert skill.tools == ["web_search"]


class TestSkillRegistry:
    def test_load_all(self, skills_dir):
        registry = SkillRegistry()
        registry.load_all(str(skills_dir))
        assert len(registry.list()) == 2

    def test_get_by_name(self, skills_dir):
        registry = SkillRegistry()
        registry.load_all(str(skills_dir))
        skill = registry.get("research-deep-dive")
        assert skill is not None
        assert skill.description == "In-depth research using web search"
        assert "web_search" in skill.tools
        assert "thorough research assistant" in skill.system_prompt

    def test_get_missing_returns_none(self, skills_dir):
        registry = SkillRegistry()
        registry.load_all(str(skills_dir))
        assert registry.get("nonexistent") is None

    def test_ignores_non_skill_files(self, skills_dir):
        """Files without valid YAML frontmatter are ignored."""
        registry = SkillRegistry()
        registry.load_all(str(skills_dir))
        names = [s.name for s in registry.list()]
        assert "README" not in names

    def test_empty_dir(self, tmp_path):
        registry = SkillRegistry()
        registry.load_all(str(tmp_path))
        assert len(registry.list()) == 0
