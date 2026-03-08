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

    def test_create_skill(self, tmp_path):
        registry = SkillRegistry()
        skill = registry.create(
            name="daily-digest",
            description="Summarize the day",
            system_prompt="You summarize the user's day.",
            tools=["web_search"],
            skills_dir=str(tmp_path),
        )
        assert skill.name == "daily-digest"
        assert registry.get("daily-digest") is not None
        # File was written to disk
        path = tmp_path / "daily-digest.md"
        assert path.exists()
        content = path.read_text()
        assert "daily-digest" in content
        assert "You summarize the user's day." in content

    def test_created_skill_is_loadable(self, tmp_path):
        """A skill created with create() can be loaded by load_all()."""
        registry1 = SkillRegistry()
        registry1.create(
            name="my-skill",
            description="Test",
            system_prompt="Be helpful.",
            skills_dir=str(tmp_path),
        )

        registry2 = SkillRegistry()
        registry2.load_all(str(tmp_path))
        skill = registry2.get("my-skill")
        assert skill is not None
        assert skill.system_prompt == "Be helpful."

    def test_create_requires_skills_dir(self):
        registry = SkillRegistry()
        with pytest.raises(ValueError, match="skills_dir"):
            registry.create(
                name="test",
                description="test",
                system_prompt="test",
            )


class TestSkillBuiltinFlag:
    def test_loaded_skills_are_builtin(self, skills_dir):
        registry = SkillRegistry()
        registry.load_all(str(skills_dir))
        for skill in registry.list():
            assert skill.builtin is True

    def test_created_skills_are_not_builtin(self, tmp_path):
        registry = SkillRegistry()
        skill = registry.create(
            name="my-skill",
            description="Test",
            system_prompt="Be helpful.",
            skills_dir=str(tmp_path),
        )
        assert skill.builtin is False

    def test_load_all_stores_skills_dir(self, skills_dir):
        registry = SkillRegistry()
        registry.load_all(str(skills_dir))
        assert registry.skills_dir == str(skills_dir)


class TestSkillRegistryUpdate:
    def test_update_description(self, tmp_path):
        registry = SkillRegistry()
        registry.create(
            name="my-skill",
            description="Original",
            system_prompt="Be helpful.",
            skills_dir=str(tmp_path),
        )
        updated = registry.update(name="my-skill", description="Updated description")
        assert updated.description == "Updated description"
        assert registry.get("my-skill").description == "Updated description"

    def test_update_instructions(self, tmp_path):
        registry = SkillRegistry()
        registry.create(
            name="my-skill",
            description="Test",
            system_prompt="Be helpful.",
            skills_dir=str(tmp_path),
        )
        updated = registry.update(name="my-skill", instructions="New instructions here.")
        assert updated.system_prompt == "New instructions here."

    def test_update_persists_to_disk(self, tmp_path):
        registry = SkillRegistry()
        registry.create(
            name="my-skill",
            description="Test",
            system_prompt="Be helpful.",
            skills_dir=str(tmp_path),
        )
        registry.update(name="my-skill", instructions="Updated on disk.")

        # Reload from disk
        registry2 = SkillRegistry()
        registry2.load_all(str(tmp_path))
        skill = registry2.get("my-skill")
        assert skill.system_prompt == "Updated on disk."

    def test_update_rejects_builtin(self, skills_dir):
        registry = SkillRegistry()
        registry.load_all(str(skills_dir))
        with pytest.raises(ValueError, match="built-in"):
            registry.update(name="research-deep-dive", description="Hacked")

    def test_update_rejects_nonexistent(self, tmp_path):
        registry = SkillRegistry()
        registry.skills_dir = str(tmp_path)
        with pytest.raises(ValueError, match="not found"):
            registry.update(name="nonexistent", description="Nope")

    def test_update_partial_preserves_other_fields(self, tmp_path):
        registry = SkillRegistry()
        registry.create(
            name="my-skill",
            description="Original desc",
            system_prompt="Original prompt.",
            tools=["web_search"],
            complexity="standard",
            skills_dir=str(tmp_path),
        )
        updated = registry.update(name="my-skill", description="New desc")
        assert updated.description == "New desc"
        assert updated.system_prompt == "Original prompt."
        assert updated.tools == ["web_search"]
        assert updated.complexity == "standard"
