import httpx

from app.core.settings import settings
from app.core.logger import logger


class AlterResponder:
    """
    Posts replies back to the Alter Go server, which routes them through
    its RabbitMQ delivery pipeline.
    """
    def __init__(self):
        self.server_url = settings.ALTER_SERVER_URL
        self.service_token = settings.ALTER_SERVICE_TOKEN

    async def send_reply(self, sender_user_id: str, recipient_phone: str, content: str, intent: str = "reply") -> None:
        payload = {
            "sender_user_id": sender_user_id,
            "to": recipient_phone,
            "intent": intent,
            "payload": {"text": content},
        }
        headers = {"X-Service-Token": self.service_token}

        logger.info("Sending reply to Alter", sender_user_id=sender_user_id, recipient=recipient_phone, intent=intent)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self.server_url}/messages",
                json=payload,
                headers=headers,
            )

        if not response.is_success:
            logger.error(
                "Failed to send reply to Alter",
                status_code=response.status_code,
                body=response.text,
            )
            response.raise_for_status()
        
        logger.info("Reply sent successfully", status_code=response.status_code)
