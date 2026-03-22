import json
import anthropic
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.core.logger import logger
from app.permissions.engine import PermissionEngine
from app.connectors.registry import get_registry
from app.connectors.base import CredentialsExpiredError
from app.context.working_memory import WorkingMemory
from app.bot.gemini_adapter import call_gemini, gemini_send_message_tool


MAX_LOOP_ITERATIONS = 10
MAX_TOOL_RESULT_CHARS = 2000

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
        gemini_connector_tools = [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            }
            for t in connector_tools
        ]
        active_tools_gemini = gemini_connector_tools + ([gemini_send_message_tool] if owner_mode else [])

        # Debug: log which tools are being presented to the LLM
        tool_names = [t["name"] for t in (active_tools_claude if preferred_llm == "claude" else active_tools_gemini)]
        logger.info("active_tools", user_id=user_id, llm=preferred_llm, count=len(tool_names), tools=tool_names)

        try:
            if preferred_llm == "claude":
                return await self._run_claude(user_id, thread_id, context, active_tools_claude, llm_api_keys=llm_api_keys)
            else:  # gemini OR unset → Gemini
                return await self._run_gemini(user_id, thread_id, context, active_tools_gemini, llm_api_keys=llm_api_keys)
        except Exception as e:
            err_str = str(e)
            logger.error("orchestrator_error", user_id=user_id, error=err_str)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower() or ("rate" in err_str.lower() and "limit" in err_str.lower()):
                return {"action": "reply", "text": "The AI model has hit its quota limit. Please check your API billing or try again later."}
            return {"action": "reply", "text": "Something went wrong on my end. Please try again."}

    async def _run_agentic_loop(
        self,
        user_id: str,
        thread_id: str,
        context: Dict[str, Any],
        call_llm,          # async (messages, tools) -> {"type": "tool_call"|"text", ...}
        append_tool_turn,  # (messages, name, args, result_str, call_id) -> messages
        active_tools: list,
    ) -> Dict[str, Any]:
        """
        Shared agentic loop. Runs until:
          - LLM produces a text reply (normal exit)
          - handle_tool_call returns a non-connector action (send_message, permission denied, etc.)
          - A duplicate tool+args fingerprint is detected (stuck loop guard)
          - MAX_LOOP_ITERATIONS is reached (runaway guard)
        On loop exhaustion, a final LLM call with tools=[] forces a text reply.
        """
        messages = list(context["messages"])
        seen_calls: set = set()

        for iteration in range(MAX_LOOP_ITERATIONS):
            llm_response = await call_llm(messages, active_tools)

            if llm_response["type"] == "text":
                reply_text = llm_response.get("content") or ""
                logger.info("agentic_loop_complete", user_id=user_id, iterations=iteration + 1)
                if not reply_text:
                    reply_text = "Done."
                await self.working_memory.append_event(
                    user_id, thread_id, {"role": "assistant", "content": reply_text}
                )
                return {"action": "reply", "text": reply_text}

            # --- Tool call path ---
            tool_name = llm_response["name"]
            tool_args = llm_response["args"]
            call_id = llm_response.get("id") or f"call_{iteration}"

            # Guard: identical tool+args seen before → stuck loop
            fingerprint = (tool_name, json.dumps(tool_args, sort_keys=True))
            if fingerprint in seen_calls:
                logger.warning("agentic_loop_duplicate_detected", tool=tool_name, iteration=iteration)
                break
            seen_calls.add(fingerprint)

            logger.info("agentic_loop_tool_call", tool=tool_name, args=tool_args, iteration=iteration)

            tool_result = await self.handle_tool_call(user_id, thread_id, tool_name, tool_args)

            # Non-connector results exit immediately (send_message, permission denied, expired creds)
            if tool_result["action"] != "tool_executed":
                return tool_result

            # Truncate to prevent unbounded context growth
            result_str = json.dumps(tool_result["result"])
            if len(result_str) > MAX_TOOL_RESULT_CHARS:
                result_str = result_str[:MAX_TOOL_RESULT_CHARS] + "... [truncated]"
                logger.info("agentic_loop_result_truncated", tool=tool_name)

            messages = append_tool_turn(messages, tool_name, tool_args, result_str, call_id)

        # Loop exhausted or duplicate detected — force a text reply with no tools
        logger.warning("agentic_loop_forced_reply", user_id=user_id, thread_id=thread_id)
        final_response = await call_llm(messages, [])
        reply_text = (final_response.get("content") or "").strip()
        if not reply_text:
            reply_text = "I've gathered the information but had trouble summarizing it."
        await self.working_memory.append_event(
            user_id, thread_id, {"role": "assistant", "content": reply_text}
        )
        return {"action": "reply", "text": reply_text}

    async def _run_claude(self, user_id: str, thread_id: str, context: Dict[str, Any], active_tools: list = None, llm_api_keys: dict = None) -> Dict[str, Any]:
        if active_tools is None:
            active_tools = []
        raw_key = (llm_api_keys or {}).get("claude") or settings.ANTHROPIC_API_KEY
        if not raw_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured")
        claude_client = anthropic.AsyncAnthropic(api_key=raw_key)

        async def call_llm(messages, tools):
            response = await claude_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1024,
                system=context["system_prompt"],
                messages=messages,
                tools=tools if tools else [],
            )
            for block in response.content:
                if block.type == "tool_use":
                    return {"type": "tool_call", "name": block.name, "args": block.input, "id": block.id}
            text_blocks = [b.text for b in response.content if b.type == "text"]
            return {"type": "text", "content": "\n".join(text_blocks)}

        def append_tool_turn(messages, tool_name, tool_args, result_str, call_id):
            # Claude requires matched tool_use (assistant) + tool_result (user) content blocks
            return messages + [
                {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": call_id, "name": tool_name, "input": tool_args}],
                },
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": call_id, "content": result_str}],
                },
            ]

        return await self._run_agentic_loop(
            user_id, thread_id, context, call_llm, append_tool_turn, active_tools
        )

    async def _run_gemini(self, user_id: str, thread_id: str, context: Dict[str, Any], active_tools: list = None, llm_api_keys: dict = None) -> Dict[str, Any]:
        if active_tools is None:
            active_tools = []
        api_key = (llm_api_keys or {}).get("gemini") or settings.GEMINI_API_KEY

        async def call_llm(messages, tools):
            result = await call_gemini(
                api_key=api_key,
                system_prompt=context["system_prompt"],
                messages=messages,
                tools=tools,
            )
            if result["type"] == "tool_call":
                return {"type": "tool_call", "name": result["name"], "args": result["args"], "id": "gemini_call"}
            return {"type": "text", "content": result.get("content", "")}

        def append_tool_turn(messages, tool_name, tool_args, result_str, call_id):
            # Gemini uses plain text turns — alternating assistant ack + user result
            return messages + [
                {"role": "assistant", "content": f"[Called tool: {tool_name}]"},
                {"role": "user", "content": f"Tool result: {result_str}"},
            ]

        return await self._run_agentic_loop(
            user_id, thread_id, context, call_llm, append_tool_turn, active_tools
        )

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

        # Execute via registry
        registry = get_registry()
        try:
            result_obj = await registry.dispatch_tool(tool_name, args, user_id, self.db)
        except CredentialsExpiredError:
            msg = f"Your {service} connection has expired. Please reconnect it in your settings."
            await self.working_memory.append_event(user_id, thread_id, {"role": "assistant", "content": msg})
            return {"action": "reply", "text": msg}

        result = result_obj.content if result_obj.error is None else {"error": result_obj.error}
        return {"action": "tool_executed", "result": result}
