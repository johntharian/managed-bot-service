import base64
import json
import logging
import secrets
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.core.database import get_db
from app.core.settings import settings
from app.connectors.credentials import CredentialManager
from app.connectors.builtin.gmail import GmailConnector
from app.connectors.builtin.gcal import GCalConnector
from app.connectors.builtin.notion import NotionConnector
from app.context.working_memory import redis_client

router = APIRouter()

_CONNECTOR_MAP = {
    "gmail": GmailConnector,
    "gcal": GCalConnector,
    "notion": NotionConnector,
}

_DEEP_LINK_BASE = "alter://oauth/callback"


@router.get("/{service}/authorize")
async def authorize(service: str, user_id: str):
    if service not in ("google", "notion"):
        raise HTTPException(status_code=400, detail=f"Unsupported service: {service}")

    state = secrets.token_urlsafe(32)
    await redis_client.setex(
        f"oauth_state:{state}",
        600,
        json.dumps({"user_id": user_id, "service": service}),
    )

    if service == "google":
        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.BASE_URL + "/oauth/callback",
            "scope": (
                "https://www.googleapis.com/auth/gmail.readonly "
                "https://www.googleapis.com/auth/gmail.send "
                "https://www.googleapis.com/auth/calendar"
            ),
            "access_type": "offline",
            "prompt": "consent",
            "response_type": "code",
            "state": state,
        }
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

    else:  # notion
        params = {
            "client_id": settings.NOTION_OAUTH_CLIENT_ID,
            "redirect_uri": settings.BASE_URL + "/oauth/callback",
            "response_type": "code",
            "owner": "user",
            "state": state,
        }
        auth_url = "https://api.notion.com/v1/oauth/authorize?" + urlencode(params)

    return {"url": auth_url}


@router.get("/callback")
async def callback(
    state: str,
    code: str = None,
    error: str = None,
    db: AsyncSession = Depends(get_db),
):
    if error:
        logger.warning("OAuth provider error", extra={"service": "unknown", "provider_error": error})
        return RedirectResponse(f"{_DEEP_LINK_BASE}?status=error&message={error}")

    raw = await redis_client.get(f"oauth_state:{state}")
    if raw is None:
        logger.warning("OAuth state expired or not found", extra={"state_prefix": state[:8]})
        return RedirectResponse(f"{_DEEP_LINK_BASE}?status=error&message=state_expired")

    await redis_client.delete(f"oauth_state:{state}")
    data = json.loads(raw)
    user_id = data["user_id"]
    service = data["service"]
    logger.info("OAuth callback received", extra={"service": service, "user_id": user_id})

    try:
        if service == "google":
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    settings.GOOGLE_TOKEN_URI,
                    data={
                        "code": code,
                        "client_id": settings.GOOGLE_CLIENT_ID,
                        "client_secret": settings.GOOGLE_CLIENT_SECRET,
                        "redirect_uri": settings.BASE_URL + "/oauth/callback",
                        "grant_type": "authorization_code",
                    },
                )
                resp.raise_for_status()
                token_data = resp.json()

            expiry = (
                datetime.now(timezone.utc)
                + timedelta(seconds=token_data["expires_in"])
            ).isoformat()
            creds = {
                "access_token": token_data["access_token"],
                "refresh_token": token_data.get("refresh_token"),
                "token_uri": settings.GOOGLE_TOKEN_URI,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "expiry": expiry,
            }

            cred_manager = CredentialManager()
            await cred_manager.store(user_id, "gmail", creds, db)
            await cred_manager.store(user_id, "gcal", creds, db)

            logger.info("Google OAuth success", extra={"service": "google", "user_id": user_id})
            return RedirectResponse(f"{_DEEP_LINK_BASE}?service=google&status=success")

        else:  # notion
            encoded = base64.b64encode(
                f"{settings.NOTION_OAUTH_CLIENT_ID}:{settings.NOTION_OAUTH_CLIENT_SECRET}".encode()
            ).decode()

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.notion.com/v1/oauth/token",
                    headers={"Authorization": f"Basic {encoded}"},
                    json={
                        "code": code,
                        "grant_type": "authorization_code",
                        "redirect_uri": settings.BASE_URL + "/oauth/callback",
                    },
                )
                resp.raise_for_status()
                token_data = resp.json()

            creds = {
                "access_token": token_data["access_token"],
                "workspace_id": token_data.get("workspace_id"),
                "workspace_name": token_data.get("workspace_name"),
            }

            await CredentialManager().store(user_id, "notion", creds, db)

            logger.info("Notion OAuth success", extra={"service": "notion", "user_id": user_id})
            return RedirectResponse(f"{_DEEP_LINK_BASE}?service=notion&status=success")

    except Exception as exc:
        logger.exception("OAuth token exchange failed", extra={"service": service, "user_id": user_id})
        return RedirectResponse(f"{_DEEP_LINK_BASE}?status=error&message=server_error")


@router.delete("/{user_id}/integrations/{service}")
async def disconnect_integration(
    user_id: str, service: str, db: AsyncSession = Depends(get_db)
):
    ConnectorClass = _CONNECTOR_MAP.get(service)
    if ConnectorClass is None:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")

    connector = ConnectorClass(CredentialManager())
    await connector.disconnect(user_id, db)
    return {"status": "disconnected"}
