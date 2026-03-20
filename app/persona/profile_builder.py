# app/persona/profile_builder.py
import json
import logging
from typing import Any, Optional

import httpx
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.settings import settings
from app.persona.style_analyzer import extract_style_signals

logger = logging.getLogger(__name__)

MIN_MESSAGES_REQUIRED = 5


async def fetch_recent_messages(user_id: str, limit: int = 50) -> list[dict]:
    """Fetch the last `limit` messages sent by this user from alter-server."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{settings.ALTER_SERVER_URL}/internal/users/{user_id}/sent-messages",
            params={"limit": limit},
            headers={"Authorization": f"Bearer {settings.ALTER_SERVICE_TOKEN}"},
            timeout=5.0,
        )
        resp.raise_for_status()
        return resp.json()


def signals_to_directive(signals: dict[str, Any]) -> str:
    """Convert style signals dict to a concise system prompt directive."""
    parts = []

    avg_len = signals.get("avg_length", 0)
    if avg_len < 20:
        parts.append("very short, punchy messages")
    elif avg_len < 60:
        parts.append("concise messages")
    else:
        parts.append("detailed messages")

    if signals.get("end_punct_ratio", 0) < 0.2:
        parts.append("rarely uses end punctuation")
    else:
        parts.append("uses proper punctuation")

    if signals.get("emoji_frequency", 0) > 0.3:
        parts.append("frequently uses emojis")
    elif signals.get("emoji_frequency", 0) < 0.05:
        parts.append("rarely uses emojis")

    formality = signals.get("formality", "casual")
    parts.append(f"{formality} tone")

    phrases = signals.get("common_phrases", [])
    if phrases:
        parts.append(f"uses phrases like: {', '.join(phrases[:5])}")

    return f"Mirror this communication style: {'; '.join(parts)}."


async def build_style_profile(user_id: str) -> Optional[dict]:
    """
    Fetch recent messages, extract signals, and upsert style_profiles row
    using optimistic concurrency (version column).
    Returns the profile dict on success, None if insufficient data.
    """
    messages = await fetch_recent_messages(user_id)
    signals = extract_style_signals(messages)

    if signals.get("message_count", 0) < MIN_MESSAGES_REQUIRED:
        logger.info("Not enough messages to build style profile for user %s", user_id)
        return None

    directive = signals_to_directive(signals)
    profile_data = {**signals, "directive": directive}
    profile_json = json.dumps(profile_data)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("SELECT version FROM style_profiles WHERE user_id = :uid"),
            {"uid": user_id},
        )
        row = result.scalar_one_or_none()

        if row is None:
            await db.execute(
                text("""
                    INSERT INTO style_profiles (user_id, profile, version, message_count)
                    VALUES (:uid, :profile::jsonb, 0, :count)
                """),
                {"uid": user_id, "profile": profile_json, "count": signals["message_count"]},
            )
        else:
            current_version = row
            updated = await db.execute(
                text("""
                    UPDATE style_profiles
                    SET profile = :profile::jsonb,
                        version = version + 1,
                        message_count = :count,
                        updated_at = now()
                    WHERE user_id = :uid AND version = :version
                """),
                {"uid": user_id, "profile": profile_json, "count": signals["message_count"], "version": current_version},
            )
            if updated.rowcount == 0:
                # Optimistic concurrency conflict — retry once (second write wins)
                logger.info("Style profile version conflict for user %s — retrying", user_id)
                await db.execute(
                    text("""
                        UPDATE style_profiles
                        SET profile = :profile::jsonb,
                            version = version + 1,
                            message_count = :count,
                            updated_at = now()
                        WHERE user_id = :uid
                    """),
                    {"uid": user_id, "profile": profile_json, "count": signals["message_count"]},
                )

        await db.commit()

    logger.info("Style profile updated for user %s", user_id)
    return profile_data
