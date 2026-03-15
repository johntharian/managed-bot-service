from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional, Tuple

from app.models.integration import Integration
from app.models.bot_permission import BotPermission

class PermissionEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_permission(self, user_id: str, service: str, action: str) -> str:
        """
        Determines the permission level for a given service and action.
        Returns: 'read_only', 'ask_first', 'full_auto', or 'denied'
        """
        # 1. Fetch Integration
        stmt = select(Integration).where(Integration.user_id == user_id, Integration.service == service)
        integ = (await self.db.execute(stmt)).scalar_one_or_none()

        if not integ:
            return "denied" # Integration not connected

        # 2. Fetch specific permission
        stmt_perm = select(BotPermission).where(
            BotPermission.user_id == user_id,
            BotPermission.integration_id == integ.id,
            BotPermission.action == action
        )
        perm = (await self.db.execute(stmt_perm)).scalar_one_or_none()
        
        if perm:
            return perm.level
            
        # Default fallback
        if "read" in action:
            return "read_only"
            
        return "ask_first" # Safe default for state-mutating actions without explicit rules
