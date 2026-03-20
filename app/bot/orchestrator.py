import anthropic
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.permissions.engine import PermissionEngine
from app.connectors.registry import get_registry
from app.connectors.base import CredentialsExpiredError
from app.context.working_memory import WorkingMemory
from app.bot.gemini_adapter import call_gemini, gemini_send_message_tool


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

class LLMOrchestrator:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.permission_engine = PermissionEngine(db)
        self.working_memory = WorkingMemory()

    async def run(self, user_id: str, thread_id: str, context: Dict[str, Any], preferred_llm: str = "gemini", owner_mode: bool = False, llm_api_keys: dict = None) -> Dict[str, Any]:
        """
        Takes the assembled context, calls the preferred LLM, and handles the resulting actions.
        """
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
        active_tools_gemini = gemini_connector_tools + ([gemini_send_message_tool] if owner_mode else [])

        try:
            if preferred_llm == "claude":
                return await self._run_claude(user_id, thread_id, context, active_tools_claude, llm_api_keys=llm_api_keys)
            else:  # gemini OR unset → Gemini
                return await self._run_gemini(user_id, thread_id, context, active_tools_gemini, llm_api_keys=llm_api_keys)
        except Exception as e:
            return {"action": "reply", "text": f"I encountered an error: {str(e)}"}

    async def _run_claude(self, user_id: str, thread_id: str, context: Dict[str, Any], active_tools: list = None, llm_api_keys: dict = None) -> Dict[str, Any]:
        if active_tools is None:
            active_tools = []
        raw_key = (llm_api_keys or {}).get("claude") or settings.ANTHROPIC_API_KEY
        if not raw_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured")
        claude_client = anthropic.AsyncAnthropic(api_key=raw_key)
        # 1. Call Claude with context and tools
        response = await claude_client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            system=context["system_prompt"],
            messages=context["messages"],
            tools=active_tools
        )

        # 2. Check if Claude wants to use a tool
        for block in response.content:
            if block.type == "tool_use":
                return await self.handle_tool_call(user_id, thread_id, block.name, block.input)

        # 3. If no tool, just a text response
        text_blocks = [b.text for b in response.content if b.type == "text"]
        reply_text = "\n".join(text_blocks)
        
        # Save to working memory
        await self.working_memory.append_event(user_id, thread_id, {"role": "assistant", "content": reply_text})
        
        return {"action": "reply", "text": reply_text}

    async def _run_gemini(self, user_id: str, thread_id: str, context: Dict[str, Any], active_tools: list = None, llm_api_keys: dict = None) -> Dict[str, Any]:
        if active_tools is None:
            active_tools = []
        api_key = (llm_api_keys or {}).get("gemini") or settings.GEMINI_API_KEY
        result = await call_gemini(
            api_key=api_key,
            system_prompt=context["system_prompt"],
            messages=context["messages"],
            tools=active_tools
        )
        
        if result["type"] == "tool_call":
            return await self.handle_tool_call(user_id, thread_id, result["name"], result["args"])
        else:
            reply_text = result["content"]
            await self.working_memory.append_event(user_id, thread_id, {"role": "assistant", "content": reply_text})
            return {"action": "reply", "text": reply_text}

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
        except CredentialsExpiredError:
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
