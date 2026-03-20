# tests/connectors/test_notion.py
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import httpx

from app.connectors.builtin.notion import NotionConnector
from app.connectors.credentials import CredentialManager


def _mock_search_response(titles: list[str]):
    results = []
    for t in titles:
        results.append({
            "properties": {
                "title": {
                    "title": [{"plain_text": t}]
                }
            }
        })
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"results": results}
    return mock_resp


async def test_get_context_lists_recent_pages():
    """get_context returns the titles of recently edited Notion pages."""
    cred_manager = MagicMock(spec=CredentialManager)
    cred_manager.get = AsyncMock(return_value={"access_token": "tok_notion"})
    connector = NotionConnector(cred_manager)

    mock_db = AsyncMock()
    mock_resp = _mock_search_response(["My Project", "Meeting Notes", "Ideas"])

    with patch("httpx.AsyncClient") as MockClient:
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.post.return_value = mock_resp
        MockClient.return_value = mock_client_instance

        block = await connector.get_context("user_1", mock_db)

    assert "My Project" in block.content
    assert "Meeting Notes" in block.content


async def test_handle_tool_call_search_pages():
    """notion_search_pages calls the Notion search endpoint and returns results."""
    cred_manager = MagicMock(spec=CredentialManager)
    cred_manager.get = AsyncMock(return_value={"access_token": "tok_notion"})
    connector = NotionConnector(cred_manager)

    mock_db = AsyncMock()
    mock_resp = _mock_search_response(["Result 1"])

    with patch("httpx.AsyncClient") as MockClient:
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.post.return_value = mock_resp
        MockClient.return_value = mock_client_instance

        result = await connector.handle_tool_call(
            "notion_search_pages", {"query": "project"}, "user_1", mock_db
        )

    assert result.error is None
    assert "results" in result.content
