# app/persona/tasks.py
import asyncio
import logging
from celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="persona.tasks.update_style_profile", bind=True, max_retries=1)
def update_style_profile(self, user_id: str) -> None:
    """Celery task: rebuild style profile for a user from their recent sent messages."""
    logger.info("Running update_style_profile for user %s", user_id)
    try:
        from app.persona.profile_builder import build_style_profile
        asyncio.run(build_style_profile(user_id))
    except Exception as exc:
        logger.error("update_style_profile failed for user %s: %s", user_id, exc)
        raise self.retry(exc=exc)
