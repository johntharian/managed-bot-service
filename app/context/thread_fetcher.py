import httpx
from typing import List, Dict, Any
from app.core.settings import settings

class BotsAppThreadFetcher:
    """
    Fetches the Level 1 history: Recent thread messages from BotsApp 
    main server directly using the BOTSAPP_SERVICE_TOKEN.
    """
    def __init__(self):
        self.api_url = settings.BOTSAPP_API_URL
        self.service_token = settings.BOTSAPP_SERVICE_TOKEN

    async def fetch_recent_messages(self, thread_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        headers = {
            "Authorization": f"Bearer {self.service_token}"
        }
        url = f"{self.api_url}/internal/threads/{thread_id}/messages?limit={limit}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                return data.get("messages", [])
            
            # Since this is MVP phase 1, we will fail cleanly if we can't extract context
            response.raise_for_status()
            return []
