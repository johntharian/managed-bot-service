import json
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import uuid

from app.core.database import get_db
from app.core.security import verify_hmac_signature
from app.models.user import User
from app.schemas.bot import MessageEnvelope
from app.context.assembler import ContextAssembler
from app.bot.orchestrator import LLMOrchestrator
from app.bot.responder import BotsAppResponder
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
    Main webhook entrypoint for BotsApp.
    Validates HMAC signature and hands off to the Context/Orchestrator.
    """
    # 1. Fetch user to get their secret key
    stmt = select(User).where(User.user_id == uuid.UUID(user_id))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="Bot not found")

    # 2. Verify signature
    body = await request.body()
    if not verify_hmac_signature(body, x_hub_signature_256, user.secret_key):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    # 3. Parse envelope
    try:
        envelope_data = json.loads(body.decode("utf-8"))
        envelope = MessageEnvelope(**envelope_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    # Phase 4/5: Context generation and execution
    assembler = ContextAssembler(db)
    context = await assembler.assemble(user_id, envelope.thread_id, envelope_data)
    
    orchestrator = LLMOrchestrator(db)
    result = await orchestrator.run(user_id, envelope.thread_id, context, preferred_llm=user.preferred_llm)
    
    responder = BotsAppResponder()
    
    if result["action"] == "reply":
        # Bot generated a text response, send it back
        await responder.send_reply(user_id, envelope.from_, envelope.thread_id, result["text"])
        
    elif result["action"] == "pending_approval":
        # Action requires human-in-the-loop, ask for permission
        app_mgr = ApprovalManager(db)
        await app_mgr.create_pending_approval(
            user_id=user_id,
            action_desc=result["tool"],
            payload=result["args"]
        )
        await responder.send_reply(user_id, envelope.from_, envelope.thread_id, result["text"])
        
    elif result["action"] == "tool_executed":
        # Action was executed on full_auto
        # In a real setup, we might ask Claude to generate a follow up message, but for MVP:
        await responder.send_reply(user_id, envelope.from_, envelope.thread_id, "Action executed successfully.")
        
    return {"status": "processed", "message_id": envelope.message_id}
