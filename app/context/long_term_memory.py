from typing import Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import uuid

from app.models.user_memory import UserMemory

class LongTermMemory:
    """
    Level 3: Long Term Database Profile Preferences Memory.
    """
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all_for_user(self, user_id: str) -> Dict[str, str]:
        stmt = select(UserMemory).where(UserMemory.user_id == uuid.UUID(user_id))
        result = await self.db.execute(stmt)
        memories = result.scalars().all()
        
        return {m.key: m.value for m in memories}

    async def upsert(self, user_id: str, key: str, value: str):
        uid = uuid.UUID(user_id)
        stmt = select(UserMemory).where(UserMemory.user_id == uid, UserMemory.key == key)
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            existing.value = value
        else:
            new_mem = UserMemory(user_id=uid, key=key, value=value)
            self.db.add(new_mem)
            
        await self.db.commit()
