# app/triage/classifier.py
import json
import logging
from typing import Any

from app.core.settings import settings

logger = logging.getLogger(__name__)

_CLASSIFIER_PROMPT = """\
You are a message triage classifier. Decide if an incoming message requires a reply from an AI assistant.

Return ONLY valid JSON: {{"needs_reply": bool, "confidence": float (0-1), "reason": string}}

Rules:
- needs_reply=false: pure acknowledgements ("ok", "thanks", emoji-only), closers ("sounds good"), no question or request
- needs_reply=true: questions, requests, complaints, anything actionable
- confidence must reflect actual certainty

Context (last 2 messages):
{context}

Incoming message: "{message}"
Intent: {intent}
"""

CONFIDENCE_THRESHOLD = 0.85


async def _call_llm(prompt: str) -> str:
    """Call Gemini Flash (cheap) for triage classification."""
    import google.generativeai as genai
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")
    response = await model.generate_content_async(prompt)
    return response.text


async def classify_message(
    message: str,
    last_two_msgs: list[dict[str, Any]],
    intent: str,
) -> dict[str, Any]:
    """
    Returns {"needs_reply": bool, "confidence": float, "reason": str}.
    If confidence < CONFIDENCE_THRESHOLD, forces needs_reply=True (safe default).
    """
    context_str = "\n".join(
        f"{m['role']}: {m['content']}" for m in last_two_msgs
    ) or "(no prior context)"

    prompt = _CLASSIFIER_PROMPT.format(
        context=context_str,
        message=message,
        intent=intent,
    )

    try:
        raw = await _call_llm(prompt)
        # Strip markdown code fences if present
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(raw)
        confidence = float(result.get("confidence", 0.0))
        needs_reply = bool(result.get("needs_reply", True))

        # Safety: low confidence → always reply
        if confidence < CONFIDENCE_THRESHOLD:
            needs_reply = True

        return {
            "needs_reply": needs_reply,
            "confidence": confidence,
            "reason": result.get("reason", ""),
        }
    except Exception as e:
        logger.warning("Triage classifier failed, defaulting to needs_reply=True: %s", e)
        return {"needs_reply": True, "confidence": 0.0, "reason": f"classifier_error: {e}"}
