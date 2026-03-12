import os
import pytest
from odigos.tools.file import FileTool


@pytest.fixture
def file_tool(tmp_path):
    return FileTool(allowed_paths=[str(tmp_path)])


class TestFileTool:
    async def test_write_and_read(self, file_tool, tmp_path):
        result = await file_tool.execute({
            "operation": "write",
            "path": str(tmp_path / "test.txt"),
            "content": "hello world",
        })
        assert result.success
        result = await file_tool.execute({
            "operation": "read",
            "path": str(tmp_path / "test.txt"),
        })
        assert result.success
        assert "hello world" in result.data

    async def test_read_nonexistent(self, file_tool, tmp_path):
        result = await file_tool.execute({
            "operation": "read",
            "path": str(tmp_path / "nope.txt"),
        })
        assert not result.success

    async def test_path_outside_sandbox_rejected(self, file_tool):
        result = await file_tool.execute({
            "operation": "read",
            "path": "/etc/passwd",
        })
        assert not result.success
        assert "not within allowed" in result.error.lower()

    async def test_symlink_escape_blocked(self, file_tool, tmp_path):
        link = tmp_path / "sneaky"
        link.symlink_to("/etc")
        result = await file_tool.execute({
            "operation": "read",
            "path": str(link / "passwd"),
        })
        assert not result.success

    async def test_list_directory(self, file_tool, tmp_path):
        (tmp_path / "a.txt").write_text("aaa")
        (tmp_path / "b.txt").write_text("bbb")
        result = await file_tool.execute({
            "operation": "list",
            "path": str(tmp_path),
        })
        assert result.success
        assert "a.txt" in result.data
        assert "b.txt" in result.data

    async def test_write_creates_parent_dirs(self, file_tool, tmp_path):
        result = await file_tool.execute({
            "operation": "write",
            "path": str(tmp_path / "sub" / "dir" / "file.txt"),
            "content": "nested",
        })
        assert result.success
        assert (tmp_path / "sub" / "dir" / "file.txt").read_text() == "nested"

    async def test_read_binary_rejected(self, file_tool, tmp_path):
        bin_file = tmp_path / "binary.bin"
        bin_file.write_bytes(b"\x00\x01\x02\xff\xfe")
        result = await file_tool.execute({
            "operation": "read",
            "path": str(bin_file),
        })
        assert not result.success

    async def test_missing_operation(self, file_tool):
        result = await file_tool.execute({"path": "/tmp/x"})
        assert not result.success
