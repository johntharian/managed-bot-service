# app/persona/style_analyzer.py
import re
from collections import Counter
from typing import Any

_EMOJI_RE = re.compile(
    "[\U00010000-\U0010ffff\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\u2702-\u27B0\u24C2-\U0001F251]+",
    flags=re.UNICODE,
)
_END_PUNCT_RE = re.compile(r'[.!?]$')
_WORD_RE = re.compile(r'\b[a-z]{2,}\b')
_CONTRACTION_RE = re.compile(
    r"\b(?:i'm|i've|i'll|i'd|you're|you've|you'll|you'd"
    r"|he's|he'd|he'll|she's|she'd|she'll"
    r"|we're|we've|we'll|we'd|they're|they've|they'll|they'd"
    r"|it's|that's|who's|what's|here's|there's|where's"
    r"|don't|doesn't|didn't|won't|wouldn't|can't|couldn't"
    r"|shouldn't|hasn't|haven't|hadn't|isn't|aren't|wasn't|weren't"
    r"|let's|that'll|how's|why's)\b",
    flags=re.IGNORECASE,
)

_HUMAN_INTENTS = {"text_message", "owner_command"}


def extract_style_signals(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Extract style signals from a list of messages.
    Each message dict must have 'content' and 'intent' keys.
    Bot-generated messages (intent='reply', 'bot_message') are excluded.
    """
    human_msgs = [m for m in messages if m.get("intent") in _HUMAN_INTENTS]

    if not human_msgs:
        return {"message_count": 0}

    texts = [m["content"] for m in human_msgs]

    avg_length = sum(len(t) for t in texts) / len(texts)
    emoji_freq = sum(1 for t in texts if _EMOJI_RE.search(t)) / len(texts)
    end_punct_ratio = sum(1 for t in texts if _END_PUNCT_RE.search(t.strip())) / len(texts)
    uses_contractions = sum(1 for t in texts if _CONTRACTION_RE.search(t)) / len(texts)

    all_words = []
    for text in texts:
        all_words.extend(_WORD_RE.findall(text.lower()))
    word_counts = Counter(all_words)
    common_phrases = [w for w, c in word_counts.most_common(20) if c >= 2 and len(w) <= 6]

    formal_signals = sum(
        1 for t in texts
        if " I " in t or t[0].isupper() or _END_PUNCT_RE.search(t.strip())
    )
    formality = "formal" if formal_signals / len(texts) > 0.6 else "casual"

    return {
        "message_count": len(human_msgs),
        "avg_length": round(avg_length, 1),
        "emoji_frequency": round(emoji_freq, 3),
        "end_punct_ratio": round(end_punct_ratio, 3),
        "uses_contractions": round(uses_contractions, 3),
        "common_phrases": common_phrases[:10],
        "formality": formality,
    }
