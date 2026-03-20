# tests/triage/test_rules.py
import pytest
from app.triage.rules import should_skip

@pytest.mark.parametrize("text,expected", [
    # Single-word acks
    ("ok", True),
    ("OK", True),
    ("okay", True),
    ("k", True),
    ("thanks", True),
    ("thx", True),
    ("np", True),
    ("noted", True),
    ("sure", True),
    # Multi-word acks
    ("got it", True),
    ("will do", True),
    ("sounds good", True),
    # Emoji-only
    ("👍", True),
    ("😊", True),
    ("✅", True),
    ("👍👍", True),
    # Punctuation-only
    ("...", True),
    ("!!", True),
    # Should NOT skip
    ("ok but can we reschedule?", False),
    ("thanks but I have a question", False),
    ("Can we meet tomorrow?", False),
    ("Fine.", False),
    ("", False),
    ("What time works for you?", False),
])
def test_should_skip(text, expected):
    assert should_skip(text) == expected
