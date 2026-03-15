from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.models.pending_approval import PendingApproval

class ApprovalManager:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_pending_approval(self, user_id: str, action_desc: str, payload: Dict[str, Any]) -> str:
        """
        Creates a new pending approval and simulates push notification to BotsApp.
        """
        approval = PendingApproval(
            user_id=user_id,
            action_desc=action_desc,
            payload=payload,
            status="pending"
        )
        self.db.add(approval)
        await self.db.commit()
        await self.db.refresh(approval)
        
        # In a real app, this would POST an internal notification webhook to BotsApp 
        # to show up in the user's dashboard/websocket stream.
        
        return str(approval.id)
