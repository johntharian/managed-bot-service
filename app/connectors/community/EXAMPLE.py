# app/connectors/community/EXAMPLE.py
"""
Community connector template for Alter.

CONTRIBUTION CONTRACT:
1. Subclass BaseConnector
2. Set class attributes: name, display_name, token_budget
3. Implement all five abstract methods
4. Drop this file into app/connectors/community/
5. It will be auto-discovered at startup — no other changes needed

SECURITY NOTE:
Community connectors run arbitrary Python at startup. This is intentional
for self-hosted deployments where the operator controls the directory.
For hosted/multi-tenant deployments, community connectors require review
before being enabled.
"""
from app.connectors.base import (
    BaseConnector,
    ContextBlock,
    ToolDefinition,
    ToolResult,
    CredentialsExpiredError,
)
from app.connectors.credentials import CredentialManager


class ExampleConnector(BaseConnector):
    """
    A minimal example connector. Replace 'example' with your service name.
    This connector does nothing useful — it demonstrates the interface only.
    It will NOT appear in tests unless credentials are stored for a user.
    """

    name = "example"           # Unique snake_case identifier
    display_name = "Example"   # Human-readable name shown in the UI
    token_budget = 30          # Max tokens this connector may use in context

    def __init__(self, cred_manager: CredentialManager) -> None:
        super().__init__(cred_manager)

    async def connect(self, user_id: str, creds: dict, db) -> None:
        """Called when the user completes OAuth or enters an API key."""
        await self.cred_manager.store(user_id, self.name, creds, db)

    async def disconnect(self, user_id: str, db) -> None:
        """Called when the user disconnects. Soft-deletes credentials."""
        await self.cred_manager.deactivate(user_id, self.name, db)

    async def get_context(self, user_id: str, db) -> ContextBlock:
        """
        Return a short summary injected into the system prompt.
        Keep it under token_budget tokens (len(content) // 4 approximation).
        Raise CredentialsExpiredError if credentials are not available.
        """
        creds = await self.cred_manager.get(user_id, self.name, db)
        # TODO: use creds["access_token"] or similar to fetch real data
        content = "**Example service:** Connected. (Replace with real data.)"
        return ContextBlock(content=content)

    def get_tools(self) -> list[ToolDefinition]:
        """
        Return a list of tool definitions. Each dict must have:
          - name: str (unique, prefixed with your connector name, e.g. "example_do_thing")
          - description: str
          - input_schema: dict (JSON Schema "object" type)
        """
        return [
            {
                "name": "example_do_thing",
                "description": "An example tool that does something.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "param": {"type": "string", "description": "An example parameter"},
                    },
                    "required": ["param"],
                },
            },
            {
                "name": "example_get_context",
                "description": "Get a summary of the user's Example service data. Call this when context from this service is relevant.",
                "input_schema": {"type": "object", "properties": {}},
            },
        ]

    async def handle_tool_call(
        self, tool_name: str, args: dict, user_id: str, db
    ) -> ToolResult:
        """
        Execute a tool call. Return ToolResult(content=...) on success,
        ToolResult(content=None, error="...") on failure.
        """
        creds = await self.cred_manager.get(user_id, self.name, db)
        if tool_name == "example_do_thing":
            return ToolResult(content={"echo": args.get("param")})
        if tool_name == "example_get_context":
            block = await self.get_context(user_id, db)
            return ToolResult(content={"summary": block.content})
        return ToolResult(content=None, error=f"Unknown tool: {tool_name}")
