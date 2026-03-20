# tests/connectors/test_gmail.py
from unittest.mock import MagicMock, AsyncMock, patch

from app.connectors.builtin.gmail import GmailConnector
from app.connectors.credentials import CredentialManager


def _mock_service():
    """Build a minimal mock of the Gmail service object."""
    svc = MagicMock()
    # getProfile
    svc.users.return_value.getProfile.return_value.execute.return_value = {
        "messagesUnread": 3
    }
    # messages.list
    svc.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]
    }
    # messages.get (for context — metadata headers)
    svc.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "payload": {"headers": [{"name": "Subject", "value": "Test subject"}]}
    }
    return svc


async def test_get_context_returns_unread_count_and_subjects():
    """get_context returns unread count and subject lines."""
    cred_manager = MagicMock(spec=CredentialManager)
    cred_manager.get = AsyncMock(return_value={
        "access_token": "tok", "refresh_token": "ref",
        "client_id": "cid", "client_secret": "cs", "token_uri": "uri"
    })
    connector = GmailConnector(cred_manager)

    mock_svc = _mock_service()
    mock_db = AsyncMock()

    with patch("app.connectors.builtin.gmail._build_service", return_value=mock_svc):
        block = await connector.get_context("user_1", mock_db)

    assert "3 unread" in block.content
    assert "Test subject" in block.content
    assert block.token_count == len(block.content) // 4


async def test_handle_tool_call_send_email():
    """handle_tool_call sends an email and returns sent status."""
    cred_manager = MagicMock(spec=CredentialManager)
    cred_manager.get = AsyncMock(return_value={
        "access_token": "tok", "refresh_token": "ref",
        "client_id": "cid", "client_secret": "cs", "token_uri": "uri"
    })
    connector = GmailConnector(cred_manager)

    mock_svc = MagicMock()
    mock_svc.users.return_value.messages.return_value.send.return_value.execute.return_value = {
        "id": "sent_123"
    }
    mock_db = AsyncMock()

    with patch("app.connectors.builtin.gmail._build_service", return_value=mock_svc):
        result = await connector.handle_tool_call(
            "gmail_send_email",
            {"to": "bob@example.com", "subject": "Hello", "body": "World"},
            "user_1",
            mock_db,
        )

    assert result.error is None
    assert result.content["status"] == "sent"
