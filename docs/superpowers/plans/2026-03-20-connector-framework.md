# Connector Framework Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a thin, auto-discoverable connector framework that wires external service APIs (Gmail, Google Calendar, Notion) into the bot's context assembly and tool execution pipeline. All connectors share a common interface; new connectors can be dropped into `app/connectors/community/` with zero framework changes.

**Architecture:** A `BaseConnector` ABC defines the contract. A `CredentialManager` handles encrypted storage and transparent token refresh. A singleton `ConnectorRegistry` auto-discovers connectors at startup, aggregates context up to a 200-token cap (sorted by `last_used_at DESC`), and routes tool calls. The assembler appends connector context to the system prompt; the orchestrator replaces hardcoded tool lists with registry-sourced ones.

**Tech Stack:** Python/FastAPI, SQLAlchemy async (asyncpg), Alembic, google-api-python-client, google-auth-oauthlib, httpx, pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-03-19-bot-persona-triage-connectors-design.md` (Phase 2, lines 148–275)

---

## File Map

### New files
| File | Responsibility |
|------|----------------|
| `app/connectors/__init__.py` | Package marker |
| `app/connectors/base.py` | `BaseConnector` ABC + supporting types (`ContextBlock`, `ToolResult`, `CredentialsExpiredError`) |
| `app/connectors/credentials.py` | `CredentialManager` — fetch, store, deactivate, auto-refresh Google tokens |
| `app/connectors/registry.py` | `ConnectorRegistry` singleton — discovery, context aggregation, tool dispatch |
| `app/connectors/builtin/__init__.py` | Package marker |
| `app/connectors/builtin/gmail.py` | Full Gmail connector (replaces stub) |
| `app/connectors/builtin/gcal.py` | Full Google Calendar connector (replaces stub) |
| `app/connectors/builtin/notion.py` | Notion connector |
| `app/connectors/community/__init__.py` | Package marker |
| `app/connectors/community/EXAMPLE.py` | Annotated community template |
| `tests/connectors/__init__.py` | Package marker |
| `tests/connectors/test_credentials.py` | Unit tests for CredentialManager |
| `tests/connectors/test_registry.py` | Unit tests for registry discovery, context cap, dispatch |
| `tests/connectors/test_gmail.py` | Unit tests for GmailConnector (Google API mocked) |
| `tests/connectors/test_gcal.py` | Unit tests for GCalConnector (Google API mocked) |
| `tests/connectors/test_notion.py` | Unit tests for NotionConnector (httpx mocked) |
| `tests/connectors/test_assembler_connectors.py` | Integration test: connector context appears in system prompt |
| `tests/connectors/test_orchestrator_registry.py` | Integration test: orchestrator uses registry tools + dispatch |

### Modified files
| File | Change |
|------|--------|
| `app/models/integration.py` | Add `active` (Boolean) and `last_used_at` (DateTime) columns |
| `app/models/__init__.py` | No change needed — Integration already imported |
| `app/core/settings.py` | Add 5 optional OAuth settings |
| `app/context/assembler.py` | Append connector context block to system prompt in `assemble()` |
| `app/bot/orchestrator.py` | Replace hardcoded tools + direct connector calls with registry |
| `app/bot/gemini_adapter.py` | Accept dynamic tool list (already does — no change needed) |

### Deleted files
| File | Reason |
|------|--------|
| `app/connectors/gmail.py` | Replaced by `app/connectors/builtin/gmail.py` |
| `app/connectors/gcal.py` | Replaced by `app/connectors/builtin/gcal.py` |

### Migration
| File | Change |
|------|--------|
| `alembic/versions/<rev>_add_integration_active_last_used.py` | `op.add_column` — `active` Boolean + `last_used_at` DateTime on `integrations` table |

---

## Chunk 1: Framework Core

### Step 1.1 — Alembic migration: add `active` and `last_used_at` to `integrations`

- [ ] Generate a new migration file at `alembic/versions/<new_rev>_add_integration_active_last_used.py`.

  The revision ID should be a short hex string (e.g. `b9c1d2e3f4a5`). Set `down_revision` to `'f4780f4e9fa2'` (the current head — the persona tables migration).

  ```python
  """add active and last_used_at to integrations

  Revision ID: b9c1d2e3f4a5
  Revises: f4780f4e9fa2
  Create Date: 2026-03-20 00:00:00.000000
  """
  from typing import Sequence, Union
  from alembic import op
  import sqlalchemy as sa

  revision: str = 'b9c1d2e3f4a5'
  down_revision: Union[str, Sequence[str], None] = 'f4780f4e9fa2'
  branch_labels: Union[str, Sequence[str], None] = None
  depends_on: Union[str, Sequence[str], None] = None


  def upgrade() -> None:
      op.add_column(
          'integrations',
          sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true'))
      )
      op.add_column(
          'integrations',
          sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True)
      )


  def downgrade() -> None:
      op.drop_column('integrations', 'last_used_at')
      op.drop_column('integrations', 'active')
  ```

  **Why `server_default`:** Existing rows in the `integrations` table have no `active` value. Using `server_default=sa.text('true')` means Postgres fills existing rows as `true` (opt-in by default), avoiding a NOT NULL constraint violation. `last_used_at` is nullable so existing rows get NULL with no issue.

### Step 1.2 — Update `Integration` model

- [ ] Edit `app/models/integration.py` to add the two new columns. The final file:

  ```python
  import uuid
  from sqlalchemy import Column, String, DateTime, ForeignKey, func, ARRAY, Boolean
  from sqlalchemy.dialects.postgresql import UUID
  from sqlalchemy.orm import relationship
  from app.models import Base

  class Integration(Base):
      __tablename__ = "integrations"

      id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
      user_id = Column(String, ForeignKey("managed_bot_users.user_id"), nullable=False)
      service = Column(String, nullable=False)  # e.g., 'gmail', 'gcal'
      encrypted_creds = Column(String, nullable=False)  # AES-256 encrypted JSON
      scopes = Column(ARRAY(String))
      connected_at = Column(DateTime(timezone=True), server_default=func.now())
      active = Column(Boolean, nullable=False, server_default="true")
      last_used_at = Column(DateTime(timezone=True), nullable=True)

      user = relationship("User", back_populates="integrations")
      permissions = relationship("BotPermission", back_populates="integration", cascade="all, delete-orphan")
  ```

### Step 1.3 — Add OAuth settings to `app/core/settings.py`

- [ ] Edit `app/core/settings.py`. Add five optional fields after `GEMINI_API_KEY`:

  ```python
  # Google OAuth
  GOOGLE_CLIENT_ID: str = ""
  GOOGLE_CLIENT_SECRET: str = ""
  GOOGLE_TOKEN_URI: str = "https://oauth2.googleapis.com/token"

  # Notion OAuth
  NOTION_OAUTH_CLIENT_ID: str = ""
  NOTION_OAUTH_CLIENT_SECRET: str = ""
  ```

  All five have empty-string (or string) defaults so the service starts without them set.

### Step 1.4 — Create `app/connectors/__init__.py`

- [ ] Create an empty file `app/connectors/__init__.py`.

  (The `app/connectors/` directory already exists with the stub files; we just need the package marker.)

### Step 1.5 — Create `app/connectors/base.py`

- [ ] Create `app/connectors/base.py`:

  ```python
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
  ```

### Step 1.6 — Create `app/connectors/credentials.py`

- [ ] Create `app/connectors/credentials.py`:

  ```python
  # app/connectors/credentials.py
  from datetime import datetime, timezone
  from sqlalchemy import select
  from sqlalchemy.dialects.postgresql import insert as pg_insert

  from app.core.security import encrypt_credentials, decrypt_credentials
  from app.core.settings import settings
  from app.models.integration import Integration
  from app.connectors.base import CredentialsExpiredError


  class CredentialManager:
      """
      Fetches, stores, and refreshes connector credentials.
      No persistent DB connection — takes `db` as a parameter per call.
      """

      async def get(self, user_id: str, connector_name: str, db) -> dict:
          """
          Fetch credentials from the integrations table.
          For Google connectors, refresh the token if expired.
          Returns a fresh credentials dict.
          Raises CredentialsExpiredError if integration is missing or inactive.
          """
          stmt = select(Integration).where(
              Integration.user_id == user_id,
              Integration.service == connector_name,
          )
          result = await db.execute(stmt)
          integration = result.scalar_one_or_none()

          if integration is None or not integration.active:
              raise CredentialsExpiredError(
                  f"No active integration for {connector_name} (user={user_id})"
              )

          creds = decrypt_credentials(integration.encrypted_creds)

          # Google token refresh
          if connector_name in ("gmail", "gcal") and creds.get("expiry"):
              creds = await self._maybe_refresh_google(creds, integration, db)

          return creds

      async def store(
          self, user_id: str, connector_name: str, creds: dict, db
      ) -> None:
          """
          Encrypt and upsert credentials into the integrations table.
          Sets active=True on upsert.
          """
          encrypted = encrypt_credentials(creds)
          stmt = (
              pg_insert(Integration)
              .values(
                  user_id=user_id,
                  service=connector_name,
                  encrypted_creds=encrypted,
                  active=True,
              )
              .on_conflict_do_update(
                  index_elements=["user_id", "service"],
                  set_={
                      "encrypted_creds": encrypted,
                      "active": True,
                  },
              )
          )
          await db.execute(stmt)
          await db.commit()

      async def deactivate(self, user_id: str, connector_name: str, db) -> None:
          """Set active=False (soft delete). Credentials are retained for re-auth."""
          stmt = select(Integration).where(
              Integration.user_id == user_id,
              Integration.service == connector_name,
          )
          result = await db.execute(stmt)
          integration = result.scalar_one_or_none()
          if integration:
              integration.active = False
              await db.commit()

      async def _maybe_refresh_google(
          self, creds: dict, integration: Integration, db
      ) -> dict:
          """Refresh a Google OAuth token if it is expired. Updates DB in-place."""
          from google.oauth2.credentials import Credentials
          from google.auth.transport.requests import Request

          expiry_dt = datetime.fromisoformat(creds["expiry"]) if creds.get("expiry") else None
          creds_obj = Credentials(
              token=creds["access_token"],
              refresh_token=creds.get("refresh_token"),
              token_uri=creds.get("token_uri") or settings.GOOGLE_TOKEN_URI,
              client_id=creds.get("client_id") or settings.GOOGLE_CLIENT_ID,
              client_secret=creds.get("client_secret") or settings.GOOGLE_CLIENT_SECRET,
              expiry=expiry_dt,
          )

          if creds_obj.expired and creds_obj.refresh_token:
              # google.auth.transport.requests.Request is synchronous
              creds_obj.refresh(Request())
              new_creds = {
                  "access_token": creds_obj.token,
                  "refresh_token": creds_obj.refresh_token,
                  "token_uri": creds_obj.token_uri,
                  "client_id": creds_obj.client_id,
                  "client_secret": creds_obj.client_secret,
                  "expiry": creds_obj.expiry.isoformat() if creds_obj.expiry else None,
              }
              integration.encrypted_creds = encrypt_credentials(new_creds)
              await db.commit()
              return new_creds

          return creds
  ```

  **Note on upsert:** The `store` method uses `pg_insert(...).on_conflict_do_update(index_elements=["user_id", "service"], ...)`. This requires a unique constraint on `(user_id, service)`. If one does not exist yet in the DB, a migration step must add it (see Step 1.7).

### Step 1.7 — Add unique constraint on `(user_id, service)` to `integrations`

- [ ] Add `op.create_unique_constraint` to the same migration as Step 1.1 (or create a companion migration). Since the `store` upsert depends on this constraint, it must land in the same migration.

  Add to `upgrade()` in `b9c1d2e3f4a5`:
  ```python
  op.create_unique_constraint(
      'uq_integrations_user_service', 'integrations', ['user_id', 'service']
  )
  ```
  Add to `downgrade()`:
  ```python
  op.drop_constraint('uq_integrations_user_service', 'integrations', type_='unique')
  ```

  The complete migration `upgrade()`:
  ```python
  def upgrade() -> None:
      op.add_column(
          'integrations',
          sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true'))
      )
      op.add_column(
          'integrations',
          sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True)
      )
      op.create_unique_constraint(
          'uq_integrations_user_service', 'integrations', ['user_id', 'service']
      )
  ```

### Step 1.8 — Create `app/connectors/registry.py`

- [ ] Create `app/connectors/registry.py`:

  ```python
  # app/connectors/registry.py
  import importlib
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
                      import logging
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
              except Exception:
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
  ```

### Step 1.9 — Verify migration runs cleanly

- [ ] Run: `cd /Users/john/Desktop/john/projects/botsapp/managed-bot-service && venv/bin/alembic upgrade head`

  Expected output: no errors, migration `b9c1d2e3f4a5` applied.

- [ ] Run: `venv/bin/alembic check`

  Expected: `No new upgrade operations detected.` (model matches DB after migration).

---

## Chunk 2: Built-in Connectors + Community Template

### Step 2.1 — Create `app/connectors/builtin/__init__.py`

- [ ] Create an empty `app/connectors/builtin/__init__.py`.

### Step 2.2 — Delete the stubs

- [ ] Delete `app/connectors/gmail.py`.
- [ ] Delete `app/connectors/gcal.py`.

  These files are referenced in `app/bot/orchestrator.py` (imports on lines 8–9). The orchestrator will be updated in Chunk 3 before any running server would import them, so the delete is safe at this point in the plan. Do not run the server between Step 2.2 and Step 3.1.

### Step 2.3 — Create `app/connectors/builtin/gmail.py`

- [ ] Create `app/connectors/builtin/gmail.py`:

  ```python
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

          return ToolResult(content=None, error=f"Unknown gmail tool: {tool_name}")
  ```

### Step 2.4 — Create `app/connectors/builtin/gcal.py`

- [ ] Create `app/connectors/builtin/gcal.py`:

  ```python
  # app/connectors/builtin/gcal.py
  from datetime import datetime, timedelta, timezone

  from googleapiclient.discovery import build
  from google.oauth2.credentials import Credentials
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
      return build("calendar", "v3", credentials=creds_obj)


  class GCalConnector(BaseConnector):
      name = "gcal"
      display_name = "Google Calendar"
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

          now = datetime.now(timezone.utc)
          day_after_tomorrow = now + timedelta(days=2)

          events_result = service.events().list(
              calendarId="primary",
              timeMin=now.isoformat(),
              timeMax=day_after_tomorrow.isoformat(),
              singleEvents=True,
              orderBy="startTime",
          ).execute()
          events = events_result.get("items", [])

          if not events:
              content = "**Google Calendar:** No events today or tomorrow."
          else:
              lines = ["**Google Calendar — upcoming events:**"]
              for event in events:
                  start = event.get("start", {})
                  start_str = start.get("dateTime") or start.get("date", "")
                  summary = event.get("summary", "(no title)")
                  lines.append(f"- {start_str}: {summary}")
              content = "\n".join(lines)

          return ContextBlock(content=content)

      def get_tools(self) -> list[ToolDefinition]:
          return [
              {
                  "name": "gcal_create_event",
                  "description": "Create a new event on the user's Google Calendar.",
                  "input_schema": {
                      "type": "object",
                      "properties": {
                          "summary": {"type": "string", "description": "Event title"},
                          "start_time": {"type": "string", "description": "ISO 8601 datetime, e.g. 2026-03-21T14:00:00+00:00"},
                          "end_time": {"type": "string", "description": "ISO 8601 datetime"},
                          "description": {"type": "string", "description": "Optional event description"},
                      },
                      "required": ["summary", "start_time", "end_time"],
                  },
              },
              {
                  "name": "gcal_update_event",
                  "description": "Update an existing event on the user's Google Calendar.",
                  "input_schema": {
                      "type": "object",
                      "properties": {
                          "event_id": {"type": "string"},
                          "summary": {"type": "string"},
                          "start_time": {"type": "string"},
                          "end_time": {"type": "string"},
                      },
                      "required": ["event_id"],
                  },
              },
              {
                  "name": "gcal_check_availability",
                  "description": "Check what events are scheduled in a time range.",
                  "input_schema": {
                      "type": "object",
                      "properties": {
                          "time_min": {"type": "string", "description": "ISO 8601 start of range"},
                          "time_max": {"type": "string", "description": "ISO 8601 end of range"},
                      },
                      "required": ["time_min", "time_max"],
                  },
              },
          ]

      async def handle_tool_call(
          self, tool_name: str, args: dict, user_id: str, db
      ) -> ToolResult:
          creds = await self.cred_manager.get(user_id, self.name, db)
          service = _build_service(creds)

          if tool_name == "gcal_create_event":
              body = {
                  "summary": args["summary"],
                  "start": {"dateTime": args["start_time"]},
                  "end": {"dateTime": args["end_time"]},
              }
              if args.get("description"):
                  body["description"] = args["description"]
              result = service.events().insert(calendarId="primary", body=body).execute()
              return ToolResult(content={"status": "created", "event_id": result.get("id")})

          if tool_name == "gcal_update_event":
              event_id = args.pop("event_id")
              existing = service.events().get(calendarId="primary", eventId=event_id).execute()
              if "summary" in args:
                  existing["summary"] = args["summary"]
              if "start_time" in args:
                  existing["start"] = {"dateTime": args["start_time"]}
              if "end_time" in args:
                  existing["end"] = {"dateTime": args["end_time"]}
              result = service.events().update(
                  calendarId="primary", eventId=event_id, body=existing
              ).execute()
              return ToolResult(content={"status": "updated", "event_id": result.get("id")})

          if tool_name == "gcal_check_availability":
              events_result = service.events().list(
                  calendarId="primary",
                  timeMin=args["time_min"],
                  timeMax=args["time_max"],
                  singleEvents=True,
                  orderBy="startTime",
              ).execute()
              events = events_result.get("items", [])
              return ToolResult(content={"events": events, "count": len(events)})

          return ToolResult(content=None, error=f"Unknown gcal tool: {tool_name}")
  ```

### Step 2.5 — Create `app/connectors/builtin/notion.py`

- [ ] Create `app/connectors/builtin/notion.py`:

  ```python
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

          return ToolResult(content=None, error=f"Unknown notion tool: {tool_name}")
  ```

### Step 2.6 — Create `app/connectors/community/__init__.py` and `EXAMPLE.py`

- [ ] Create an empty `app/connectors/community/__init__.py`.

- [ ] Create `app/connectors/community/EXAMPLE.py`:

  ```python
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
              }
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
          return ToolResult(content=None, error=f"Unknown tool: {tool_name}")
  ```

### Step 2.7 — Write tests for the framework core

- [ ] Create `tests/connectors/__init__.py` (empty).

- [ ] Create `tests/connectors/test_credentials.py`:

  ```python
  # tests/connectors/test_credentials.py
  from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
  import pytest

  from app.connectors.base import CredentialsExpiredError
  from app.connectors.credentials import CredentialManager


  async def test_get_raises_when_no_integration():
      """CredentialManager.get raises CredentialsExpiredError if no DB row exists."""
      manager = CredentialManager()
      mock_db = AsyncMock()
      mock_db.execute.return_value.scalar_one_or_none.return_value = None

      with pytest.raises(CredentialsExpiredError):
          await manager.get("user_1", "gmail", mock_db)


  async def test_get_raises_when_inactive():
      """CredentialManager.get raises CredentialsExpiredError if active=False."""
      manager = CredentialManager()
      mock_integration = MagicMock()
      mock_integration.active = False

      mock_db = AsyncMock()
      mock_db.execute.return_value.scalar_one_or_none.return_value = mock_integration

      with pytest.raises(CredentialsExpiredError):
          await manager.get("user_1", "gmail", mock_db)


  async def test_get_returns_decrypted_creds_no_refresh():
      """CredentialManager.get returns decrypted creds dict for a non-Google connector."""
      manager = CredentialManager()

      mock_integration = MagicMock()
      mock_integration.active = True

      # encrypt_credentials / decrypt_credentials need a real key in settings
      # — patch decrypt_credentials directly
      expected_creds = {"access_token": "tok_abc"}
      mock_db = AsyncMock()
      mock_db.execute.return_value.scalar_one_or_none.return_value = mock_integration

      with patch("app.connectors.credentials.decrypt_credentials", return_value=expected_creds):
          result = await manager.get("user_1", "notion", mock_db)

      assert result == expected_creds


  async def test_deactivate_sets_active_false():
      """CredentialManager.deactivate sets active=False and commits."""
      manager = CredentialManager()
      mock_integration = MagicMock()
      mock_integration.active = True

      mock_db = AsyncMock()
      mock_db.execute.return_value.scalar_one_or_none.return_value = mock_integration

      await manager.deactivate("user_1", "gmail", mock_db)

      assert mock_integration.active is False
      mock_db.commit.assert_called_once()
  ```

- [ ] Create `tests/connectors/test_registry.py`:

  ```python
  # tests/connectors/test_registry.py
  from unittest.mock import AsyncMock, MagicMock, patch
  import pytest

  from app.connectors.base import BaseConnector, ContextBlock, ToolResult
  from app.connectors.credentials import CredentialManager
  from app.connectors.registry import ConnectorRegistry


  def _make_connector(name: str, display_name: str, token_budget: int, context_str: str, tools: list):
      """Helper: create a concrete BaseConnector subclass for testing."""
      class TestConnector(BaseConnector):
          pass
      TestConnector.name = name
      TestConnector.display_name = display_name
      TestConnector.token_budget = token_budget
      TestConnector.get_tools = lambda self: tools
      TestConnector.get_context = AsyncMock(return_value=ContextBlock(content=context_str))
      TestConnector.handle_tool_call = AsyncMock(return_value=ToolResult(content={"ok": True}))
      TestConnector.connect = AsyncMock()
      TestConnector.disconnect = AsyncMock()
      return TestConnector


  async def test_get_active_context_respects_token_cap():
      """
      When combined budgets exceed 200 tokens, lowest-priority (last_used_at
      null / oldest) connectors are excluded entirely.
      """
      cred_manager = MagicMock(spec=CredentialManager)
      registry = ConnectorRegistry(cred_manager)

      # Connector A: 150 tokens — fits
      a_content = "A" * (150 * 4)
      ConnA = _make_connector("svc_a", "Svc A", 150, a_content, [])
      # Connector B: 100 tokens — would push total to 250, exceeds cap → excluded
      b_content = "B" * (100 * 4)
      ConnB = _make_connector("svc_b", "Svc B", 100, b_content, [])

      registry._connectors = {
          "svc_a": ConnA(cred_manager),
          "svc_b": ConnB(cred_manager),
      }

      # Mock DB: two active integrations, svc_a has most-recent last_used_at
      from datetime import datetime, timezone
      int_a = MagicMock()
      int_a.service = "svc_a"
      int_a.last_used_at = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)

      int_b = MagicMock()
      int_b.service = "svc_b"
      int_b.last_used_at = None  # older / never used → lower priority

      mock_db = AsyncMock()
      mock_db.execute.return_value.scalars.return_value.all.return_value = [int_a, int_b]

      context = await registry.get_active_context("user_1", mock_db)

      assert a_content in context       # A fits
      assert b_content not in context   # B excluded entirely


  async def test_get_tools_for_user_merges_connectors():
      """get_tools_for_user returns tools from all active connectors."""
      cred_manager = MagicMock(spec=CredentialManager)
      registry = ConnectorRegistry(cred_manager)

      tool_a = {"name": "svc_a_do", "description": "do a", "input_schema": {"type": "object", "properties": {}}}
      tool_b = {"name": "svc_b_do", "description": "do b", "input_schema": {"type": "object", "properties": {}}}

      ConnA = _make_connector("svc_a", "Svc A", 50, "", [tool_a])
      ConnB = _make_connector("svc_b", "Svc B", 50, "", [tool_b])
      registry._connectors = {
          "svc_a": ConnA(cred_manager),
          "svc_b": ConnB(cred_manager),
      }

      int_a = MagicMock(); int_a.service = "svc_a"
      int_b = MagicMock(); int_b.service = "svc_b"
      mock_db = AsyncMock()
      mock_db.execute.return_value.scalars.return_value.all.return_value = [int_a, int_b]

      tools = await registry.get_tools_for_user("user_1", mock_db)
      names = [t["name"] for t in tools]
      assert "svc_a_do" in names
      assert "svc_b_do" in names


  async def test_dispatch_tool_routes_to_correct_connector():
      """dispatch_tool resolves tool_name → connector and calls handle_tool_call."""
      cred_manager = MagicMock(spec=CredentialManager)
      registry = ConnectorRegistry(cred_manager)

      tool = {"name": "svc_a_do", "description": "x", "input_schema": {"type": "object", "properties": {}}}
      ConnA = _make_connector("svc_a", "Svc A", 50, "", [tool])
      instance_a = ConnA(cred_manager)
      registry._connectors = {"svc_a": instance_a}
      registry._tool_map = {"svc_a_do": "svc_a"}

      mock_db = AsyncMock()
      result = await registry.dispatch_tool("svc_a_do", {"x": 1}, "user_1", mock_db)

      instance_a.handle_tool_call.assert_called_once_with("svc_a_do", {"x": 1}, "user_1", mock_db)
      assert result.content == {"ok": True}
      mock_db.commit.assert_called_once()  # last_used_at update
  ```

### Step 2.8 — Write tests for built-in connectors

- [ ] Create `tests/connectors/test_gmail.py`:

  ```python
  # tests/connectors/test_gmail.py
  from unittest.mock import MagicMock, AsyncMock, patch

  from app.connectors.builtin.gmail import GmailConnector
  from app.connectors.credentials import CredentialManager


  def _mock_service():
      """Build a minimal mock of the Gmail service object."""
      svc = MagicMock()
      # getProfile
      svc.users.return_value.getProfile.return_value.execute.return_value = {
          "messagesUnread": 3
      }
      # messages.list
      svc.users.return_value.messages.return_value.list.return_value.execute.return_value = {
          "messages": [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]
      }
      # messages.get (for context — metadata headers)
      svc.users.return_value.messages.return_value.get.return_value.execute.return_value = {
          "payload": {"headers": [{"name": "Subject", "value": "Test subject"}]}
      }
      return svc


  async def test_get_context_returns_unread_count_and_subjects():
      """get_context returns unread count and subject lines."""
      cred_manager = MagicMock(spec=CredentialManager)
      cred_manager.get = AsyncMock(return_value={
          "access_token": "tok", "refresh_token": "ref",
          "client_id": "cid", "client_secret": "cs", "token_uri": "uri"
      })
      connector = GmailConnector(cred_manager)

      mock_svc = _mock_service()
      mock_db = AsyncMock()

      with patch("app.connectors.builtin.gmail._build_service", return_value=mock_svc):
          block = await connector.get_context("user_1", mock_db)

      assert "3 unread" in block.content
      assert "Test subject" in block.content
      assert block.token_count == len(block.content) // 4


  async def test_handle_tool_call_send_email():
      """handle_tool_call sends an email and returns sent status."""
      cred_manager = MagicMock(spec=CredentialManager)
      cred_manager.get = AsyncMock(return_value={
          "access_token": "tok", "refresh_token": "ref",
          "client_id": "cid", "client_secret": "cs", "token_uri": "uri"
      })
      connector = GmailConnector(cred_manager)

      mock_svc = MagicMock()
      mock_svc.users.return_value.messages.return_value.send.return_value.execute.return_value = {
          "id": "sent_123"
      }
      mock_db = AsyncMock()

      with patch("app.connectors.builtin.gmail._build_service", return_value=mock_svc):
          result = await connector.handle_tool_call(
              "gmail_send_email",
              {"to": "bob@example.com", "subject": "Hello", "body": "World"},
              "user_1",
              mock_db,
          )

      assert result.error is None
      assert result.content["status"] == "sent"
  ```

- [ ] Create `tests/connectors/test_gcal.py`:

  ```python
  # tests/connectors/test_gcal.py
  from unittest.mock import MagicMock, AsyncMock, patch

  from app.connectors.builtin.gcal import GCalConnector
  from app.connectors.credentials import CredentialManager


  async def test_get_context_returns_events():
      """get_context lists today/tomorrow events."""
      cred_manager = MagicMock(spec=CredentialManager)
      cred_manager.get = AsyncMock(return_value={
          "access_token": "tok", "refresh_token": "ref",
          "client_id": "cid", "client_secret": "cs", "token_uri": "uri"
      })
      connector = GCalConnector(cred_manager)

      mock_svc = MagicMock()
      mock_svc.events.return_value.list.return_value.execute.return_value = {
          "items": [
              {
                  "summary": "Team standup",
                  "start": {"dateTime": "2026-03-20T09:00:00+00:00"},
              }
          ]
      }
      mock_db = AsyncMock()

      with patch("app.connectors.builtin.gcal._build_service", return_value=mock_svc):
          block = await connector.get_context("user_1", mock_db)

      assert "Team standup" in block.content


  async def test_handle_tool_call_create_event():
      """handle_tool_call creates an event and returns event_id."""
      cred_manager = MagicMock(spec=CredentialManager)
      cred_manager.get = AsyncMock(return_value={
          "access_token": "tok", "refresh_token": "ref",
          "client_id": "cid", "client_secret": "cs", "token_uri": "uri"
      })
      connector = GCalConnector(cred_manager)

      mock_svc = MagicMock()
      mock_svc.events.return_value.insert.return_value.execute.return_value = {"id": "evt_xyz"}
      mock_db = AsyncMock()

      with patch("app.connectors.builtin.gcal._build_service", return_value=mock_svc):
          result = await connector.handle_tool_call(
              "gcal_create_event",
              {
                  "summary": "Doctor appt",
                  "start_time": "2026-03-21T10:00:00+00:00",
                  "end_time": "2026-03-21T11:00:00+00:00",
              },
              "user_1",
              mock_db,
          )

      assert result.error is None
      assert result.content["event_id"] == "evt_xyz"
  ```

- [ ] Create `tests/connectors/test_notion.py`:

  ```python
  # tests/connectors/test_notion.py
  from unittest.mock import AsyncMock, MagicMock, patch
  import pytest
  import httpx

  from app.connectors.builtin.notion import NotionConnector
  from app.connectors.credentials import CredentialManager


  def _mock_search_response(titles: list[str]):
      results = []
      for t in titles:
          results.append({
              "properties": {
                  "title": {
                      "title": [{"plain_text": t}]
                  }
              }
          })
      mock_resp = MagicMock()
      mock_resp.raise_for_status = MagicMock()
      mock_resp.json.return_value = {"results": results}
      return mock_resp


  async def test_get_context_lists_recent_pages():
      """get_context returns the titles of recently edited Notion pages."""
      cred_manager = MagicMock(spec=CredentialManager)
      cred_manager.get = AsyncMock(return_value={"access_token": "tok_notion"})
      connector = NotionConnector(cred_manager)

      mock_db = AsyncMock()
      mock_resp = _mock_search_response(["My Project", "Meeting Notes", "Ideas"])

      with patch("httpx.AsyncClient") as MockClient:
          mock_client_instance = AsyncMock()
          mock_client_instance.__aenter__.return_value = mock_client_instance
          mock_client_instance.__aexit__.return_value = None
          mock_client_instance.post.return_value = mock_resp
          MockClient.return_value = mock_client_instance

          block = await connector.get_context("user_1", mock_db)

      assert "My Project" in block.content
      assert "Meeting Notes" in block.content


  async def test_handle_tool_call_search_pages():
      """notion_search_pages calls the Notion search endpoint and returns results."""
      cred_manager = MagicMock(spec=CredentialManager)
      cred_manager.get = AsyncMock(return_value={"access_token": "tok_notion"})
      connector = NotionConnector(cred_manager)

      mock_db = AsyncMock()
      mock_resp = _mock_search_response(["Result 1"])

      with patch("httpx.AsyncClient") as MockClient:
          mock_client_instance = AsyncMock()
          mock_client_instance.__aenter__.return_value = mock_client_instance
          mock_client_instance.__aexit__.return_value = None
          mock_client_instance.post.return_value = mock_resp
          MockClient.return_value = mock_client_instance

          result = await connector.handle_tool_call(
              "notion_search_pages", {"query": "project"}, "user_1", mock_db
          )

      assert result.error is None
      assert "results" in result.content
  ```

### Step 2.9 — Run Chunk 2 tests

- [ ] Run: `cd /Users/john/Desktop/john/projects/botsapp/managed-bot-service && venv/bin/pytest tests/connectors/ -v`

  Expected output: all tests pass (no real network calls made — all external services are mocked).

---

## Chunk 3: Wire into Assembler + Orchestrator

### Step 3.1 — Update `app/context/assembler.py`

- [ ] Edit `app/context/assembler.py`. In the `assemble()` method, after line 111 where `system_prompt = persona_block + "\n" + base_prompt` is constructed, append the connector context block.

  Replace the current section starting at `# 3. System Prompt Synthesis` with:

  ```python
      # 3. System Prompt Synthesis
      if owner_mode:
          mentions_context = ""
          if mentions:
              mentions_context = "\n\nMentioned contacts:\n" + "\n".join(
                  f"- {m.get('display_name', '')} (phone: {m.get('phone', '')})"
                  for m in mentions
              )
          base_prompt = f"""You are the user's personal AI assistant on Alter. The user (your owner) is giving you instructions directly.

  You can:
  - Answer questions about their messages, activity, and contacts
  - Send messages to their contacts using the send_message_to_contact tool
  - Execute other configured tools (Gmail, Calendar, etc.)

  Long-term user memory:
  {long_term_memory_str if long_term_memory_str else "No preferences learned yet."}
  {mentions_context}"""
      else:
          base_prompt = f"""You are the user's personal assistant bot on Alter.

  Long-term user memory:
  {long_term_memory_str if long_term_memory_str else "No preferences learned yet."}
  """
      system_prompt = persona_block + "\n" + base_prompt

      # 3b. Connector context — injected fresh on every LLM call
      from app.connectors.registry import get_registry
      connector_context = await get_registry().get_active_context(user_id, self.db)
      if connector_context:
          system_prompt += "\n\n" + connector_context
  ```

  The import is placed inline (inside the method) to avoid a circular import at module load time. Alternatively it can be placed at the top of the file — there is no circular dependency here since `registry.py` does not import from `assembler.py`.

