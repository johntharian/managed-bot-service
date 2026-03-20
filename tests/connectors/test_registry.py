# tests/connectors/test_registry.py
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.connectors.base import BaseConnector, ContextBlock, ToolResult
from app.connectors.credentials import CredentialManager
from app.connectors.registry import ConnectorRegistry


def _make_connector(name: str, display_name: str, token_budget: int, context_str: str, tools: list):
    """Helper: create a concrete BaseConnector subclass for testing."""
    _tools = tools
    _context = ContextBlock(content=context_str)

    class TestConnector(BaseConnector):
        async def connect(self, user_id: str, creds: dict, db) -> None:
            pass

        async def disconnect(self, user_id: str, db) -> None:
            pass

        async def get_context(self, user_id: str, db) -> ContextBlock:
            return _context

        def get_tools(self):
            return _tools

        async def handle_tool_call(self, tool_name: str, args: dict, user_id: str, db) -> ToolResult:
            return ToolResult(content={"ok": True})

    TestConnector.name = name
    TestConnector.display_name = display_name
    TestConnector.token_budget = token_budget
    return TestConnector


async def test_get_active_context_respects_token_cap():
    """
    When combined budgets exceed 200 tokens, lowest-priority (last_used_at
    null / oldest) connectors are excluded entirely.
    """
    cred_manager = MagicMock(spec=CredentialManager)
    registry = ConnectorRegistry(cred_manager)

    # Connector A: 150 tokens — fits
    a_content = "A" * (150 * 4)
    ConnA = _make_connector("svc_a", "Svc A", 150, a_content, [])
    # Connector B: 100 tokens — would push total to 250, exceeds cap → excluded
    b_content = "B" * (100 * 4)
    ConnB = _make_connector("svc_b", "Svc B", 100, b_content, [])

    registry._connectors = {
        "svc_a": ConnA(cred_manager),
        "svc_b": ConnB(cred_manager),
    }

    # Mock DB: two active integrations, svc_a has most-recent last_used_at
    from datetime import datetime, timezone
    int_a = MagicMock()
    int_a.service = "svc_a"
    int_a.last_used_at = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)

    int_b = MagicMock()
    int_b.service = "svc_b"
    int_b.last_used_at = None  # older / never used → lower priority

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [int_a, int_b]
    mock_db.execute.return_value = mock_result

    context = await registry.get_active_context("user_1", mock_db)

    assert a_content in context       # A fits
    assert b_content not in context   # B excluded entirely


async def test_get_tools_for_user_merges_connectors():
    """get_tools_for_user returns tools from all active connectors."""
    cred_manager = MagicMock(spec=CredentialManager)
    registry = ConnectorRegistry(cred_manager)

    tool_a = {"name": "svc_a_do", "description": "do a", "input_schema": {"type": "object", "properties": {}}}
    tool_b = {"name": "svc_b_do", "description": "do b", "input_schema": {"type": "object", "properties": {}}}

    ConnA = _make_connector("svc_a", "Svc A", 50, "", [tool_a])
    ConnB = _make_connector("svc_b", "Svc B", 50, "", [tool_b])
    registry._connectors = {
        "svc_a": ConnA(cred_manager),
        "svc_b": ConnB(cred_manager),
    }

    int_a = MagicMock(); int_a.service = "svc_a"
    int_b = MagicMock(); int_b.service = "svc_b"
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [int_a, int_b]
    mock_db.execute.return_value = mock_result

    tools = await registry.get_tools_for_user("user_1", mock_db)
    names = [t["name"] for t in tools]
    assert "svc_a_do" in names
    assert "svc_b_do" in names


async def test_dispatch_tool_routes_to_correct_connector():
    """dispatch_tool resolves tool_name → connector and calls handle_tool_call."""
    cred_manager = MagicMock(spec=CredentialManager)
    registry = ConnectorRegistry(cred_manager)

    tool = {"name": "svc_a_do", "description": "x", "input_schema": {"type": "object", "properties": {}}}
    ConnA = _make_connector("svc_a", "Svc A", 50, "", [tool])
    instance_a = ConnA(cred_manager)

    # Wrap handle_tool_call with an AsyncMock to track calls
    original_handle = instance_a.handle_tool_call
    instance_a.handle_tool_call = AsyncMock(return_value=ToolResult(content={"ok": True}))

    registry._connectors = {"svc_a": instance_a}
    registry._tool_map = {"svc_a_do": "svc_a"}

    mock_db = AsyncMock()
    result = await registry.dispatch_tool("svc_a_do", {"x": 1}, "user_1", mock_db)

    instance_a.handle_tool_call.assert_called_once_with("svc_a_do", {"x": 1}, "user_1", mock_db)
    assert result.content == {"ok": True}
    mock_db.commit.assert_called_once()  # last_used_at update
