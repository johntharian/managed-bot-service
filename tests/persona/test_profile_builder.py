# tests/persona/test_profile_builder.py
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.persona.profile_builder import signals_to_directive


def test_signals_to_directive_short_casual():
    signals = {
        "avg_length": 12.5,
        "emoji_frequency": 0.05,
        "end_punct_ratio": 0.1,
        "common_phrases": ["lmk", "nw", "brb"],
        "formality": "casual",
    }
    directive = signals_to_directive(signals)
    assert "lmk" in directive
    assert "casual" in directive.lower() or "informal" in directive.lower()


def test_signals_to_directive_long_formal():
    signals = {
        "avg_length": 120.0,
        "emoji_frequency": 0.01,
        "end_punct_ratio": 0.9,
        "common_phrases": [],
        "formality": "formal",
    }
    directive = signals_to_directive(signals)
    assert "formal" in directive.lower() or "detail" in directive.lower()


async def test_build_profile_skips_on_insufficient_messages():
    """Fewer than 5 human messages → returns None, no DB write."""
    mock_messages = [
        {"content": "ok", "intent": "text_message"},
    ]

    with patch("app.persona.profile_builder.fetch_recent_messages", new_callable=AsyncMock, return_value=mock_messages):
        from app.persona.profile_builder import build_style_profile
        result = await build_style_profile("user_123")

    assert result is None


async def test_build_profile_writes_to_db_on_first_run():
    """Enough messages → executes DB upsert."""
    mock_messages = [
        {"content": f"message number {i}", "intent": "text_message"} for i in range(10)
    ]
    mock_execute = AsyncMock()
    mock_execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

    mock_db = AsyncMock()
    mock_db.execute = mock_execute
    mock_db.commit = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("app.persona.profile_builder.fetch_recent_messages", new_callable=AsyncMock, return_value=mock_messages):
        with patch("app.persona.profile_builder.AsyncSessionLocal", return_value=mock_db):
            from app.persona.profile_builder import build_style_profile
            result = await build_style_profile("user_123")

    assert mock_db.commit.called
    assert result is not None
    assert "directive" in result
