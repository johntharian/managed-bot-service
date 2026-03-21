# app/connectors/credentials.py
import asyncio
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.security import encrypt_credentials, decrypt_credentials
from app.core.settings import settings
from app.models.integration import Integration
from app.connectors.base import CredentialsExpiredError


class CredentialManager:
    """
    Fetches, stores, and refreshes connector credentials.
    No persistent DB connection — takes `db` as a parameter per call.
    """

    async def get(self, user_id: str, connector_name: str, db) -> dict:
        """
        Fetch credentials from the integrations table.
        For Google connectors, refresh the token if expired.
        Returns a fresh credentials dict.
        Raises CredentialsExpiredError if integration is missing or inactive.
        """
        stmt = select(Integration).where(
            Integration.user_id == user_id,
            Integration.service == connector_name,
        )
        result = await db.execute(stmt)
        integration = result.scalar_one_or_none()

        if integration is None or not integration.active:
            raise CredentialsExpiredError(
                f"No active integration for {connector_name} (user={user_id})"
            )

        creds = decrypt_credentials(integration.encrypted_creds)

        # Google token refresh
        if connector_name in ("gmail", "gcal") and creds.get("expiry"):
            creds = await self._maybe_refresh_google(creds, integration, db)

        return creds

    async def store(
        self, user_id: str, connector_name: str, creds: dict, db
    ) -> None:
        """
        Encrypt and upsert credentials into the integrations table.
        Sets active=True on upsert.
        """
        encrypted = encrypt_credentials(creds)
        stmt = (
            pg_insert(Integration)
            .values(
                user_id=user_id,
                service=connector_name,
                encrypted_creds=encrypted,
                active=True,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "service"],
                set_={
                    "encrypted_creds": encrypted,
                    "active": True,
                },
            )
        )
        await db.execute(stmt)
        await db.commit()

    async def deactivate(self, user_id: str, connector_name: str, db) -> None:
        """Set active=False (soft delete). Credentials are retained for re-auth."""
        stmt = select(Integration).where(
            Integration.user_id == user_id,
            Integration.service == connector_name,
        )
        result = await db.execute(stmt)
        integration = result.scalar_one_or_none()
        if integration:
            integration.active = False
            await db.commit()

    async def _maybe_refresh_google(
        self, creds: dict, integration: Integration, db
    ) -> dict:
        """Refresh a Google OAuth token if it is expired. Updates DB in-place."""
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        expiry_dt = datetime.fromisoformat(creds["expiry"]).replace(tzinfo=None) if creds.get("expiry") else None
        creds_obj = Credentials(
            token=creds["access_token"],
            refresh_token=creds.get("refresh_token"),
            token_uri=creds.get("token_uri") or settings.GOOGLE_TOKEN_URI,
            client_id=creds.get("client_id") or settings.GOOGLE_CLIENT_ID,
            client_secret=creds.get("client_secret") or settings.GOOGLE_CLIENT_SECRET,
            expiry=expiry_dt,
        )

        if creds_obj.expired and creds_obj.refresh_token:
            # google.auth.transport.requests.Request is synchronous — run in thread
            await asyncio.to_thread(creds_obj.refresh, Request())
            new_creds = {
                "access_token": creds_obj.token,
                "refresh_token": creds_obj.refresh_token,
                "token_uri": creds_obj.token_uri,
                "client_id": creds_obj.client_id,
                "client_secret": creds_obj.client_secret,
                "expiry": creds_obj.expiry.isoformat() if creds_obj.expiry else None,
            }
            integration.encrypted_creds = encrypt_credentials(new_creds)
            await db.commit()
            return new_creds
        elif creds_obj.expired:
            raise CredentialsExpiredError(
                f"Token expired and no refresh_token available (connector may need re-auth)"
            )

        return creds
