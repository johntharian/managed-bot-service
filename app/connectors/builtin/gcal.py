# app/connectors/builtin/gcal.py
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from app.core.settings import settings

from app.connectors.base import BaseConnector, ContextBlock, ToolDefinition, ToolResult
from app.connectors.credentials import CredentialManager


def _has_tz(dt_str: str) -> bool:
    return dt_str.endswith("Z") or "+" in dt_str[10:] or (dt_str.count("-") > 2)


def _dt_field(dt_str: str) -> dict:
    """Return a Google Calendar dateTime field, adding timeZone=UTC for naive datetimes."""
    if _has_tz(dt_str):
        return {"dateTime": dt_str}
    return {"dateTime": dt_str, "timeZone": "UTC"}


def _dt_param(dt_str: str) -> str:
    """Return a timezone-aware datetime string for use as a query param (timeMin/timeMax)."""
    if _has_tz(dt_str):
        return dt_str
    return dt_str + "+00:00"


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
            {
                "name": "gcal_get_upcoming_events",
                "description": "Get the user's upcoming Google Calendar events for today and tomorrow. Call this when the user asks about their schedule, availability, or before creating or modifying events.",
                "input_schema": {"type": "object", "properties": {}},
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
                "start": _dt_field(args["start_time"]),
                "end": _dt_field(args["end_time"]),
            }
            if args.get("description"):
                body["description"] = args["description"]
            result = service.events().insert(calendarId="primary", body=body).execute()
            return ToolResult(content={"status": "created", "event_id": result.get("id")})

        if tool_name == "gcal_update_event":
            event_id = args["event_id"]
            existing = service.events().get(calendarId="primary", eventId=event_id).execute()
            if "summary" in args:
                existing["summary"] = args["summary"]
            if "start_time" in args:
                existing["start"] = _dt_field(args["start_time"])
            if "end_time" in args:
                existing["end"] = _dt_field(args["end_time"])
            result = service.events().update(
                calendarId="primary", eventId=event_id, body=existing
            ).execute()
            return ToolResult(content={"status": "updated", "event_id": result.get("id")})

        if tool_name == "gcal_check_availability":
            events_result = service.events().list(
                calendarId="primary",
                timeMin=_dt_param(args["time_min"]),
                timeMax=_dt_param(args["time_max"]),
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            events = events_result.get("items", [])
            return ToolResult(content={"events": events, "count": len(events)})

        if tool_name == "gcal_get_upcoming_events":
            block = await self.get_context(user_id, db)
            return ToolResult(content={"events": block.content})

        return ToolResult(content=None, error=f"Unknown gcal tool: {tool_name}")
