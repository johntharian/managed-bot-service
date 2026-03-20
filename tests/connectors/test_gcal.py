# tests/connectors/test_gcal.py
from unittest.mock import MagicMock, AsyncMock, patch

from app.connectors.builtin.gcal import GCalConnector
from app.connectors.credentials import CredentialManager


async def test_get_context_returns_events():
    """get_context lists today/tomorrow events."""
    cred_manager = MagicMock(spec=CredentialManager)
    cred_manager.get = AsyncMock(return_value={
        "access_token": "tok", "refresh_token": "ref",
        "client_id": "cid", "client_secret": "cs", "token_uri": "uri"
    })
    connector = GCalConnector(cred_manager)

    mock_svc = MagicMock()
    mock_svc.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "summary": "Team standup",
                "start": {"dateTime": "2026-03-20T09:00:00+00:00"},
            }
        ]
    }
    mock_db = AsyncMock()

    with patch("app.connectors.builtin.gcal._build_service", return_value=mock_svc):
        block = await connector.get_context("user_1", mock_db)

    assert "Team standup" in block.content


async def test_handle_tool_call_create_event():
    """handle_tool_call creates an event and returns event_id."""
    cred_manager = MagicMock(spec=CredentialManager)
    cred_manager.get = AsyncMock(return_value={
        "access_token": "tok", "refresh_token": "ref",
        "client_id": "cid", "client_secret": "cs", "token_uri": "uri"
    })
    connector = GCalConnector(cred_manager)

    mock_svc = MagicMock()
    mock_svc.events.return_value.insert.return_value.execute.return_value = {"id": "evt_xyz"}
    mock_db = AsyncMock()

    with patch("app.connectors.builtin.gcal._build_service", return_value=mock_svc):
        result = await connector.handle_tool_call(
            "gcal_create_event",
            {
                "summary": "Doctor appt",
                "start_time": "2026-03-21T10:00:00+00:00",
                "end_time": "2026-03-21T11:00:00+00:00",
            },
            "user_1",
            mock_db,
        )

    assert result.error is None
    assert result.content["event_id"] == "evt_xyz"