### Step 3.2 — Update `app/bot/orchestrator.py`

- [ ] Edit `app/bot/orchestrator.py`. Replace the top-of-file hardcoded tool lists, the old connector imports, and the `handle_tool_call` dispatch block.

  New imports section (replace lines 1–13):
  ```python
  import anthropic
  from typing import Dict, Any, List
  from sqlalchemy.ext.asyncio import AsyncSession

  from app.core.settings import settings
  from app.permissions.engine import PermissionEngine
  from app.connectors.registry import get_registry
  from app.connectors.base import CredentialsExpiredError
  from app.context.working_memory import WorkingMemory
  from app.bot.gemini_adapter import call_gemini
  ```

  Remove the module-level `tools = [...]`, `send_message_tool = {...}`, `owner_tools = tools + [send_message_tool]` variables (lines 14–52). The `send_message_tool` dict should be preserved as a local constant (or inline) since it is not connector-managed.

  New `send_message_tool` (place it just before the `LLMOrchestrator` class definition, replacing the deleted block):
  ```python
  send_message_tool = {
      "name": "send_message_to_contact",
      "description": "Send a message to one of the owner's contacts on their behalf via Alter.",
      "input_schema": {
          "type": "object",
          "properties": {
              "recipient_phone": {"type": "string", "description": "Phone number of the contact to message"},
              "message_text": {"type": "string", "description": "The message text to send to the contact"},
          },
          "required": ["recipient_phone", "message_text"],
      },
  }
  ```

  New `run()` body (replace lines 60–72 of the current `run()` method):
  ```python
  async def run(self, user_id: str, thread_id: str, context: Dict[str, Any], preferred_llm: str = "gemini", owner_mode: bool = False, llm_api_keys: dict = None) -> Dict[str, Any]:
      registry = get_registry()
      connector_tools = await registry.get_tools_for_user(user_id, self.db)
      active_tools_claude = connector_tools + ([send_message_tool] if owner_mode else [])
      # Build Gemini-format tools from the registry tools (convert input_schema -> parameters)
      gemini_connector_tools = [
          {
              "name": t["name"],
              "description": t["description"],
              "parameters": t["input_schema"],
          }
          for t in connector_tools
      ]
      from app.bot.gemini_adapter import gemini_send_message_tool
      active_tools_gemini = gemini_connector_tools + ([gemini_send_message_tool] if owner_mode else [])

      try:
          if preferred_llm == "claude":
              return await self._run_claude(user_id, thread_id, context, active_tools_claude, llm_api_keys=llm_api_keys)
          else:
              return await self._run_gemini(user_id, thread_id, context, active_tools_gemini, llm_api_keys=llm_api_keys)
      except Exception as e:
          return {"action": "reply", "text": f"I encountered an error: {str(e)}"}
  ```

  New `handle_tool_call()` (replace lines 122–171):
  ```python
  async def handle_tool_call(self, user_id: str, thread_id: str, tool_name: str, args: Dict[str, Any]):
      if tool_name == "send_message_to_contact":
          recipient = args.get("recipient_phone", "")
          text = args.get("message_text", "")
          confirmation = f"Message sent to {recipient}: \"{text}\""
          await self.working_memory.append_event(user_id, thread_id, {"role": "assistant", "content": confirmation})
          return {
              "action": "send_to_contact",
              "recipient_phone": recipient,
              "text": text,
              "confirmation": confirmation,
          }

      # Connector tool — check permissions first
      parts = tool_name.split("_", 1)
      service = parts[0] if len(parts) > 1 else tool_name
      action = parts[1] if len(parts) > 1 else tool_name

      level = await self.permission_engine.check_permission(user_id, service, action)
      if level == "denied" or (level == "read_only" and "create" in action):
          msg = f"I am not authorized to perform {action} on {service}."
          await self.working_memory.append_event(user_id, thread_id, {"role": "assistant", "content": msg})
          return {"action": "reply", "text": msg}

      if level == "ask_first":
          msg = f"I need your permission to {action}. Please approve this request in your control panel."
          return {"action": "pending_approval", "text": msg, "tool": tool_name, "args": args}

      # Execute via registry
      registry = get_registry()
      try:
          result_obj = await registry.dispatch_tool(tool_name, args, user_id, self.db)
      except CredentialsExpiredError as exc:
          msg = f"Your {service} connection has expired. Please reconnect it in your settings."
          await self.working_memory.append_event(user_id, thread_id, {"role": "assistant", "content": msg})
          return {"action": "reply", "text": msg}

      result = result_obj.content if result_obj.error is None else {"error": result_obj.error}
      await self.working_memory.append_event(
          user_id,
          thread_id,
          {"role": "user", "content": f"Tool {tool_name} returned: {result}"},
      )
      return {"action": "tool_executed", "result": result}
  ```

  **Note on `gemini_send_message_tool`:** The `gemini_adapter.py` currently has the send message tool embedded in `gemini_owner_tools`. Extract it as a named export so the orchestrator can reference it. Add this to `app/bot/gemini_adapter.py`:
  ```python
  gemini_send_message_tool = {
      "name": "send_message_to_contact",
      "description": "Send a message to one of the owner's contacts on their behalf via Alter.",
      "parameters": {
          "type": "object",
          "properties": {
              "recipient_phone": {"type": "string"},
              "message_text": {"type": "string"},
          },
          "required": ["recipient_phone", "message_text"],
      },
  }
  ```
  And simplify `gemini_owner_tools = [gemini_send_message_tool]` (the connector tools now come from the registry at runtime).

