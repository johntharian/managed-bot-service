# app/connectors/registry.py
import importlib
import logging
import pkgutil
import inspect
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update

from app.connectors.base import BaseConnector, ContextBlock, ToolResult, ToolDefinition
from app.connectors.credentials import CredentialManager
from app.models.integration import Integration

_TOKEN_CAP = 200

_registry: Optional["ConnectorRegistry"] = None


def get_registry() -> "ConnectorRegistry":
    """Module-level singleton factory. Thread-safe for single-process startup."""
    global _registry
    if _registry is None:
        cred_manager = CredentialManager()
        _registry = ConnectorRegistry(cred_manager)
        _registry.discover()
    return _registry


class ConnectorRegistry:
    def __init__(self, cred_manager: CredentialManager) -> None:
        self.cred_manager = cred_manager
        # connector_name -> BaseConnector instance
        self._connectors: dict[str, BaseConnector] = {}
        # tool_name -> connector_name
        self._tool_map: dict[str, str] = {}

    def discover(self) -> None:
        """
        Scan app/connectors/builtin/ and app/connectors/community/ for BaseConnector
        subclasses. Instantiates each with self.cred_manager.
        """
        import app.connectors.builtin as builtin_pkg
        import app.connectors.community as community_pkg

        for pkg in (builtin_pkg, community_pkg):
            for _finder, module_name, _ispkg in pkgutil.iter_modules(pkg.__path__):
                full_name = f"{pkg.__name__}.{module_name}"
                try:
                    module = importlib.import_module(full_name)
                except Exception as exc:
                    # Community connectors may fail — log and continue
                    logging.getLogger(__name__).warning(
                        "Failed to load connector module %s: %s", full_name, exc
                    )
                    continue
                for _name, obj in inspect.getmembers(module, inspect.isclass):
                    if (
                        issubclass(obj, BaseConnector)
                        and obj is not BaseConnector
                        and hasattr(obj, "name")
                    ):
                        instance = obj(self.cred_manager)
                        self._connectors[obj.name] = instance
                        for tool in instance.get_tools():
                            self._tool_map[tool["name"]] = obj.name

    def get_connector(self, name: str) -> Optional[BaseConnector]:
        return self._connectors.get(name)

    async def get_active_context(self, user_id: str, db) -> str:
        """
        Returns a combined connector context string, capped at 200 tokens total.
        Connectors are sorted by last_used_at DESC NULLS LAST.
        If adding a connector would exceed the cap it is excluded entirely.
        """
        # Fetch all active integrations sorted by last_used_at
        stmt = (
            select(Integration)
            .where(Integration.user_id == user_id, Integration.active == True)
            .order_by(Integration.last_used_at.desc().nullslast())
        )
        result = await db.execute(stmt)
        active_integrations = result.scalars().all()

        blocks: list[str] = []
        tokens_used = 0

        for integration in active_integrations:
            connector = self._connectors.get(integration.service)
            if connector is None:
                continue
            try:
                block: ContextBlock = await connector.get_context(user_id, db)
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "get_context failed for %s: %s", integration.service, exc, exc_info=True
                )
                continue
            if tokens_used + block.token_count > _TOKEN_CAP:
                # Drop entirely — never truncate mid-sentence
                continue
            blocks.append(block.content)
            tokens_used += block.token_count

        if not blocks:
            return ""
        return "## Connected Services\n" + "\n\n".join(blocks)

    async def get_tools_for_user(self, user_id: str, db) -> list[ToolDefinition]:
        """Returns merged tool list for all active connectors the user has connected."""
        stmt = select(Integration).where(
            Integration.user_id == user_id, Integration.active == True
        )
        result = await db.execute(stmt)
        active_services = {row.service for row in result.scalars().all()}

        tools: list[ToolDefinition] = []
        for service in active_services:
            connector = self._connectors.get(service)
            if connector:
                tools.extend(connector.get_tools())
        return tools

    async def dispatch_tool(
        self, tool_name: str, args: dict, user_id: str, db
    ) -> ToolResult:
        """Route a tool call to the correct connector. Updates last_used_at."""
        connector_name = self._tool_map.get(tool_name)
        if connector_name is None:
            return ToolResult(content=None, error=f"Unknown tool: {tool_name}")

        connector = self._connectors[connector_name]
        result = await connector.handle_tool_call(tool_name, args, user_id, db)

        # Update last_used_at on the integration row
        await db.execute(
            update(Integration)
            .where(Integration.user_id == user_id, Integration.service == connector_name)
            .values(last_used_at=datetime.now(timezone.utc))
        )
        await db.commit()

        return result
