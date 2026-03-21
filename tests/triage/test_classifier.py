# tests/triage/test_classifier.py
import pytest
from unittest.mock import AsyncMock, patch
from app.triage.classifier import classify_message


async def test_classifier_skip_on_low_intent():
    """Classifier returns needs_reply=False with high confidence for clear ack."""
    mock_response = '{"needs_reply": false, "confidence": 0.95, "reason": "Pure acknowledgement"}'

    with patch("app.triage.classifier._call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_response
        result = await classify_message(
            message="Fine.",
            last_two_msgs=[
                {"role": "user", "content": "Are you free tomorrow?"},
                {"role": "assistant", "content": "Yes, I'm free!"},
            ],
            intent="text_message",
        )

    assert result["needs_reply"] is False
    assert result["confidence"] >= 0.85
    assert "reason" in result


async def test_classifier_passes_question():
    """Classifier returns needs_reply=True for a clear question."""
    mock_response = '{"needs_reply": true, "confidence": 0.98, "reason": "Direct question"}'

    with patch("app.triage.classifier._call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_response
        result = await classify_message(
            message="Can we reschedule to 4pm?",
            last_two_msgs=[],
            intent="text_message",
        )

    assert result["needs_reply"] is True


async def test_classifier_low_confidence_defaults_to_reply():
    """When confidence < 0.85, always reply even if needs_reply=False."""
    mock_response = '{"needs_reply": false, "confidence": 0.70, "reason": "Ambiguous"}'

    with patch("app.triage.classifier._call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_response
        result = await classify_message("Fine.", [], "text_message")

    assert result["needs_reply"] is True


async def test_classifier_error_defaults_to_reply():
    """LLM call failure → needs_reply=True (safe default)."""
    with patch("app.triage.classifier._call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = Exception("LLM timeout")
        result = await classify_message("Fine.", [], "text_message")

    assert result["needs_reply"] is True
    assert "classifier_error" in result["reason"]