### Step 3.3 — Write integration tests for assembler + orchestrator

- [ ] Create `tests/connectors/test_assembler_connectors.py`:

  ```python
  # tests/connectors/test_assembler_connectors.py
  from unittest.mock import AsyncMock, MagicMock, patch


  async def test_system_prompt_includes_connector_context():
      """Connector context block appears in assembled system prompt."""
      mock_db = AsyncMock()

      mock_registry = MagicMock()
      mock_registry.get_active_context = AsyncMock(
          return_value="## Connected Services\n**Gmail:** 2 unread message(s)"
      )

      with patch("app.context.assembler.fetch_bot_instructions", new_callable=AsyncMock, return_value=[]):
          with patch("app.context.assembler.fetch_style_profile", new_callable=AsyncMock, return_value=None):
              with patch("app.context.assembler.get_registry", return_value=mock_registry):
                  from app.context.assembler import ContextAssembler
                  from app.context.thread_fetcher import AlterThreadFetcher
                  from app.context.working_memory import WorkingMemory

                  with patch.object(AlterThreadFetcher, "fetch_thread_history", new_callable=AsyncMock, return_value=[]):
                      with patch.object(WorkingMemory, "get_state", new_callable=AsyncMock, return_value=[]):
                          assembler = ContextAssembler(mock_db)
                          result = await assembler.assemble(
                              user_id="user_1",
                              thread_id="thread_1",
                              incoming_message={"role": "user", "content": "hi"},
                          )

      assert "## Connected Services" in result["system_prompt"]
      assert "Gmail: 2 unread" in result["system_prompt"]


  async def test_system_prompt_omits_connector_context_when_empty():
      """When no connectors are active, system prompt has no Connected Services block."""
      mock_db = AsyncMock()
      mock_registry = MagicMock()
      mock_registry.get_active_context = AsyncMock(return_value="")

      with patch("app.context.assembler.fetch_bot_instructions", new_callable=AsyncMock, return_value=[]):
          with patch("app.context.assembler.fetch_style_profile", new_callable=AsyncMock, return_value=None):
              with patch("app.context.assembler.get_registry", return_value=mock_registry):
                  from app.context.assembler import ContextAssembler
                  from app.context.thread_fetcher import AlterThreadFetcher
                  from app.context.working_memory import WorkingMemory

                  with patch.object(AlterThreadFetcher, "fetch_thread_history", new_callable=AsyncMock, return_value=[]):
                      with patch.object(WorkingMemory, "get_state", new_callable=AsyncMock, return_value=[]):
                          assembler = ContextAssembler(mock_db)
                          result = await assembler.assemble(
                              user_id="user_1",
                              thread_id="thread_1",
                              incoming_message={"role": "user", "content": "hi"},
                          )

      assert "## Connected Services" not in result["system_prompt"]
  ```

