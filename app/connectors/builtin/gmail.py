# app/connectors/builtin/gmail.py
import base64
import email as email_lib
from typing import Any

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from app.core.settings import settings

from app.connectors.base import BaseConnector, ContextBlock, ToolDefinition, ToolResult
from app.connectors.credentials import CredentialManager


def _build_service(creds_dict: dict):
    creds_obj = Credentials(
        token=creds_dict["access_token"],
        refresh_token=creds_dict.get("refresh_token"),
        token_uri=creds_dict.get("token_uri") or settings.GOOGLE_TOKEN_URI,
        client_id=creds_dict.get("client_id") or settings.GOOGLE_CLIENT_ID,
        client_secret=creds_dict.get("client_secret") or settings.GOOGLE_CLIENT_SECRET,
    )
    return build("gmail", "v1", credentials=creds_obj)


class GmailConnector(BaseConnector):
    name = "gmail"
    display_name = "Gmail"
    token_budget = 80

    def __init__(self, cred_manager: CredentialManager) -> None:
        super().__init__(cred_manager)

    async def connect(self, user_id: str, creds: dict, db) -> None:
        await self.cred_manager.store(user_id, self.name, creds, db)

    async def disconnect(self, user_id: str, db) -> None:
        await self.cred_manager.deactivate(user_id, self.name, db)

    async def get_context(self, user_id: str, db) -> ContextBlock:
        creds = await self.cred_manager.get(user_id, self.name, db)
        service = _build_service(creds)

        # Unread count
        profile = service.users().getProfile(userId="me").execute()
        unread = profile.get("messagesUnread", 0)

        # 3 most recent subject lines
        list_result = service.users().messages().list(
            userId="me", maxResults=3, labelIds=["INBOX"]
        ).execute()
        messages = list_result.get("messages", [])
        subjects = []
        for msg in messages:
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["Subject"]
            ).execute()
            for header in detail.get("payload", {}).get("headers", []):
                if header["name"] == "Subject":
                    subjects.append(header["value"])
                    break

        lines = [f"**Gmail:** {unread} unread message(s)"]
        if subjects:
            lines.append("Recent subjects:")
            lines.extend(f"- {s}" for s in subjects)
        content = "\n".join(lines)
        return ContextBlock(content=content)

    def get_tools(self) -> list[ToolDefinition]:
        return [
            {
                "name": "gmail_read_email",
                "description": "Read the content of a specific Gmail message by ID.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string", "description": "Gmail message ID"}
                    },
                    "required": ["message_id"],
                },
            },
            {
                "name": "gmail_send_email",
                "description": "Send an email from the user's Gmail account.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["to", "subject", "body"],
                },
            },
            {
                "name": "gmail_search_emails",
                "description": "Search Gmail messages using a Gmail query string.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Gmail search query, e.g. 'from:boss@example.com'"},
                        "max_results": {"type": "integer", "description": "Maximum number of results (default 5)"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "gmail_get_inbox_summary",
                "description": "Get a summary of the user's Gmail inbox: unread count and recent email subjects. Call this when the user asks about emails, their inbox, or when you need email context.",
                "input_schema": {"type": "object", "properties": {}},
            },
        ]

    async def handle_tool_call(
        self, tool_name: str, args: dict, user_id: str, db
    ) -> ToolResult:
        creds = await self.cred_manager.get(user_id, self.name, db)
        service = _build_service(creds)

        if tool_name == "gmail_read_email":
            msg_id = args["message_id"]
            detail = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()
            snippet = detail.get("snippet", "")
            return ToolResult(content={"message_id": msg_id, "snippet": snippet})

        if tool_name == "gmail_send_email":
            import email.mime.text
            import email.mime.multipart
            msg = email.mime.multipart.MIMEMultipart()
            msg["To"] = args["to"]
            msg["Subject"] = args["subject"]
            msg.attach(email.mime.text.MIMEText(args["body"], "plain"))
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            result = service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
            return ToolResult(content={"status": "sent", "id": result.get("id")})

        if tool_name == "gmail_search_emails":
            max_results = args.get("max_results", 5)
            result = service.users().messages().list(
                userId="me", q=args["query"], maxResults=max_results
            ).execute()
            messages = result.get("messages", [])
            return ToolResult(content={"messages": messages, "count": len(messages)})

        if tool_name == "gmail_get_inbox_summary":
            block = await self.get_context(user_id, db)
            return ToolResult(content={"summary": block.content})

        return ToolResult(content=None, error=f"Unknown gmail tool: {tool_name}")
