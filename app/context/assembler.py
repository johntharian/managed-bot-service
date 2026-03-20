from typing import Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.context.thread_fetcher import AlterThreadFetcher
from app.context.working_memory import WorkingMemory
from app.context.long_term_memory import LongTermMemory
from app.models.bot_instruction import BotInstruction
from app.models.style_profile import StyleProfile
from app.models.user import User

_CATEGORY_LABELS = {
    "communication_style": "Communication style",
    "relationships": "Key relationships",
    "role_context": "Role & context",
    "response_preferences": "Response preferences",
    "general": "Additional context",
}


async def fetch_bot_instructions(user_id: str, db) -> list:
    """Fetch all bot instructions for a user."""
    result = await db.execute(
        select(BotInstruction).where(BotInstruction.user_id == user_id)
    )
    return result.scalars().all()


async def fetch_style_profile(user_id: str, db):
    """Fetch the style profile for a user, or None if not yet built."""
    result = await db.execute(
        select(StyleProfile).where(StyleProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


class ContextAssembler:
    """
    Assembles the complete state context representation of a conversation 
    for feeding into the Claude LLM prompts.
    """
    def __init__(self, db: AsyncSession):
        self.db = db
        self.thread_fetcher = AlterThreadFetcher()
        self.working_memory = WorkingMemory()
        self.long_term_memory = LongTermMemory(self.db)

    async def _build_system_prompt(self, user_id: str, owner_mode: bool, db) -> str:
        """Build the system prompt with categorised persona and optional style directive."""
        instructions = await fetch_bot_instructions(user_id, db)
        categories: dict = {k: [] for k in _CATEGORY_LABELS}
        for instr in instructions:
            cat = instr.category or "general"
            categories.get(cat, categories["general"]).append(instr.instruction_text)

        persona_block = "## About the person you represent\n"
        for cat, items in categories.items():
            if items:
                persona_block += f"\n**{_CATEGORY_LABELS[cat]}:**\n"
                persona_block += "\n".join(f"- {item}" for item in items) + "\n"

        # Style learning directive (omit if no profile yet — cold-start)
        style_profile = await fetch_style_profile(user_id, db)
        if style_profile and style_profile.profile.get("directive"):
            persona_block += f"\n**Style:** {style_profile.profile['directive']}\n"

        return persona_block

    async def assemble(
        self,
        user_id: str,
        thread_id: str,
        incoming_message: Dict[str, Any],
        owner_mode: bool = False,
        mentions: list = None,
    ) -> Dict[str, Any]:
        """
        Gathers L1 (Recent thread window), L2 (Transient state), L3 (Long term memory),
        as well as explicit user bot instructions.
        """
        # 1. Persona block (categorised instructions + style directive)
        persona_block = await self._build_system_prompt(user_id, owner_mode, db=self.db)

        # 2. Long Term Memory (L3)
        user_memory = await self.long_term_memory.get_all_for_user(user_id)
        long_term_memory_str = "\n".join([f"{k}: {v}" for k, v in user_memory.items()])

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

        # 4. Recent Thread History (L1)
        recent_thread_history = await self.thread_fetcher.fetch_thread_history(thread_id, user_id)

        # Normalize L1 history: add 'role' field based on sender direction
        normalized_history = [
            {
                "role": "assistant" if str(m.get("sender_id")) == str(user_id) else "user",
                "content": m.get("content", ""),
            }
            for m in recent_thread_history
        ]

        # 5. Working Memory (L2)
        working_memory_turns = await self.working_memory.get_state(user_id, thread_id)

        # Return bundle
        return {
            "system_prompt": system_prompt,
            "messages": [
                *normalized_history,
                *working_memory_turns,
                {"role": "user", "content": incoming_message}
            ]
        }
