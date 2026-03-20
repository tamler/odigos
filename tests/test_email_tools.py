"""Tests for email tools (check_email, send_email)."""

import pytest

from odigos.config import EmailConfig
from odigos.tools.email import CheckEmailTool, SendEmailTool


@pytest.fixture
def disabled_config():
    return EmailConfig(enabled=False)


@pytest.fixture
def configured_config():
    return EmailConfig(
        enabled=True,
        address="test@example.com",
        imap_host="imap.example.com",
        imap_port=993,
        smtp_host="smtp.example.com",
        smtp_port=587,
        username="test@example.com",
        password="testpass",
    )


class TestCheckEmailTool:
    async def test_disabled_returns_error(self, disabled_config):
        tool = CheckEmailTool(email_config=disabled_config)
        result = await tool.execute({})
        assert not result.success
        assert "not configured" in result.error

    async def test_tool_metadata(self, configured_config):
        tool = CheckEmailTool(email_config=configured_config)
        assert tool.name == "check_email"
        assert "inbox" in tool.description.lower()
        assert "limit" in tool.parameters_schema["properties"]


class TestSendEmailTool:
    async def test_disabled_returns_error(self, disabled_config):
        tool = SendEmailTool(email_config=disabled_config)
        result = await tool.execute({"to": "a@b.com", "subject": "Hi", "body": "Hello"})
        assert not result.success
        assert "not configured" in result.error

    async def test_missing_fields_returns_error(self, configured_config):
        tool = SendEmailTool(email_config=configured_config)
        result = await tool.execute({"to": "", "subject": "", "body": ""})
        assert not result.success
        assert "required" in result.error

    async def test_invalid_email_returns_error(self, configured_config):
        tool = SendEmailTool(email_config=configured_config)
        result = await tool.execute({"to": "not-an-email", "subject": "Hi", "body": "Hello"})
        assert not result.success
        assert "Invalid" in result.error

    async def test_tool_metadata(self, configured_config):
        tool = SendEmailTool(email_config=configured_config)
        assert tool.name == "send_email"
        assert "to" in tool.parameters_schema["properties"]
        assert "subject" in tool.parameters_schema["properties"]
        assert "body" in tool.parameters_schema["properties"]
