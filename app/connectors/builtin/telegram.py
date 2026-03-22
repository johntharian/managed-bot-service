# app/connectors/builtin/telegram.py
import httpx

from app.connectors.base import BaseConnector, ContextBlock, ToolDefinition, ToolResult
from app.connectors.credentials import CredentialManager


class TelegramConnector(BaseConnector):
    name = "telegram"
    display_name = "Telegram"
    token_budget = 50

    def __init__(self, cred_manager: CredentialManager) -> None:
        super().__init__(cred_manager)

    async def connect(self, user_id: str, creds: dict, db) -> None:
        await self.cred_manager.store(user_id, self.name, creds, db)

    async def disconnect(self, user_id: str, db) -> None:
        await self.cred_manager.deactivate(user_id, self.name, db)

    async def get_context(self, user_id: str, db) -> ContextBlock:
        creds = await self.cred_manager.get(user_id, self.name, db)
        bot_token = creds["bot_token"]
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, params={"limit": 5, "offset": -5})
                data = resp.json()
        except httpx.HTTPError:
            return ContextBlock(content="**Telegram:** Could not connect to Telegram.")

        if not data.get("ok"):
            return ContextBlock(content="**Telegram:** Could not retrieve updates.")

        result = data["result"]
        count = len(result)
        if count == 0:
            return ContextBlock(content="**Telegram:** No recent messages.")

        return ContextBlock(content=f"**Telegram:** {count} recent messages in your bot.")

    def get_tools(self) -> list[ToolDefinition]:
        return [
            {
                "name": "telegram_send_message",
                "description": (
                    "Send a message to a Telegram chat. "
                    "For group chats, chat_id is a negative integer (e.g. -1001234567890)."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "chat_id": {
                            "type": "string",
                            "description": "The chat ID to send the message to. Group chat IDs are negative integers.",
                        },
                        "text": {
                            "type": "string",
                            "description": "The message text to send.",
                        },
                    },
                    "required": ["chat_id", "text"],
                },
            },
            {
                "name": "telegram_get_updates",
                "description": (
                    "Retrieve recent updates (messages) for the bot. "
                    "Note: this does not advance the offset, so the same updates may be returned on subsequent calls."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Number of updates to retrieve (default: 10).",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "telegram_get_chat",
                "description": "Get information about a Telegram chat by its chat ID.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "chat_id": {
                            "type": "string",
                            "description": "The chat ID to look up.",
                        },
                    },
                    "required": ["chat_id"],
                },
            },
        ]

    async def handle_tool_call(self, tool_name: str, args: dict, user_id: str, db) -> ToolResult:
        creds = await self.cred_manager.get(user_id, self.name, db)
        bot_token = creds["bot_token"]
        base = f"https://api.telegram.org/bot{bot_token}"

        async with httpx.AsyncClient() as client:
            if tool_name == "telegram_send_message":
                resp = await client.post(
                    f"{base}/sendMessage",
                    json={"chat_id": args["chat_id"], "text": args["text"]},
                )
                data = resp.json()
                if not data.get("ok"):
                    return ToolResult(content=None, error=data.get("description", "Telegram API error"))
                return ToolResult(content={"sent": True, "chat_id": args["chat_id"]})

            if tool_name == "telegram_get_updates":
                limit = args.get("limit", 10)
                resp = await client.get(f"{base}/getUpdates", params={"limit": limit})
                data = resp.json()
                if not data.get("ok"):
                    return ToolResult(content=None, error=data.get("description", "Telegram API error"))
                return ToolResult(content=data["result"])

            if tool_name == "telegram_get_chat":
                resp = await client.get(f"{base}/getChat", params={"chat_id": args["chat_id"]})
                data = resp.json()
                if not data.get("ok"):
                    return ToolResult(content=None, error=data.get("description", "Telegram API error"))
                return ToolResult(content=data["result"])

        return ToolResult(content=None, error=f"Unknown telegram tool: {tool_name}")
