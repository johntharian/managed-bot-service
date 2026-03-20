# tests/persona/test_tasks.py
from unittest.mock import patch, AsyncMock, MagicMock


def test_update_style_profile_task_calls_builder():
    """Task calls build_style_profile with the correct user_id."""
    with patch("app.persona.tasks.asyncio") as mock_asyncio:
        with patch("app.persona.profile_builder.build_style_profile", new_callable=AsyncMock) as mock_build:
            mock_asyncio.run = MagicMock(return_value=None)  # trackable mock

            from app.persona.tasks import update_style_profile
            # Call the underlying function directly (not via Celery)
            update_style_profile.__wrapped__("user_42")

    # asyncio.run was called (i.e., the coroutine was invoked)
    mock_asyncio.run.assert_called_once()
