import anthropic
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from app.core.settings import settings
from app.permissions.engine import PermissionEngine
from app.connectors.gmail import GmailConnector
from app.connectors.gcal import GCalConnector
from app.context.working_memory import WorkingMemory
from app.bot.gemini_adapter import call_gemini, gemini_tools

# In a real app, Anthropic AsyncClient should be instantiated once globally
claude_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

tools = [
    {
        "name": "gmail_read_inbox",
        "description": "Read the recent emails from the user's Gmail inbox.",
        "input_schema": {
            "type": "object",
            "properties": {"max_results": {"type": "integer"}},
            "required": []
        }
    },
    {
        "name": "gcal_create_event",
        "description": "Create a new event on the user's Google Calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "start_time": {"type": "string"},
                "end_time": {"type": "string"}
            },
            "required": ["summary", "start_time", "end_time"]
        }
    }
]

class LLMOrchestrator:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.permission_engine = PermissionEngine(db)
        self.working_memory = WorkingMemory()

    async def run(self, user_id: str, thread_id: str, context: Dict[str, Any], preferred_llm: str = "gemini") -> Dict[str, Any]:
        """
        Takes the assembled context, calls the preferred LLM, and handles the resulting actions.
        """
        try:
            if preferred_llm == "gemini":
                return await self._run_gemini(user_id, thread_id, context)
            elif preferred_llm == "claude" or not preferred_llm:
                return await self._run_claude(user_id, thread_id, context)
            else:
                return {"action": "reply", "text": f"I encountered an error: The requested LLM provider '{preferred_llm}' is not currently supported or installed."}
        except Exception as e:
            return {"action": "reply", "text": f"I encountered an error: {str(e)}"}

    async def _run_claude(self, user_id: str, thread_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        # 1. Call Claude with context and tools
        response = await claude_client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            system=context["system_prompt"],
            messages=context["messages"],
            tools=tools
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

    async def _run_gemini(self, user_id: str, thread_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        result = await call_gemini(
            api_key=settings.GEMINI_API_KEY,
            system_prompt=context["system_prompt"],
            messages=context["messages"],
            tools=gemini_tools
        )
        
        if result["type"] == "tool_call":
            return await self.handle_tool_call(user_id, thread_id, result["name"], result["args"])
        else:
            reply_text = result["content"]
            await self.working_memory.append_event(user_id, thread_id, {"role": "assistant", "content": reply_text})
            return {"action": "reply", "text": reply_text}

    async def handle_tool_call(self, user_id: str, thread_id: str, tool_name: str, args: Dict[str, Any]):
        service, action = tool_name.split("_", 1)
        
        # 1. Check permissions
        level = await self.permission_engine.check_permission(user_id, service, action)
        
        if level == "denied" or level == "read_only" and "create" in action:
            msg = f"I am not authorized to perform {action} on {service}."
            await self.working_memory.append_event(user_id, thread_id, {"role": "assistant", "content": msg})
            return {"action": "reply", "text": msg}
            
        if level == "ask_first":
            # This handles Phase 6 Approval flow. For now, mock it.
            msg = f"I need your permission to {action}. Please approve this request in your control panel."
            return {"action": "pending_approval", "text": msg, "tool": tool_name, "args": args}
            
        # 2. Execute tool if level == 'full_auto' (or read action dropping through)
        # Mock credentials fetching for now
        creds = {}
        
        result = {}
        if service == "gmail":
            connector = GmailConnector(creds)
            if action == "read_inbox":
                result = await connector.read_inbox()
        elif service == "gcal":
            connector = GCalConnector(creds)
            if action == "create_event":
                result = await connector.create_event(**args)
                
        # Append tool result to memory for next turn
        await self.working_memory.append_event(
            user_id, 
            thread_id, 
            {"role": "user", "content": f"Tool {tool_name} returned: {result}"}
        )
        
        return {"action": "tool_executed", "result": result}
