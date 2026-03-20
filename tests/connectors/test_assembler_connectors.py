# tests/connectors/test_assembler_connectors.py
from unittest.mock import AsyncMock, MagicMock, patch

from app.context.long_term_memory import LongTermMemory


async def test_system_prompt_includes_connector_context():
    """Connector context block appears in assembled system prompt."""
    mock_db = AsyncMock()

    mock_registry = MagicMock()
    mock_registry.get_active_context = AsyncMock(
        return_value="## Connected Services\n**Gmail:** 2 unread message(s)"
    )

    with patch("app.context.assembler.fetch_bot_instructions", new_callable=AsyncMock, return_value=[]):
        with patch("app.context.assembler.fetch_style_profile", new_callable=AsyncMock, return_value=None):
            with patch("app.context.assembler.get_registry", return_value=mock_registry):
                with patch.object(LongTermMemory, "get_all_for_user", new_callable=AsyncMock, return_value={}):
                    from app.context.assembler import ContextAssembler
                    from app.context.thread_fetcher import AlterThreadFetcher
                    from app.context.working_memory import WorkingMemory

                    with patch.object(AlterThreadFetcher, "fetch_thread_history", new_callable=AsyncMock, return_value=[]):
                        with patch.object(WorkingMemory, "get_state", new_callable=AsyncMock, return_value=[]):
                            assembler = ContextAssembler(mock_db)
                            result = await assembler.assemble(
                                user_id="user_1",
                                thread_id="thread_1",
                                incoming_message={"role": "user", "content": "hi"},
                            )

    assert "## Connected Services" in result["system_prompt"]
    assert "2 unread" in result["system_prompt"]


async def test_system_prompt_omits_connector_context_when_empty():
    """When no connectors are active, system prompt has no Connected Services block."""
    mock_db = AsyncMock()
    mock_registry = MagicMock()
    mock_registry.get_active_context = AsyncMock(return_value="")

    with patch("app.context.assembler.fetch_bot_instructions", new_callable=AsyncMock, return_value=[]):
        with patch("app.context.assembler.fetch_style_profile", new_callable=AsyncMock, return_value=None):
            with patch("app.context.assembler.get_registry", return_value=mock_registry):
                with patch.object(LongTermMemory, "get_all_for_user", new_callable=AsyncMock, return_value={}):
                    from app.context.assembler import ContextAssembler
                    from app.context.thread_fetcher import AlterThreadFetcher
                    from app.context.working_memory import WorkingMemory

                    with patch.object(AlterThreadFetcher, "fetch_thread_history", new_callable=AsyncMock, return_value=[]):
                        with patch.object(WorkingMemory, "get_state", new_callable=AsyncMock, return_value=[]):
                            assembler = ContextAssembler(mock_db)
                            result = await assembler.assemble(
                                user_id="user_1",
                                thread_id="thread_1",
                                incoming_message={"role": "user", "content": "hi"},
                            )

    assert "## Connected Services" not in result["system_prompt"]
