# tests/persona/test_assembler_persona.py
from unittest.mock import AsyncMock, MagicMock, patch


async def test_system_prompt_includes_categorised_instructions():
    """Categorised instructions appear as grouped blocks in system prompt."""
    mock_instructions = [
        MagicMock(instruction_text="Be direct and brief", category="communication_style"),
        MagicMock(instruction_text="Sarah is my wife", category="relationships"),
        MagicMock(instruction_text="Never use bullet points", category="response_preferences"),
    ]
    mock_style = MagicMock()
    mock_style.profile = {"directive": "Mirror this style: short messages; casual tone."}
    mock_db = AsyncMock()

    with patch("app.context.assembler.fetch_bot_instructions", new_callable=AsyncMock, return_value=mock_instructions):
        with patch("app.context.assembler.fetch_style_profile", new_callable=AsyncMock, return_value=mock_style):
            from app.context.assembler import ContextAssembler
            assembler = ContextAssembler(mock_db)
            # _build_system_prompt takes (user_id, owner_mode, db)
            prompt = await assembler._build_system_prompt("user_123", owner_mode=False, db=mock_db)

    assert "Be direct and brief" in prompt
    assert "Sarah is my wife" in prompt
    assert "Mirror this style" in prompt


async def test_system_prompt_omits_style_directive_when_no_profile():
    """When no style_profiles row exists, style directive is omitted (cold-start)."""
    mock_instructions = [MagicMock(instruction_text="Be helpful", category="general")]
    mock_db = AsyncMock()

    with patch("app.context.assembler.fetch_bot_instructions", new_callable=AsyncMock, return_value=mock_instructions):
        with patch("app.context.assembler.fetch_style_profile", new_callable=AsyncMock, return_value=None):
            from app.context.assembler import ContextAssembler
            assembler = ContextAssembler(mock_db)
            prompt = await assembler._build_system_prompt("user_123", owner_mode=False, db=mock_db)

    assert "Be helpful" in prompt
    assert "Mirror this" not in prompt
