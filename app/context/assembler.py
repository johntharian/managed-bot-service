from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import uuid

from app.context.thread_fetcher import BotsAppThreadFetcher
from app.context.working_memory import WorkingMemory
from app.context.long_term_memory import LongTermMemory
from app.models.bot_instruction import BotInstruction
from app.models.user import User

class ContextAssembler:
    """
    Assembles the complete state context representation of a conversation 
    for feeding into the Claude LLM prompts.
    """
    def __init__(self, db: AsyncSession):
        self.db = db
        self.thread_fetcher = BotsAppThreadFetcher()
        self.working_memory = WorkingMemory()
        self.long_term_memory = LongTermMemory(self.db)

    async def assemble(self, user_id: str, thread_id: str, incoming_message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Gathers L1 (Recent thread window), L2 (Transient state), L3 (Long term memory),
        as well as explicit user bot instructions.
        """
        # 1. Main Bot instructions
        stmt = select(BotInstruction.instruction_text).where(BotInstruction.user_id == uuid.UUID(user_id))
        instructions = (await self.db.execute(stmt)).scalars().all()
        bot_instructions = "\n".join(instructions)

        # 2. Long Term Memory (L3)
        user_memory = await self.long_term_memory.get_all_for_user(user_id)
        long_term_memory_str = "\n".join([f"{k}: {v}" for k, v in user_memory.items()])

        # 3. System Prompt Synthesis
        system_prompt = f"""You are the user's personal assistant bot on BotsApp.

Long-term user memory:
{long_term_memory_str if long_term_memory_str else "No preferences learned yet."}

User instructions:
{bot_instructions if bot_instructions else "Assist the user appropriately."}
"""

        # 4. Recent Thread History (L1)
        recent_thread_history = await self.thread_fetcher.fetch_recent_messages(thread_id)

        # 5. Working Memory (L2)
        working_memory_turns = await self.working_memory.get_state(user_id, thread_id)

        # Return bundle
        return {
            "system_prompt": system_prompt,
            "messages": [
                *recent_thread_history,
                *working_memory_turns,
                {"role": "user", "content": incoming_message}
            ]
        }
