# tests/connectors/test_orchestrator_registry.py
from unittest.mock import AsyncMock, MagicMock, patch

from app.connectors.base import ToolResult


async def test_orchestrator_uses_registry_tools():
    """LLMOrchestrator.run fetches tools from the registry, not hardcoded lists."""
    mock_db = AsyncMock()
    mock_registry = MagicMock()
    registry_tool = {
        "name": "gmail_send_email",
        "description": "Send email",
        "input_schema": {"type": "object", "properties": {}},
    }
    mock_registry.get_tools_for_user = AsyncMock(return_value=[registry_tool])

    context = {
        "system_prompt": "You are a bot.",
        "messages": [{"role": "user", "content": "test"}],
    }

    with patch("app.bot.orchestrator.get_registry", return_value=mock_registry):
        with patch("app.bot.orchestrator.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.content = [MagicMock(type="text", text="Hello")]
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            from app.bot.orchestrator import LLMOrchestrator
            from app.context.working_memory import WorkingMemory
            with patch.object(WorkingMemory, "append_event", new_callable=AsyncMock):
                orch = LLMOrchestrator(mock_db)
                await orch.run(
                    user_id="user_1",
                    thread_id="thread_1",
                    context=context,
                    preferred_llm="claude",
                    llm_api_keys={"claude": "test_key"},
                )

    # Registry was consulted for tools
    mock_registry.get_tools_for_user.assert_called_once_with("user_1", mock_db)


async def test_handle_tool_call_dispatches_to_registry():
    """handle_tool_call routes non-send_message tools to registry.dispatch_tool."""
    mock_db = AsyncMock()
    mock_registry = MagicMock()
    mock_registry.dispatch_tool = AsyncMock(return_value=ToolResult(content={"result": "ok"}))

    mock_permission_engine = MagicMock()
    mock_permission_engine.check_permission = AsyncMock(return_value="full_auto")

    with patch("app.bot.orchestrator.get_registry", return_value=mock_registry):
        from app.bot.orchestrator import LLMOrchestrator
        from app.permissions.engine import PermissionEngine
        from app.context.working_memory import WorkingMemory

        with patch.object(PermissionEngine, "check_permission", new_callable=AsyncMock, return_value="full_auto"):
            with patch.object(WorkingMemory, "append_event", new_callable=AsyncMock):
                orch = LLMOrchestrator(mock_db)
                result = await orch.handle_tool_call(
                    "user_1", "thread_1", "gmail_send_email", {"to": "x", "subject": "y", "body": "z"}
                )

    mock_registry.dispatch_tool.assert_called_once()
    assert result["action"] == "tool_executed"
