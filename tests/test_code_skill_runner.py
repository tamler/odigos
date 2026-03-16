import pytest
from pathlib import Path
from odigos.tools.code_skill_runner import CodeSkillRunner


@pytest.fixture
def skill_files(tmp_path):
    """Create a simple code skill and its .md file."""
    code_dir = tmp_path / "skills" / "code"
    code_dir.mkdir(parents=True)

    code_file = code_dir / "adder.py"
    code_file.write_text('def run(a: str, b: str) -> str:\n    return str(int(a) + int(b))\n')

    md_file = tmp_path / "skills" / "adder.md"
    md_file.write_text(
        '---\nname: adder\ndescription: Add numbers\ncode: skills/code/adder.py\nverified: false\n---\nAdds two numbers.\n'
    )

    return code_file, md_file


@pytest.fixture
def runner(skill_files):
    code_file, md_file = skill_files
    return CodeSkillRunner(
        skill_name="adder",
        skill_description="Add two numbers",
        code_path=str(code_file),
        parameters={"a": {"type": "string"}, "b": {"type": "string"}},
        timeout=5,
        allow_network=False,
        skill_md_path=str(md_file),
        verified=False,
    )


@pytest.mark.asyncio
async def test_tool_metadata(runner):
    assert runner.name == "skill_adder"
    assert runner.description == "Add two numbers"
    props = runner.parameters_schema["properties"]
    assert "a" in props
    assert "b" in props
    assert props["a"]["type"] == "string"
    assert props["b"]["type"] == "string"


@pytest.mark.asyncio
async def test_execute_simple(runner):
    result = await runner.execute({"a": "3", "b": "4"})
    assert result.success is True
    assert result.data == "7"


@pytest.mark.asyncio
async def test_execute_missing_file(skill_files):
    _, md_file = skill_files
    runner = CodeSkillRunner(
        skill_name="adder",
        skill_description="Add two numbers",
        code_path="/nonexistent/path/adder.py",
        parameters={"a": {"type": "string"}, "b": {"type": "string"}},
        skill_md_path=str(md_file),
    )
    result = await runner.execute({"a": "1", "b": "2"})
    assert result.success is False
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_verified_flag_updates(runner, skill_files):
    _, md_file = skill_files

    assert runner._verified is False
    result = await runner.execute({"a": "1", "b": "2"})
    assert result.success is True
    assert runner._verified is True

    content = md_file.read_text()
    assert "verified: true" in content
