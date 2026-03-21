# tests/connectors/test_assembler_connectors.py
from unittest.mock import AsyncMock, patch

from app.context.long_term_memory import LongTermMemory


async def test_system_prompt_has_no_connector_context_block():
    """Connector context is no longer proactively injected into system prompt."""
    mock_db = AsyncMock()

    with patch("app.context.assembler.fetch_bot_instructions", new_callable=AsyncMock, return_value=[]):
        with patch("app.context.assembler.fetch_style_profile", new_callable=AsyncMock, return_value=None):
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
