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


async def test_agentic_loop_multi_step_claude():
    """LLM calls two tools sequentially before replying — loop runs twice."""
    mock_db = AsyncMock()

    tool_use_1 = MagicMock(type="tool_use", name="gmail_list_emails", input={}, id="call_1")
    tool_use_2 = MagicMock(type="tool_use", name="gmail_get_email_details", input={"id": "abc"}, id="call_2")
    text_reply = MagicMock(type="text", text="Here are your emails: ...")

    response_1 = MagicMock(content=[tool_use_1])
    response_2 = MagicMock(content=[tool_use_2])
    response_3 = MagicMock(content=[text_reply])

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(side_effect=[response_1, response_2, response_3])

    mock_registry = MagicMock()
    mock_registry.get_tools_for_user = AsyncMock(return_value=[])
    mock_registry.dispatch_tool = AsyncMock(return_value=ToolResult(content={"emails": ["abc"]}))

    context = {
        "system_prompt": "You are a bot.",
        "messages": [{"role": "user", "content": "Summarize my emails"}],
    }

    with patch("app.bot.orchestrator.get_registry", return_value=mock_registry):
        with patch("app.bot.orchestrator.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = mock_client
            from app.bot.orchestrator import LLMOrchestrator
            from app.permissions.engine import PermissionEngine
            from app.context.working_memory import WorkingMemory
            with patch.object(PermissionEngine, "check_permission", new_callable=AsyncMock, return_value="full_auto"):
                with patch.object(WorkingMemory, "append_event", new_callable=AsyncMock):
                    orch = LLMOrchestrator(mock_db)
                    result = await orch.run(
                        user_id="user_1",
                        thread_id="thread_1",
                        context=context,
                        preferred_llm="claude",
                        llm_api_keys={"claude": "test_key"},
                    )

    assert result["action"] == "reply"
    assert "emails" in result["text"].lower()
    assert mock_client.messages.create.call_count == 3  # 2 tool turns + 1 final reply


async def test_agentic_loop_max_iterations():
    """Loop exits and forces a text reply after MAX_LOOP_ITERATIONS tool calls."""
    mock_db = AsyncMock()

    forced_text = MagicMock(content=[MagicMock(type="text", text="I've gathered what I can.")])

    # Use distinct tool names per iteration so duplicate-detection doesn't fire first —
    # we want to exercise the MAX_LOOP_ITERATIONS cap, not the duplicate guard.
    from app.bot import orchestrator as orch_module
    tool_responses = [
        MagicMock(content=[MagicMock(type="tool_use", name=f"gcal_tool_{i}", input={}, id=f"call_{i}")])
        for i in range(orch_module.MAX_LOOP_ITERATIONS)
    ]
    side_effects = tool_responses + [forced_text]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(side_effect=side_effects)

    mock_registry = MagicMock()
    mock_registry.get_tools_for_user = AsyncMock(return_value=[])
    mock_registry.dispatch_tool = AsyncMock(return_value=ToolResult(content={"events": []}))

    context = {
        "system_prompt": "You are a bot.",
        "messages": [{"role": "user", "content": "What's on my calendar?"}],
    }

    with patch("app.bot.orchestrator.get_registry", return_value=mock_registry):
        with patch("app.bot.orchestrator.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = mock_client
            from app.bot.orchestrator import LLMOrchestrator
            from app.permissions.engine import PermissionEngine
            from app.context.working_memory import WorkingMemory
            with patch.object(PermissionEngine, "check_permission", new_callable=AsyncMock, return_value="full_auto"):
                with patch.object(WorkingMemory, "append_event", new_callable=AsyncMock):
                    orch = LLMOrchestrator(mock_db)
                    result = await orch.run(
                        user_id="user_1",
                        thread_id="thread_1",
                        context=context,
                        preferred_llm="claude",
                        llm_api_keys={"claude": "test_key"},
                    )

    assert result["action"] == "reply"
    assert mock_client.messages.create.call_count == orch_module.MAX_LOOP_ITERATIONS + 1


async def test_agentic_loop_duplicate_call_breaks_loop():
    """Loop exits early when the same tool+args is called twice."""
    mock_db = AsyncMock()

    tool_use = MagicMock(type="tool_use", name="gcal_get_upcoming_events", input={}, id="call_dup")
    always_tool = MagicMock(content=[tool_use])
    forced_text = MagicMock(content=[MagicMock(type="text", text="Done.")])

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(side_effect=[always_tool, always_tool, forced_text])

    mock_registry = MagicMock()
    mock_registry.get_tools_for_user = AsyncMock(return_value=[])
    mock_registry.dispatch_tool = AsyncMock(return_value=ToolResult(content={"events": []}))

    context = {
        "system_prompt": "You are a bot.",
        "messages": [{"role": "user", "content": "Check my calendar"}],
    }

    with patch("app.bot.orchestrator.get_registry", return_value=mock_registry):
        with patch("app.bot.orchestrator.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = mock_client
            from app.bot.orchestrator import LLMOrchestrator
            from app.permissions.engine import PermissionEngine
            from app.context.working_memory import WorkingMemory
            with patch.object(PermissionEngine, "check_permission", new_callable=AsyncMock, return_value="full_auto"):
                with patch.object(WorkingMemory, "append_event", new_callable=AsyncMock):
                    orch = LLMOrchestrator(mock_db)
                    result = await orch.run(
                        user_id="user_1",
                        thread_id="thread_1",
                        context=context,
                        preferred_llm="claude",
                        llm_api_keys={"claude": "test_key"},
                    )

    assert result["action"] == "reply"
    assert mock_registry.dispatch_tool.call_count == 1  # only first iteration executes the tool
    assert mock_client.messages.create.call_count == 3  # iter1 + iter2(dup,break) + forced final


async def test_agentic_loop_truncates_large_tool_result():
    """Tool results larger than MAX_TOOL_RESULT_CHARS are truncated before being appended."""
    mock_db = AsyncMock()

    tool_use = MagicMock(type="tool_use", name="gmail_get_email_details", input={"id": "x"}, id="call_t")
    tool_response = MagicMock(content=[tool_use])
    text_reply = MagicMock(content=[MagicMock(type="text", text="Summarized.")])

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(side_effect=[tool_response, text_reply])

    from app.bot import orchestrator as orch_module
    large_result = {"body": "x" * (orch_module.MAX_TOOL_RESULT_CHARS + 500)}
    mock_registry = MagicMock()
    mock_registry.get_tools_for_user = AsyncMock(return_value=[])
    mock_registry.dispatch_tool = AsyncMock(return_value=ToolResult(content=large_result))

    # Capture messages sent to the second LLM call to verify truncation
    captured_messages = []
    original_side_effect = [tool_response, text_reply]

    async def capturing_create(**kwargs):
        captured_messages.append(kwargs.get("messages", []))
        resp = original_side_effect.pop(0)
        return resp

    mock_client.messages.create = capturing_create

    context = {
        "system_prompt": "You are a bot.",
        "messages": [{"role": "user", "content": "Read email x"}],
    }

    with patch("app.bot.orchestrator.get_registry", return_value=mock_registry):
        with patch("app.bot.orchestrator.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = mock_client
            from app.bot.orchestrator import LLMOrchestrator, MAX_TOOL_RESULT_CHARS
            from app.permissions.engine import PermissionEngine
            from app.context.working_memory import WorkingMemory
            with patch.object(PermissionEngine, "check_permission", new_callable=AsyncMock, return_value="full_auto"):
                with patch.object(WorkingMemory, "append_event", new_callable=AsyncMock):
                    orch = LLMOrchestrator(mock_db)
                    result = await orch.run(
                        user_id="user_1",
                        thread_id="thread_1",
                        context=context,
                        preferred_llm="claude",
                        llm_api_keys={"claude": "test_key"},
                    )

    assert result["action"] == "reply"
    mock_registry.dispatch_tool.assert_called_once()
    # The tool result appended to the second call's messages must be truncated
    second_call_messages = captured_messages[1]
    tool_result_turn = second_call_messages[-1]  # last message is the tool_result user turn
    result_content = tool_result_turn["content"][0]["content"]  # tool_result content block
    assert len(result_content) <= MAX_TOOL_RESULT_CHARS + len("... [truncated]")
