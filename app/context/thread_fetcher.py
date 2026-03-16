import httpx
from typing import List, Dict, Any

from app.core.settings import settings
from app.core.logger import logger


class BotsAppThreadFetcher:
    """
    Fetches Level 1 history: recent thread messages from the BotsApp Go server.
    """
    def __init__(self):
        self.server_url = settings.BOTSAPP_SERVER_URL
        self.service_token = settings.BOTSAPP_SERVICE_TOKEN

    async def fetch_thread_history(self, thread_id: str, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        headers = {"X-Service-Token": self.service_token}
        url = f"{self.server_url}/internal/threads/{thread_id}/messages?limit={limit}"

        try:
            logger.info("Fetching thread history", thread_id=thread_id, user_id=user_id, url=url)
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                messages = response.json()
                logger.info("Fetched thread history successfully", thread_id=thread_id, message_count=len(messages))
                return messages
        except Exception as e:
            logger.error("Failed to fetch thread history", thread_id=thread_id, user_id=user_id, error=str(e))
            return []
