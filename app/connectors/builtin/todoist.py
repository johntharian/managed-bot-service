import httpx
from datetime import datetime, timezone

from app.connectors.base import BaseConnector, ContextBlock, ToolDefinition, ToolResult
from app.connectors.credentials import CredentialManager

_TODOIST_BASE = "https://api.todoist.com"


def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


class TodoistConnector(BaseConnector):
    name = "todoist"
    display_name = "Todoist"
    token_budget = 50

    def __init__(self, cred_manager: CredentialManager) -> None:
        super().__init__(cred_manager)

    async def connect(self, user_id: str, creds: dict, db) -> None:
        await self.cred_manager.store(user_id, self.name, creds, db)

    async def disconnect(self, user_id: str, db) -> None:
        await self.cred_manager.deactivate(user_id, self.name, db)

    async def get_context(self, user_id: str, db) -> ContextBlock:
        creds = await self.cred_manager.get(user_id, self.name, db)
        token = creds["access_token"]
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_TODOIST_BASE}/rest/v2/tasks",
                params={"filter": "today|overdue"},
                headers=_headers(token),
            )
            resp.raise_for_status()
            tasks = resp.json()

        if not tasks:
            return ContextBlock(content="**Todoist:** No tasks due today.")

        lines = []
        for task in tasks:
            due = task.get("due")
            overdue = False
            if due:
                due_date = due.get("date", "")
                if due_date and due_date < today_str:
                    overdue = True

            label = "(overdue) " if overdue else ""
            lines.append(f"- [ ] {label}{task['content']}")

        header = f"**Todoist:** {len(tasks)} task{'s' if len(tasks) != 1 else ''} due today/overdue:"
        content = header + "\n" + "\n".join(lines)
        return ContextBlock(content=content)

    def get_tools(self) -> list[ToolDefinition]:
        return [
            {
                "name": "todoist_get_tasks",
                "description": "Retrieve tasks from Todoist. Defaults to today's and overdue tasks.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filter": {
                            "type": "string",
                            "description": "Todoist filter query. Defaults to 'today|overdue'.",
                        }
                    },
                    "required": [],
                },
            },
            {
                "name": "todoist_create_task",
                "description": "Create a new task in Todoist.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The task content/title.",
                        },
                        "due_string": {
                            "type": "string",
                            "description": "Natural language due date, e.g. 'tomorrow', 'next Monday'.",
                        },
                        "priority": {
                            "type": "integer",
                            "description": "Task priority: 1 (normal) to 4 (urgent).",
                            "minimum": 1,
                            "maximum": 4,
                        },
                        "project_name": {
                            "type": "string",
                            "description": "Name of the project to add the task to (case-insensitive lookup).",
                        },
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "todoist_complete_task",
                "description": "Mark a Todoist task as complete.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "The ID of the task to complete.",
                        }
                    },
                    "required": ["task_id"],
                },
            },
            {
                "name": "todoist_update_task",
                "description": "Update an existing Todoist task's content or due date.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "The ID of the task to update.",
                        },
                        "content": {
                            "type": "string",
                            "description": "New content/title for the task.",
                        },
                        "due_string": {
                            "type": "string",
                            "description": "New due date in natural language.",
                        },
                    },
                    "required": ["task_id"],
                },
            },
            {
                "name": "todoist_get_projects",
                "description": "Retrieve all projects from Todoist.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        ]

    async def handle_tool_call(self, tool_name: str, args: dict, user_id: str, db) -> ToolResult:
        creds = await self.cred_manager.get(user_id, self.name, db)
        token = creds["access_token"]

        async with httpx.AsyncClient() as client:
            if tool_name == "todoist_get_tasks":
                filter_query = args.get("filter", "today|overdue")
                resp = await client.get(
                    f"{_TODOIST_BASE}/rest/v2/tasks",
                    params={"filter": filter_query},
                    headers=_headers(token),
                )
                resp.raise_for_status()
                return ToolResult(content=resp.json())

            elif tool_name == "todoist_create_task":
                body: dict = {"content": args["content"]}
                if args.get("due_string") is not None:
                    body["due_string"] = args["due_string"]
                if args.get("priority") is not None:
                    body["priority"] = args["priority"]

                project_name = args.get("project_name")
                if project_name:
                    proj_resp = await client.get(
                        f"{_TODOIST_BASE}/rest/v2/projects",
                        headers=_headers(token),
                    )
                    proj_resp.raise_for_status()
                    projects = proj_resp.json()
                    matched = next(
                        (p for p in projects if p["name"].lower() == project_name.lower()),
                        None,
                    )
                    if matched:
                        body["project_id"] = matched["id"]

                resp = await client.post(
                    f"{_TODOIST_BASE}/rest/v2/tasks",
                    json=body,
                    headers=_headers(token),
                )
                resp.raise_for_status()
                return ToolResult(content=resp.json())

            elif tool_name == "todoist_complete_task":
                task_id = args["task_id"]
                resp = await client.post(
                    f"{_TODOIST_BASE}/rest/v2/tasks/{task_id}/close",
                    headers=_headers(token),
                )
                resp.raise_for_status()
                return ToolResult(content={"completed": True})

            elif tool_name == "todoist_update_task":
                task_id = args["task_id"]
                body = {}
                if args.get("content") is not None:
                    body["content"] = args["content"]
                if args.get("due_string") is not None:
                    body["due_string"] = args["due_string"]
                resp = await client.post(
                    f"{_TODOIST_BASE}/rest/v2/tasks/{task_id}",
                    json=body,
                    headers=_headers(token),
                )
                resp.raise_for_status()
                return ToolResult(content=resp.json())

            elif tool_name == "todoist_get_projects":
                resp = await client.get(
                    f"{_TODOIST_BASE}/rest/v2/projects",
                    headers=_headers(token),
                )
                resp.raise_for_status()
                return ToolResult(content=resp.json())

        return ToolResult(content=None, error=f"Unknown todoist tool: {tool_name}")
