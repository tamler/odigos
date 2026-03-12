from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odigos.channels.telegram import TelegramChannel
from odigos.core.agent_service import AgentService


@pytest.fixture
def mock_service():
    service = MagicMock(spec=AgentService)
    service.handle_message = AsyncMock(return_value="Document processed.")
    return service


@pytest.fixture
def channel(mock_service):
    return TelegramChannel(token="test-token", service=mock_service, mode="polling")


class TestTelegramDocumentHandler:
    async def test_handle_document_downloads_and_passes_path(
        self, channel, mock_service, tmp_path
    ):
        mock_file = AsyncMock()
        mock_file.download_to_drive = AsyncMock()

        update = MagicMock()
        update.effective_message.document.file_name = "report.pdf"
        update.effective_message.document.file_id = "file-123"
        update.effective_message.document.mime_type = "application/pdf"
        update.effective_message.caption = "Summarize this report"
        update.effective_message.message_id = 42
        update.effective_message.reply_text = AsyncMock()
        update.effective_chat.id = 12345
        update.effective_user.id = 67890
        update.effective_user.username = "testuser"

        context = MagicMock()
        context.bot.get_file = AsyncMock(return_value=mock_file)
        context.bot.send_chat_action = AsyncMock()

        with patch("odigos.channels.telegram.DOCUMENT_DIR", str(tmp_path)):
            await channel._handle_document(update, context)

        call_args = mock_service.handle_message.call_args[0][0]
        assert call_args.content == "Summarize this report"
        assert "file_path" in call_args.metadata
        assert call_args.metadata["file_path"].endswith("report.pdf")
        assert call_args.channel == "telegram"

    async def test_handle_document_uses_default_caption(
        self, channel, mock_service, tmp_path
    ):
        mock_file = AsyncMock()
        mock_file.download_to_drive = AsyncMock()

        update = MagicMock()
        update.effective_message.document.file_name = "photo.jpg"
        update.effective_message.document.file_id = "file-456"
        update.effective_message.document.mime_type = "image/jpeg"
        update.effective_message.caption = None
        update.effective_message.message_id = 43
        update.effective_message.reply_text = AsyncMock()
        update.effective_chat.id = 12345
        update.effective_user.id = 67890
        update.effective_user.username = "testuser"

        context = MagicMock()
        context.bot.get_file = AsyncMock(return_value=mock_file)
        context.bot.send_chat_action = AsyncMock()

        with patch("odigos.channels.telegram.DOCUMENT_DIR", str(tmp_path)):
            await channel._handle_document(update, context)

        call_args = mock_service.handle_message.call_args[0][0]
        assert (
            "document" in call_args.content.lower()
            or "process" in call_args.content.lower()
        )

    async def test_handle_document_replies_on_download_failure(
        self, channel, mock_service, tmp_path
    ):
        update = MagicMock()
        update.effective_message.document.file_name = "fail.pdf"
        update.effective_message.document.file_id = "file-789"
        update.effective_message.message_id = 44
        update.effective_message.reply_text = AsyncMock()
        update.effective_chat.id = 12345
        update.effective_user.id = 67890

        context = MagicMock()
        context.bot.get_file = AsyncMock(side_effect=Exception("Download failed"))
        context.bot.send_chat_action = AsyncMock()

        with patch("odigos.channels.telegram.DOCUMENT_DIR", str(tmp_path)):
            await channel._handle_document(update, context)

        update.effective_message.reply_text.assert_called_once()
        assert "failed" in update.effective_message.reply_text.call_args[0][0].lower()
        mock_service.handle_message.assert_not_called()
