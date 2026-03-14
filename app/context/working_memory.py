import json
from typing import Dict, Any, List
import redis.asyncio as redis
from app.core.settings import settings

redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

class WorkingMemory:
    """
    Level 2: Working Memory (Redis).
    Maintains transient conversation state, like what actions were attempted,
    current intents, etc. 
    TTL of 4 hours.
    """
    TTL_SECONDS = 4 * 60 * 60

    @staticmethod
    def get_key(user_id: str, thread_id: str) -> str:
        return f"context:{user_id}:{thread_id}"

    async def get_state(self, user_id: str, thread_id: str) -> List[Dict[str, Any]]:
        key = self.get_key(user_id, thread_id)
        data = await redis_client.get(key)
        if data:
            return json.loads(data)
        return []

    async def append_event(self, user_id: str, thread_id: str, event: Dict[str, Any]):
        key = self.get_key(user_id, thread_id)
        state = await self.get_state(user_id, thread_id)
        state.append(event)
        
        await redis_client.setex(
            key, 
            self.TTL_SECONDS, 
            json.dumps(state)
        )
        
    async def clear_state(self, user_id: str, thread_id: str):
        key = self.get_key(user_id, thread_id)
        await redis_client.delete(key)