- [ ] Create `tests/connectors/test_orchestrator_registry.py`:

  ```python
  # tests/connectors/test_orchestrator_registry.py
  from unittest.mock import AsyncMock, MagicMock, patch

  from app.connectors.base import ToolResult


  async def test_orchestrator_uses_registry_tools():
      """LLMOrchestrator.run fetches tools from the registry, not hardcoded lists."""
      mock_db = AsyncMock()
      mock_registry = MagicMock()
      registry_tool = {
          "name": "gmail_send_email",
          "description": "Send email",
          "input_schema": {"type": "object", "properties": {}},
      }
      mock_registry.get_tools_for_user = AsyncMock(return_value=[registry_tool])

      context = {
          "system_prompt": "You are a bot.",
          "messages": [{"role": "user", "content": "test"}],
      }

      with patch("app.bot.orchestrator.get_registry", return_value=mock_registry):
          with patch("app.bot.orchestrator.anthropic") as mock_anthropic:
              mock_client = AsyncMock()
              mock_response = MagicMock()
              mock_response.content = [MagicMock(type="text", text="Hello")]
              mock_client.messages.create = AsyncMock(return_value=mock_response)
              mock_anthropic.AsyncAnthropic.return_value = mock_client

              from app.bot.orchestrator import LLMOrchestrator
              from app.context.working_memory import WorkingMemory
              with patch.object(WorkingMemory, "append_event", new_callable=AsyncMock):
                  orch = LLMOrchestrator(mock_db)
                  await orch.run(
                      user_id="user_1",
                      thread_id="thread_1",
                      context=context,
                      preferred_llm="claude",
                      llm_api_keys={"claude": "test_key"},
                  )

      # Registry was consulted for tools
      mock_registry.get_tools_for_user.assert_called_once_with("user_1", mock_db)


  async def test_handle_tool_call_dispatches_to_registry():
      """handle_tool_call routes non-send_message tools to registry.dispatch_tool."""
      mock_db = AsyncMock()
      mock_registry = MagicMock()
      mock_registry.dispatch_tool = AsyncMock(return_value=ToolResult(content={"result": "ok"}))

      mock_permission_engine = MagicMock()
      mock_permission_engine.check_permission = AsyncMock(return_value="full_auto")

      with patch("app.bot.orchestrator.get_registry", return_value=mock_registry):
          from app.bot.orchestrator import LLMOrchestrator
          from app.permissions.engine import PermissionEngine
          from app.context.working_memory import WorkingMemory

          with patch.object(PermissionEngine, "check_permission", new_callable=AsyncMock, return_value="full_auto"):
              with patch.object(WorkingMemory, "append_event", new_callable=AsyncMock):
                  orch = LLMOrchestrator(mock_db)
                  result = await orch.handle_tool_call(
                      "user_1", "thread_1", "gmail_send_email", {"to": "x", "subject": "y", "body": "z"}
                  )

      mock_registry.dispatch_tool.assert_called_once()
      assert result["action"] == "tool_executed"
  ```

