from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.connectors.credentials import CredentialManager

router = APIRouter()

SUPPORTED_SERVICES = {"obsidian", "stocks", "discord", "telegram"}


class ApiKeyConnectRequest(BaseModel):
    service: str
    api_key: str
    base_url: Optional[str] = None


@router.post("/{user_id}/connect")
async def connect_apikey(
    user_id: str,
    body: ApiKeyConnectRequest,
    db: AsyncSession = Depends(get_db),
):
    if body.service not in SUPPORTED_SERVICES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported service '{body.service}'. Supported: {sorted(SUPPORTED_SERVICES)}",
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if body.service == "obsidian":
                if not body.base_url:
                    raise HTTPException(status_code=400, detail="base_url is required for obsidian.")
                response = await client.get(
                    f"{body.base_url}/",
                    headers={"Authorization": f"Bearer {body.api_key}"},
                )
                if not response.is_success:
                    raise HTTPException(
                        status_code=400,
                        detail="Could not connect to Obsidian vault. Check the API key and base URL.",
                    )

            elif body.service == "stocks":
                response = await client.get(
                    "https://finnhub.io/api/v1/quote",
                    params={"symbol": "AAPL", "token": body.api_key},
                )
                if not response.is_success:
                    raise HTTPException(status_code=400, detail="Could not validate Finnhub API key.")
                data = response.json()
                if data.get("c") == 0 and data.get("t") == 0:
                    raise HTTPException(status_code=400, detail="Finnhub API key appears invalid.")

            elif body.service == "discord":
                response = await client.get(
                    "https://discord.com/api/v10/users/@me",
                    headers={"Authorization": f"Bot {body.api_key}"},
                )
                if not response.is_success:
                    raise HTTPException(
                        status_code=400,
                        detail="Could not validate Discord bot token. Ensure the 'Bot ' prefix is not included — just the token itself.",
                    )

            elif body.service == "telegram":
                response = await client.get(
                    f"https://api.telegram.org/bot{body.api_key}/getMe",
                )
                data = response.json()
                if not data.get("ok"):
                    raise HTTPException(status_code=400, detail="Could not validate Telegram bot token.")

    except httpx.RequestError:
        raise HTTPException(
            status_code=400,
            detail=f"Could not reach {body.service} service. Check connectivity.",
        )

    # Store credentials in the correct shape per service
    cred_manager = CredentialManager()
    if body.service == "obsidian":
        creds = {"api_key": body.api_key, "base_url": body.base_url}
    elif body.service == "stocks":
        creds = {"api_key": body.api_key, "watchlist": []}
    elif body.service == "discord":
        creds = {"bot_token": body.api_key}
    elif body.service == "telegram":
        creds = {"bot_token": body.api_key}
    else:
        creds = {"api_key": body.api_key}

    await cred_manager.store(user_id, body.service, creds, db)
    return {"status": "connected"}
