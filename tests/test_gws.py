from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odigos.config import GWSConfig
from odigos.skills.registry import SkillRegistry
from odigos.tools.gws import GWSTool


class TestGWSTool:
    def test_tool_metadata(self):
        tool = GWSTool()
        assert tool.name == "run_gws"
        assert "command" in tool.parameters_schema["properties"]
        assert "command" in tool.parameters_schema["required"]

    @pytest.mark.asyncio
    async def test_missing_command(self):
        tool = GWSTool()
        result = await tool.execute({})
        assert result.success is False
        assert "Missing required parameter" in result.error

    @pytest.mark.asyncio
    async def test_empty_command(self):
        tool = GWSTool()
        result = await tool.execute({"command": ""})
        assert result.success is False
        assert "Missing required parameter" in result.error

    @pytest.mark.asyncio
    @patch("odigos.tools.subprocess_tool.asyncio.create_subprocess_exec")
    async def test_successful_command(self, mock_exec):
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate.return_value = (b'{"files": []}', b"")
        mock_exec.return_value = proc

        tool = GWSTool()
        result = await tool.execute({"command": "drive files list --params '{\"pageSize\": 5}'"})

        assert result.success is True
        assert '{"files": []}' in result.data
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0]
        assert call_args[0] == "gws"
        assert "drive" in call_args
        assert "files" in call_args
        assert "list" in call_args

    @pytest.mark.asyncio
    @patch("odigos.tools.subprocess_tool.asyncio.create_subprocess_exec")
    async def test_command_failure(self, mock_exec):
        proc = AsyncMock()
        proc.returncode = 1
        proc.communicate.return_value = (b"", b"Error: unauthorized")
        mock_exec.return_value = proc

        tool = GWSTool()
        result = await tool.execute({"command": "drive files list"})

        assert result.success is False
        assert "unauthorized" in result.error

    @pytest.mark.asyncio
    @patch("odigos.tools.subprocess_tool.asyncio.create_subprocess_exec")
    async def test_gws_not_found(self, mock_exec):
        mock_exec.side_effect = FileNotFoundError()

        tool = GWSTool()
        result = await tool.execute({"command": "drive files list"})

        assert result.success is False
        assert "npm install -g @googleworkspace/cli" in result.error

    @pytest.mark.asyncio
    async def test_malformed_quotes(self):
        tool = GWSTool()
        result = await tool.execute({"command": "drive files list --params '{\"bad"})
        assert result.success is False
        assert "Invalid command syntax" in result.error

    @pytest.mark.asyncio
    @patch("odigos.tools.subprocess_tool.asyncio.create_subprocess_exec")
    async def test_timeout(self, mock_exec):
        proc = AsyncMock()
        proc.communicate.side_effect = asyncio.TimeoutError()
        proc.kill = MagicMock()
        proc.wait = AsyncMock()
        mock_exec.return_value = proc

        tool = GWSTool(timeout=5)
        result = await tool.execute({"command": "drive files list"})

        assert result.success is False
        assert "timed out after 5s" in result.error
        proc.kill.assert_called_once()
        proc.wait.assert_called_once()

    @pytest.mark.asyncio
    @patch("odigos.tools.subprocess_tool.asyncio.create_subprocess_exec")
    async def test_quoted_params(self, mock_exec):
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate.return_value = (b"ok", b"")
        mock_exec.return_value = proc

        tool = GWSTool()
        await tool.execute({"command": "gmail users messages list --params '{\"userId\": \"me\"}'"})

        call_args = mock_exec.call_args[0]
        assert call_args[0] == "gws"
        assert "gmail" in call_args
        # shlex.split should handle the quoted JSON as a single arg
        assert '{"userId": "me"}' in call_args

    def test_custom_timeout(self):
        tool = GWSTool(timeout=120)
        assert tool._timeout == 120


class TestGWSConfig:
    def test_default_disabled(self):
        config = GWSConfig()
        assert config.enabled is False
        assert config.timeout == 30

    def test_enabled(self):
        config = GWSConfig(enabled=True, timeout=60)
        assert config.enabled is True
        assert config.timeout == 60


class TestGWSSkill:
    def test_skill_loads(self):
        registry = SkillRegistry()
        registry.load_all("skills")
        skill = registry.get("google-workspace")
        assert skill is not None
        assert "run_gws" in skill.tools
        assert skill.complexity == "standard"
        assert "gmail" in skill.system_prompt.lower()
