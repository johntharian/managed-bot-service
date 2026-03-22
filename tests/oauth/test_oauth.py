# tests/oauth/test_oauth.py
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.api.oauth import router
from app.core.database import get_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_app():
    app = FastAPI()
    app.include_router(router)
    return app


async def _mock_db_gen():
    yield AsyncMock()


def _httpx_ctx_mock(json_body: dict):
    """Return a mock that behaves like `async with httpx.AsyncClient() as client`."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = json_body

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# 1. test_authorize_google_returns_url
# ---------------------------------------------------------------------------

async def test_authorize_google_returns_url():
    app = make_app()
    app.dependency_overrides[get_db] = lambda: _mock_db_gen()

    with patch("app.api.oauth.redis_client") as mock_redis:
        mock_redis.setex = AsyncMock(return_value=None)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/google/authorize?user_id=user_123")

    assert response.status_code == 200
    body = response.json()
    assert "url" in body
    url = body["url"]
    assert url.startswith("https://accounts.google.com/")
    assert "gmail.readonly" in url
    assert "calendar" in url
    assert "access_type=offline" in url

    mock_redis.setex.assert_called_once()
    call_args = mock_redis.setex.call_args
    key = call_args[0][0]
    assert key.startswith("oauth_state:")


# ---------------------------------------------------------------------------
# 2. test_authorize_notion_returns_url
# ---------------------------------------------------------------------------

async def test_authorize_notion_returns_url():
    app = make_app()
    app.dependency_overrides[get_db] = lambda: _mock_db_gen()

    with patch("app.api.oauth.redis_client") as mock_redis:
        mock_redis.setex = AsyncMock(return_value=None)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/notion/authorize?user_id=user_123")

    assert response.status_code == 200
    body = response.json()
    assert "url" in body
    url = body["url"]
    assert url.startswith("https://api.notion.com/v1/oauth/authorize")
    assert "owner=user" in url

    mock_redis.setex.assert_called_once()
    call_args = mock_redis.setex.call_args
    key = call_args[0][0]
    assert key.startswith("oauth_state:")


# ---------------------------------------------------------------------------
# 3. test_authorize_invalid_service_returns_400
# ---------------------------------------------------------------------------

async def test_authorize_invalid_service_returns_400():
    app = make_app()
    app.dependency_overrides[get_db] = lambda: _mock_db_gen()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/foobar/authorize?user_id=user_123")

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 4. test_callback_google_success
# ---------------------------------------------------------------------------

async def test_callback_google_success():
    app = make_app()

    mock_db = AsyncMock()

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    state_payload = json.dumps({"user_id": "user_123", "service": "google"})
    token_response = {
        "access_token": "goog_tok",
        "refresh_token": "goog_ref",
        "expires_in": 3600,
    }

    with (
        patch("app.api.oauth.redis_client") as mock_redis,
        patch("app.api.oauth.CredentialManager") as MockCredManager,
        patch("httpx.AsyncClient", return_value=_httpx_ctx_mock(token_response)),
    ):
        mock_redis.get = AsyncMock(return_value=state_payload)
        mock_redis.delete = AsyncMock(return_value=None)

        mock_cred_instance = AsyncMock()
        MockCredManager.return_value = mock_cred_instance

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            response = await client.get("/callback?state=test_state&code=auth_code")

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith("alter://oauth/callback")
    assert "service=google" in location
    assert "status=success" in location

    assert mock_cred_instance.store.call_count == 2


# ---------------------------------------------------------------------------
# 5. test_callback_notion_success
# ---------------------------------------------------------------------------

async def test_callback_notion_success():
    app = make_app()

    async def _override_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _override_db

    state_payload = json.dumps({"user_id": "user_123", "service": "notion"})
    token_response = {
        "access_token": "notion_tok",
        "workspace_id": "ws_1",
        "workspace_name": "My Workspace",
    }

    with (
        patch("app.api.oauth.redis_client") as mock_redis,
        patch("app.api.oauth.CredentialManager") as MockCredManager,
        patch("httpx.AsyncClient", return_value=_httpx_ctx_mock(token_response)),
    ):
        mock_redis.get = AsyncMock(return_value=state_payload)
        mock_redis.delete = AsyncMock(return_value=None)

        mock_cred_instance = AsyncMock()
        MockCredManager.return_value = mock_cred_instance

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            response = await client.get("/callback?state=test_state&code=auth_code")

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith("alter://oauth/callback")
    assert "service=notion" in location
    assert "status=success" in location

    assert mock_cred_instance.store.call_count == 1


# ---------------------------------------------------------------------------
# 6. test_callback_expired_state
# ---------------------------------------------------------------------------

async def test_callback_expired_state():
    app = make_app()

    async def _override_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _override_db

    with patch("app.api.oauth.redis_client") as mock_redis:
        mock_redis.get = AsyncMock(return_value=None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            response = await client.get("/callback?state=expired_state&code=whatever")

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith("alter://oauth/callback")
    assert "status=error" in location
    assert "message=state_expired" in location


# ---------------------------------------------------------------------------
# 7. test_callback_provider_error
# ---------------------------------------------------------------------------

async def test_callback_provider_error():
    app = make_app()

    async def _override_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _override_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        response = await client.get("/callback?state=x&error=access_denied")

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith("alter://oauth/callback")
    assert "status=error" in location
    assert "message=access_denied" in location


# ---------------------------------------------------------------------------
# 8. test_callback_state_deleted_before_exchange
# ---------------------------------------------------------------------------

async def test_callback_state_deleted_before_exchange():
    app = make_app()

    async def _override_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _override_db

    state_payload = json.dumps({"user_id": "user_123", "service": "google"})

    # httpx raises to simulate a failed token exchange
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("network error"))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.api.oauth.redis_client") as mock_redis,
        patch("httpx.AsyncClient", return_value=ctx),
    ):
        mock_redis.get = AsyncMock(return_value=state_payload)
        mock_redis.delete = AsyncMock(return_value=None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            response = await client.get("/callback?state=some_state&code=auth_code")

    mock_redis.delete.assert_called_once()

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith("alter://oauth/callback")
    assert "status=error" in location
    assert "message=server_error" in location


# ---------------------------------------------------------------------------
# 9. test_callback_token_exchange_failure_logs_exception
# ---------------------------------------------------------------------------

async def test_callback_token_exchange_failure_logs_exception():
    app = make_app()

    async def _override_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _override_db

    state_payload = json.dumps({"user_id": "user_123", "service": "google"})

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("token exchange rejected"))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.api.oauth.redis_client") as mock_redis,
        patch("httpx.AsyncClient", return_value=ctx),
        patch("app.api.oauth.logger") as mock_logger,
    ):
        mock_redis.get = AsyncMock(return_value=state_payload)
        mock_redis.delete = AsyncMock(return_value=None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            response = await client.get("/callback?state=some_state&code=bad_code")

    mock_logger.exception.assert_called_once()
    call_kwargs = mock_logger.exception.call_args
    assert "service" in call_kwargs.kwargs.get("extra", {})
    assert "user_id" in call_kwargs.kwargs.get("extra", {})

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert "status=error" in location
    assert "message=server_error" in location


# ---------------------------------------------------------------------------
# 11. test_disconnect_known_service
# ---------------------------------------------------------------------------

async def test_disconnect_known_service():
    app = make_app()

    mock_db = AsyncMock()

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    mock_connector = AsyncMock()
    MockConnectorClass = MagicMock(return_value=mock_connector)

    with (
        patch("app.api.oauth.CredentialManager"),
        patch("app.api.oauth._CONNECTOR_MAP", {"gmail": MockConnectorClass}),
    ):

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete("/user_123/integrations/gmail")

    assert response.status_code == 200
    assert response.json() == {"status": "disconnected"}
    mock_connector.disconnect.assert_called_once_with("user_123", mock_db)


# ---------------------------------------------------------------------------
# 12. test_disconnect_unknown_service
# ---------------------------------------------------------------------------

async def test_disconnect_unknown_service():
    app = make_app()
    app.dependency_overrides[get_db] = lambda: _mock_db_gen()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete("/user_123/integrations/foobar")

    assert response.status_code == 404
