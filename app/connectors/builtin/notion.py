# app/connectors/builtin/notion.py
import httpx

from app.connectors.base import BaseConnector, ContextBlock, ToolDefinition, ToolResult
from app.connectors.credentials import CredentialManager

_NOTION_VERSION = "2022-06-28"
_NOTION_BASE = "https://api.notion.com/v1"


def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }


class NotionConnector(BaseConnector):
    name = "notion"
    display_name = "Notion"
    token_budget = 60

    def __init__(self, cred_manager: CredentialManager) -> None:
        super().__init__(cred_manager)

    async def connect(self, user_id: str, creds: dict, db) -> None:
        await self.cred_manager.store(user_id, self.name, creds, db)

    async def disconnect(self, user_id: str, db) -> None:
        await self.cred_manager.deactivate(user_id, self.name, db)

    async def get_context(self, user_id: str, db) -> ContextBlock:
        creds = await self.cred_manager.get(user_id, self.name, db)
        token = creds["access_token"]

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{_NOTION_BASE}/search",
                headers=_headers(token),
                json={"sort": {"direction": "descending", "timestamp": "last_edited_time"}, "page_size": 5},
            )
            resp.raise_for_status()
            data = resp.json()

        titles = []
        for item in data.get("results", []):
            props = item.get("properties", {})
            # Page title is under the "title" property (array of rich_text objects)
            title_prop = props.get("title") or props.get("Name") or {}
            rich_texts = title_prop.get("title", [])
            title = "".join(rt.get("plain_text", "") for rt in rich_texts)
            if title:
                titles.append(title)

        if not titles:
            content = "**Notion:** No recently edited pages found."
        else:
            lines = ["**Notion — recently edited pages:**"]
            lines.extend(f"- {t}" for t in titles)
            content = "\n".join(lines)

        return ContextBlock(content=content)

    def get_tools(self) -> list[ToolDefinition]:
        return [
            {
                "name": "notion_search_pages",
                "description": "Search Notion pages and databases by keyword.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "max_results": {"type": "integer", "description": "Max results (default 5)"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "notion_read_page",
                "description": "Read the content of a specific Notion page by ID.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "page_id": {"type": "string", "description": "Notion page ID"},
                    },
                    "required": ["page_id"],
                },
            },
            {
                "name": "notion_create_page",
                "description": "Create a new page in a Notion database.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "database_id": {"type": "string", "description": "Target database ID"},
                        "title": {"type": "string", "description": "Page title"},
                        "content": {"type": "string", "description": "Optional page content (plain text)"},
                    },
                    "required": ["database_id", "title"],
                },
            },
            {
                "name": "notion_get_recent_pages",
                "description": "Get the user's recently edited Notion pages. Call this when the user asks about their notes, documents, or Notion workspace.",
                "input_schema": {"type": "object", "properties": {}},
            },
        ]

    async def handle_tool_call(
        self, tool_name: str, args: dict, user_id: str, db
    ) -> ToolResult:
        creds = await self.cred_manager.get(user_id, self.name, db)
        token = creds["access_token"]

        async with httpx.AsyncClient() as client:
            if tool_name == "notion_search_pages":
                resp = await client.post(
                    f"{_NOTION_BASE}/search",
                    headers=_headers(token),
                    json={"query": args["query"], "page_size": args.get("max_results", 5)},
                )
                resp.raise_for_status()
                return ToolResult(content=resp.json())

            if tool_name == "notion_read_page":
                page_id = args["page_id"]
                # Fetch page metadata
                resp = await client.get(
                    f"{_NOTION_BASE}/pages/{page_id}", headers=_headers(token)
                )
                resp.raise_for_status()
                page = resp.json()
                # Fetch page blocks (content)
                blocks_resp = await client.get(
                    f"{_NOTION_BASE}/blocks/{page_id}/children", headers=_headers(token)
                )
                blocks_resp.raise_for_status()
                return ToolResult(content={"page": page, "blocks": blocks_resp.json()})

            if tool_name == "notion_create_page":
                body: dict = {
                    "parent": {"database_id": args["database_id"]},
                    "properties": {
                        "title": {
                            "title": [{"text": {"content": args["title"]}}]
                        }
                    },
                }
                if args.get("content"):
                    body["children"] = [
                        {
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [{"type": "text", "text": {"content": args["content"]}}]
                            },
                        }
                    ]
                resp = await client.post(
                    f"{_NOTION_BASE}/pages", headers=_headers(token), json=body
                )
                resp.raise_for_status()
                return ToolResult(content=resp.json())

        if tool_name == "notion_get_recent_pages":
            block = await self.get_context(user_id, db)
            return ToolResult(content={"pages": block.content})

        return ToolResult(content=None, error=f"Unknown notion tool: {tool_name}")