### Step 3.4 — Run full test suite

- [ ] Run: `cd /Users/john/Desktop/john/projects/botsapp/managed-bot-service && venv/bin/pytest tests/ -v`

  Expected output: all existing tests (triage, persona) still pass, plus all new connector tests pass. Zero failures.

### Step 3.5 — Manual smoke test (community connector auto-discovery)

- [ ] Verify `EXAMPLE.py` is discovered without error by starting Python in the venv and importing the registry:

  ```
  cd /Users/john/Desktop/john/projects/botsapp/managed-bot-service
  venv/bin/python -c "
  from unittest.mock import patch, MagicMock
  with patch('app.core.settings.Settings', MagicMock()):
      from app.connectors.registry import ConnectorRegistry
      from app.connectors.credentials import CredentialManager
      r = ConnectorRegistry(CredentialManager())
      r.discover()
      print('Discovered connectors:', list(r._connectors.keys()))
      print('Tool map:', list(r._tool_map.keys()))
  "
  ```

  Expected output (names of connectors in builtin + EXAMPLE):
  ```
  Discovered connectors: ['gmail', 'gcal', 'notion', 'example']
  Tool map: ['gmail_read_email', 'gmail_send_email', 'gmail_search_emails', 'gcal_create_event', 'gcal_update_event', 'gcal_check_availability', 'notion_search_pages', 'notion_read_page', 'notion_create_page', 'example_do_thing']
  ```

