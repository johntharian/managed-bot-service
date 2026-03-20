# app/triage/rules.py
import re

_EXACT_ACKS = frozenset([
    "ok", "okay", "k", "thanks", "thx", "np", "noted", "sure",
    "got it", "will do", "sounds good", "👍", "😊", "✅",
])

_EMOJI_RE = re.compile(
    "[\U00010000-\U0010ffff"
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\u2702-\u27B0"
    "\u24C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)
_PUNCT_ONLY_RE = re.compile(r'^[\s\W]+$')


def should_skip(text: str) -> bool:
    """Return True if the message is an acknowledgement that needs no reply."""
    if not text or not text.strip():
        return False

    cleaned = text.strip().lower()

    if cleaned in _EXACT_ACKS:
        return True

    # Emoji-only: strip all emoji and whitespace, nothing left
    no_emoji = _EMOJI_RE.sub("", text).strip()
    if not no_emoji:
        return True

    # Punctuation-only
    if _PUNCT_ONLY_RE.match(text):
        return True

    return False
