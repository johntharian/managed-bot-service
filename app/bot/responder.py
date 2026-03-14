import httpx
from typing import Dict, Any
from app.core.settings import settings

class BotsAppResponder:
    """
    Responsible for posting messages BACK to the main BotsApp routing network.
    """
    def __init__(self):
        self.api_url = settings.BOTSAPP_API_URL
        self.service_token = settings.BOTSAPP_SERVICE_TOKEN

    async def send_reply(self, from_user_id: str, to_phone: str, thread_id: str, text: str):
        """
        Posts standard envelope to Bot's App /messages
        """
        payload = {
            "from_user_id": from_user_id, # BotsApp handles bot auth differently, sending internal user_id in service mode
            "to": to_phone,
            "thread_id": thread_id,
            "intent": "response",
            "payload": {"text": text}
        }
        
        headers = {
            "Authorization": f"Bearer {self.service_token}"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_url}/messages",
                json=payload,
                headers=headers
            )
            response.raise_for_status()
