import json
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.core.logger import logger
from app.core.security import verify_hmac_signature, decrypt_credentials
from app.models.user import User
from app.schemas.bot import MessageEnvelope
from app.context.assembler import ContextAssembler
from app.bot.orchestrator import LLMOrchestrator
from app.bot.responder import AlterResponder
from app.approvals.manager import ApprovalManager

router = APIRouter()

@router.post("/{user_id}")
async def handle_bot_webhook(
    user_id: str,
    request: Request,
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
    db: AsyncSession = Depends(get_db)
):
    """
    Main webhook entrypoint for Alter.
    Validates HMAC-SHA256 signature and hands off to the Context/Orchestrator.
    """
    # 1. Fetch user to get their secret key
    stmt = select(User).where(User.user_id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="Bot not found")

    # 2. Verify X-Hub-Signature-256
    body = await request.body()
    if not verify_hmac_signature(body, x_hub_signature_256, user.secret_key):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    # 3. Parse message envelope (format sent by alter-server deliverer)
    try:
        message = MessageEnvelope(**json.loads(body.decode("utf-8")))
    except Exception as e:
        logger.error("Failed to parse message envelope", user_id=user_id, error=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    # Extract text content from payload for context assembly
    content = message.payload.get("text", json.dumps(message.payload))
    is_owner_command = message.intent == "owner_command"
    mentions = message.payload.get("mentions", [])

    # 4. Assemble context and run orchestrator
    assembler = ContextAssembler(db)
    context = await assembler.assemble(
        user_id, message.thread_id,
        {"role": "user", "content": content},
        owner_mode=is_owner_command,
        mentions=mentions
    )

    raw_keys = {}
    for provider, enc in (user.llm_api_keys or {}).items():
        try:
            raw_keys[provider] = decrypt_credentials(enc).get("api_key", "")
        except Exception:
            pass

    orchestrator = LLMOrchestrator(db)
    result = await orchestrator.run(
        user_id, message.thread_id, context,
        preferred_llm=user.preferred_llm,
        owner_mode=is_owner_command,
        llm_api_keys=raw_keys,
    )

    responder = AlterResponder()

    async def safe_send(recipient, text):
        try:
            await responder.send_reply(user_id, recipient, text)
        except Exception as e:
            logger.error("Failed to send reply", user_id=user_id, recipient=recipient, error=str(e))

    if result["action"] == "reply":
        await safe_send(message.from_, result["text"])

    elif result["action"] == "send_to_contact":
        await safe_send(result["recipient_phone"], result["text"])
        await safe_send(message.from_, result["confirmation"])

    elif result["action"] == "pending_approval":
        app_mgr = ApprovalManager(db)
        await app_mgr.create_pending_approval(
            user_id=user_id,
            action_desc=result["tool"],
            payload=result["args"]
        )
        await safe_send(message.from_, result["text"])

    elif result["action"] == "tool_executed":
        await safe_send(message.from_, "Action executed successfully.")

    return {"status": "processed"}
