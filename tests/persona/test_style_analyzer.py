# tests/persona/test_style_analyzer.py
import pytest
from app.persona.style_analyzer import extract_style_signals


def test_short_messages_detected():
    messages = [
        {"content": "ok", "intent": "text_message"},
        {"content": "sure", "intent": "text_message"},
        {"content": "lmk", "intent": "text_message"},
    ]
    signals = extract_style_signals(messages)
    assert signals["avg_length"] < 10
    assert signals["message_count"] == 3


def test_emoji_frequency():
    messages = [
        {"content": "sounds good 👍", "intent": "text_message"},
        {"content": "sure! 😊", "intent": "text_message"},
        {"content": "ok no emoji", "intent": "text_message"},
    ]
    signals = extract_style_signals(messages)
    assert signals["emoji_frequency"] == pytest.approx(2/3, abs=0.01)


def test_bot_messages_excluded():
    messages = [
        {"content": "This is a human message", "intent": "text_message"},
        {"content": "Bot reply here", "intent": "reply"},
        {"content": "Another human", "intent": "owner_command"},
    ]
    signals = extract_style_signals(messages)
    assert signals["message_count"] == 2


def test_end_punctuation_detection():
    messages = [
        {"content": "heading out now", "intent": "text_message"},
        {"content": "be there soon", "intent": "text_message"},
        {"content": "Running late.", "intent": "text_message"},
    ]
    signals = extract_style_signals(messages)
    assert signals["end_punct_ratio"] == pytest.approx(1/3, abs=0.01)


def test_common_phrases():
    messages = [
        {"content": "lmk when you're free", "intent": "text_message"},
        {"content": "lmk about the meeting", "intent": "text_message"},
        {"content": "nw just ping me", "intent": "text_message"},
    ]
    signals = extract_style_signals(messages)
    assert "lmk" in signals["common_phrases"]