---

## Summary of Changes

| File | Action |
|------|--------|
| `alembic/versions/b9c1d2e3f4a5_add_integration_active_last_used.py` | New migration |
| `app/models/integration.py` | Add `active`, `last_used_at` columns |
| `app/core/settings.py` | Add 5 OAuth settings |
| `app/connectors/__init__.py` | New (empty) |
| `app/connectors/base.py` | New — ABC + supporting types |
| `app/connectors/credentials.py` | New — CredentialManager |
| `app/connectors/registry.py` | New — singleton ConnectorRegistry |
| `app/connectors/builtin/__init__.py` | New (empty) |
| `app/connectors/builtin/gmail.py` | New — real Gmail connector |
| `app/connectors/builtin/gcal.py` | New — real GCal connector |
| `app/connectors/builtin/notion.py` | New — real Notion connector |
| `app/connectors/community/__init__.py` | New (empty) |
| `app/connectors/community/EXAMPLE.py` | New — community template |
| `app/connectors/gmail.py` | DELETED |
| `app/connectors/gcal.py` | DELETED |
| `app/context/assembler.py` | Append connector context to system prompt |
| `app/bot/orchestrator.py` | Replace hardcoded tools + direct calls with registry |
| `app/bot/gemini_adapter.py` | Extract `gemini_send_message_tool` as named export |
| `tests/connectors/__init__.py` | New (empty) |
| `tests/connectors/test_credentials.py` | New |
| `tests/connectors/test_registry.py` | New |
| `tests/connectors/test_gmail.py` | New |
| `tests/connectors/test_gcal.py` | New |
| `tests/connectors/test_notion.py` | New |
| `tests/connectors/test_assembler_connectors.py` | New |
| `tests/connectors/test_orchestrator_registry.py` | New |
```
