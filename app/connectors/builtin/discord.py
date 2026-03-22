# app/connectors/builtin/discord.py
import httpx

from app.connectors.base import BaseConnector, ContextBlock, ToolDefinition, ToolResult
from app.connectors.credentials import CredentialManager

API_BASE = "https://discord.com/api/v10"


def _headers(bot_token: str) -> dict:
    return {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json",
    }


class DiscordConnector(BaseConnector):
    name = "discord"
    display_name = "Discord"
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

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{API_BASE}/users/@me/guilds",
                    headers=_headers(bot_token),
                )
                if not resp.is_success:
                    return ContextBlock(content="**Discord:** Could not connect to Discord.")
                guilds = resp.json()
        except httpx.HTTPError:
            return ContextBlock(content="**Discord:** Could not connect to Discord.")

        if not guilds:
            return ContextBlock(content="**Discord:** Bot not in any servers.")

        top_names = [g["name"] for g in guilds[:3]]
        names_str = ", ".join(top_names)
        return ContextBlock(content=f"**Discord:** Bot active in {len(guilds)} servers: {names_str}.")

    def get_tools(self) -> list[ToolDefinition]:
        return [
            {
                "name": "discord_send_message",
                "description": "Send a message to a Discord channel.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "channel_id": {"type": "string", "description": "The ID of the channel to send the message to"},
                        "content": {"type": "string", "description": "The message content to send"},
                    },
                    "required": ["channel_id", "content"],
                },
            },
            {
                "name": "discord_get_messages",
                "description": "Retrieve recent messages from a Discord channel.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "channel_id": {"type": "string", "description": "The ID of the channel to fetch messages from"},
                        "limit": {"type": "integer", "description": "Number of messages to retrieve (default 10, max 100)"},
                    },
                    "required": ["channel_id"],
                },
            },
            {
                "name": "discord_list_guilds",
                "description": "List all Discord servers (guilds) the bot is a member of.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "discord_list_channels",
                "description": "List all channels in a Discord server (guild). Filter by type == 0 for text channels.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "The ID of the guild to list channels for"},
                    },
                    "required": ["guild_id"],
                },
            },
        ]

    async def handle_tool_call(self, tool_name: str, args: dict, user_id: str, db) -> ToolResult:
        creds = await self.cred_manager.get(user_id, self.name, db)
        bot_token = creds["bot_token"]

        async with httpx.AsyncClient() as client:
            if tool_name == "discord_send_message":
                channel_id = args["channel_id"]
                content = args["content"]
                resp = await client.post(
                    f"{API_BASE}/channels/{channel_id}/messages",
                    headers=_headers(bot_token),
                    json={"content": content},
                )
                if resp.status_code == 403:
                    return ToolResult(error="Bot lacks permissions for this channel/server.")
                if resp.status_code == 429:
                    return ToolResult(error="Discord rate limit. Try again shortly.")
                resp.raise_for_status()
                return ToolResult(content={"sent": True, "channel_id": channel_id})

            if tool_name == "discord_get_messages":
                channel_id = args["channel_id"]
                limit = min(int(args.get("limit", 10)), 100)
                resp = await client.get(
                    f"{API_BASE}/channels/{channel_id}/messages",
                    headers=_headers(bot_token),
                    params={"limit": limit},
                )
                if resp.status_code == 403:
                    return ToolResult(error="Bot lacks permissions for this channel/server.")
                if resp.status_code == 429:
                    return ToolResult(error="Discord rate limit. Try again shortly.")
                resp.raise_for_status()
                return ToolResult(content=resp.json())

            if tool_name == "discord_list_guilds":
                resp = await client.get(
                    f"{API_BASE}/users/@me/guilds",
                    headers=_headers(bot_token),
                )
                if resp.status_code == 403:
                    return ToolResult(error="Bot lacks permissions for this channel/server.")
                if resp.status_code == 429:
                    return ToolResult(error="Discord rate limit. Try again shortly.")
                resp.raise_for_status()
                return ToolResult(content=resp.json())

            if tool_name == "discord_list_channels":
                guild_id = args["guild_id"]
                resp = await client.get(
                    f"{API_BASE}/guilds/{guild_id}/channels",
                    headers=_headers(bot_token),
                )
                if resp.status_code == 403:
                    return ToolResult(error="Bot lacks permissions for this channel/server.")
                if resp.status_code == 429:
                    return ToolResult(error="Discord rate limit. Try again shortly.")
                resp.raise_for_status()
                return ToolResult(content=resp.json())

        return ToolResult(content=None, error=f"Unknown discord tool: {tool_name}")
