# app/connectors/builtin/slack.py
import httpx

from app.connectors.base import BaseConnector, ContextBlock, ToolDefinition, ToolResult
from app.connectors.credentials import CredentialManager

API_BASE = "https://slack.com/api"


def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


class SlackConnector(BaseConnector):
    name = "slack"
    display_name = "Slack"
    token_budget = 60

    def __init__(self, cred_manager: CredentialManager) -> None:
        super().__init__(cred_manager)

    async def connect(self, user_id: str, creds: dict, db) -> None:
        await self.cred_manager.store(user_id, self.name, creds, db)

    async def disconnect(self, user_id: str, db) -> None:
        await self.cred_manager.deactivate(user_id, self.name, db)

    async def get_context(self, user_id: str, db) -> ContextBlock:
        creds = await self.cred_manager.get(user_id, self.name, db)
        access_token = creds["access_token"]

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{API_BASE}/conversations.list",
                    headers=_headers(access_token),
                    params={
                        "limit": 10,
                        "exclude_archived": "true",
                        "types": "public_channel,private_channel",
                    },
                )
                data = resp.json()
        except httpx.HTTPError:
            return ContextBlock(content="**Slack:** Connected but could not load channels.")

        if not data.get("ok"):
            return ContextBlock(content="**Slack:** Connected but could not load channels.")

        channels = data.get("channels", [])
        if not channels:
            return ContextBlock(content="**Slack:** No channels found.")

        total_count = len(channels)
        top_names = [f"#{ch['name']}" for ch in channels[:3]]
        names_str = ", ".join(top_names)

        return ContextBlock(content=f"**Slack:** {total_count} channels. Recent: {names_str}.")

    def get_tools(self) -> list[ToolDefinition]:
        return [
            {
                "name": "slack_send_message",
                "description": "Send a message to a Slack channel.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string", "description": "Channel ID or name (e.g. '#general' or 'C1234567890')"},
                        "text": {"type": "string", "description": "Message text to send"},
                    },
                    "required": ["channel", "text"],
                },
            },
            {
                "name": "slack_get_messages",
                "description": "Retrieve recent messages from a Slack channel. Optionally specify a limit (default 10).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string", "description": "Channel ID (e.g. 'C1234567890')"},
                        "limit": {"type": "integer", "description": "Number of messages to retrieve (default 10)"},
                    },
                    "required": ["channel"],
                },
            },
            {
                "name": "slack_list_channels",
                "description": "List all non-archived Slack channels (public and private).",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "slack_get_user_info",
                "description": "Get information about the authenticated Slack user.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        ]

    async def handle_tool_call(self, tool_name: str, args: dict, user_id: str, db) -> ToolResult:
        creds = await self.cred_manager.get(user_id, self.name, db)
        access_token = creds["access_token"]

        async with httpx.AsyncClient() as client:
            if tool_name == "slack_send_message":
                channel = args["channel"]
                text = args["text"]
                resp = await client.post(
                    f"{API_BASE}/chat.postMessage",
                    headers=_headers(access_token),
                    json={"channel": channel, "text": text},
                )
                data = resp.json()
                if not data.get("ok"):
                    return ToolResult(content=None, error=data.get("error", "Slack API error"))
                return ToolResult(content={"ok": True, "channel": channel})

            if tool_name == "slack_get_messages":
                channel = args["channel"]
                limit = args.get("limit", 10)
                resp = await client.get(
                    f"{API_BASE}/conversations.history",
                    headers=_headers(access_token),
                    params={"channel": channel, "limit": limit},
                )
                data = resp.json()
                if not data.get("ok"):
                    return ToolResult(content=None, error=data.get("error", "Slack API error"))
                return ToolResult(content=data.get("messages", []))

            if tool_name == "slack_list_channels":
                resp = await client.get(
                    f"{API_BASE}/conversations.list",
                    headers=_headers(access_token),
                    params={
                        "exclude_archived": "true",
                        "types": "public_channel,private_channel",
                    },
                )
                data = resp.json()
                if not data.get("ok"):
                    return ToolResult(content=None, error=data.get("error", "Slack API error"))
                return ToolResult(content=data.get("channels", []))

            if tool_name == "slack_get_user_info":
                resp = await client.get(
                    f"{API_BASE}/users.identity",
                    headers=_headers(access_token),
                )
                data = resp.json()
                if not data.get("ok"):
                    return ToolResult(content=None, error=data.get("error", "Slack API error"))
                return ToolResult(content=data.get("user", {}))

        return ToolResult(content=None, error=f"Unknown slack tool: {tool_name}")
