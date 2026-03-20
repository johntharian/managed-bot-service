# app/connectors/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.connectors.credentials import CredentialManager


class CredentialsExpiredError(Exception):
    """Raised when credentials are missing, inactive, or cannot be refreshed."""
    pass


@dataclass
class ContextBlock:
    content: str
    token_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.token_count = len(self.content) // 4


@dataclass
class ToolResult:
    content: Any
    error: Optional[str] = None


# ToolDefinition is a plain dict matching Anthropic's tool schema:
# {"name": str, "description": str, "input_schema": {"type": "object", ...}}
ToolDefinition = dict


class BaseConnector(ABC):
    name: str           # unique identifier, e.g. "gmail"
    display_name: str   # human-readable, e.g. "Gmail"
    token_budget: int = 50  # default per-connector context token budget

    def __init__(self, cred_manager: "CredentialManager") -> None:
        self.cred_manager = cred_manager

    @abstractmethod
    async def connect(self, user_id: str, creds: dict, db) -> None:
        """Store OAuth credentials and mark integration active in DB."""
        ...

    @abstractmethod
    async def disconnect(self, user_id: str, db) -> None:
        """Soft-delete: set active=False. Does not remove credentials."""
        ...

    @abstractmethod
    async def get_context(self, user_id: str, db) -> ContextBlock:
        """Return a compact summary for the system prompt. Must respect token_budget."""
        ...

    @abstractmethod
    def get_tools(self) -> list[ToolDefinition]:
        """Return the list of tool definitions this connector exposes."""
        ...

    @abstractmethod
    async def handle_tool_call(
        self, tool_name: str, args: dict, user_id: str, db
    ) -> ToolResult:
        """Execute a tool call and return a ToolResult."""
        ...
