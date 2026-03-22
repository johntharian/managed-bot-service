# app/connectors/builtin/obsidian.py
import httpx

from app.connectors.base import BaseConnector, ContextBlock, ToolDefinition, ToolResult
from app.connectors.credentials import CredentialManager


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


class ObsidianConnector(BaseConnector):
    name = "obsidian"
    display_name = "Obsidian"
    token_budget = 60

    def __init__(self, cred_manager: CredentialManager) -> None:
        super().__init__(cred_manager)

    async def connect(self, user_id: str, creds: dict, db) -> None:
        await self.cred_manager.store(user_id, self.name, creds, db)

    async def disconnect(self, user_id: str, db) -> None:
        await self.cred_manager.deactivate(user_id, self.name, db)

    async def get_context(self, user_id: str, db) -> ContextBlock:
        creds = await self.cred_manager.get(user_id, self.name, db)
        api_key = creds["api_key"]
        base_url = creds["base_url"]

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{base_url}/vault/",
                    headers=_headers(api_key),
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError:
            return ContextBlock(content="**Obsidian:** Vault not reachable.")

        files = data.get("files", [])
        if not files:
            return ContextBlock(content="**Obsidian:** No notes found.")

        sorted_files = sorted(files, key=lambda f: f.get("modified", 0), reverse=True)
        top_files = sorted_files[:5]

        lines = [f"**Obsidian:** {len(top_files)} recently edited notes:"]
        lines.extend(f"- {f['path']}" for f in top_files)
        content = "\n".join(lines)

        return ContextBlock(content=content)

    def get_tools(self) -> list[ToolDefinition]:
        return [
            {
                "name": "obsidian_search_notes",
                "description": "Search Obsidian notes by keyword.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "obsidian_read_note",
                "description": "Read the content of an Obsidian note by its path.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the note (e.g. 'Daily/2026-03-22.md')"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "obsidian_create_note",
                "description": "Create a new Obsidian note with the given title and content.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Note title (without .md extension)"},
                        "content": {"type": "string", "description": "Markdown content for the note"},
                        "folder": {"type": "string", "description": "Optional folder path to place the note in"},
                    },
                    "required": ["title", "content"],
                },
            },
            {
                "name": "obsidian_append_to_note",
                "description": "Append text to an existing Obsidian note.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the note (e.g. 'Daily/2026-03-22.md')"},
                        "content": {"type": "string", "description": "Markdown content to append"},
                    },
                    "required": ["path", "content"],
                },
            },
        ]

    async def handle_tool_call(self, tool_name: str, args: dict, user_id: str, db) -> ToolResult:
        creds = await self.cred_manager.get(user_id, self.name, db)
        api_key = creds["api_key"]
        base_url = creds["base_url"]

        async with httpx.AsyncClient() as client:
            if tool_name == "obsidian_search_notes":
                query = args["query"]
                resp = await client.post(
                    f"{base_url}/search/simple",
                    headers={"Authorization": f"Bearer {api_key}"},
                    params={"query": query},
                )
                resp.raise_for_status()
                return ToolResult(content=resp.json())

            if tool_name == "obsidian_read_note":
                path = args["path"]
                resp = await client.get(
                    f"{base_url}/vault/{path}",
                    headers=_headers(api_key),
                )
                resp.raise_for_status()
                return ToolResult(content=resp.text)

            if tool_name == "obsidian_create_note":
                title = args["title"].replace("/", "-").replace("..", "")
                content = args["content"]
                folder = args.get("folder")
                if folder:
                    folder = folder.replace("..", "").strip("/")
                    note_path = f"{folder}/{title}.md"
                else:
                    note_path = f"{title}.md"
                resp = await client.put(
                    f"{base_url}/vault/{note_path}",
                    headers=_headers(api_key),
                    content=content.encode("utf-8"),
                )
                resp.raise_for_status()
                return ToolResult(content={"path": note_path, "created": True})

            if tool_name == "obsidian_append_to_note":
                path = args["path"]
                content = args["content"]
                headers = {**_headers(api_key), "Content-Type": "text/markdown"}
                resp = await client.post(
                    f"{base_url}/vault/{path}",
                    headers=headers,
                    content=content.encode("utf-8"),
                )
                resp.raise_for_status()
                return ToolResult(content={"path": path, "appended": True})

        return ToolResult(content=None, error=f"Unknown obsidian tool: {tool_name}")
