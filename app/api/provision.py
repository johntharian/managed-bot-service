import uuid
import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.models.user import User
from app.schemas.provision import ProvisionRequest, ProvisionResponse

router = APIRouter()

@router.post("/", response_model=ProvisionResponse)
async def provision_bot(req: ProvisionRequest, db: AsyncSession = Depends(get_db)):
    """
    Called internally by BotsApp main server when a user signs up.
    Creates a new user, generates a random secret key for HMAC webhooks, 
    and returns the configuration.
    """
    # Check if user already exists
    stmt = select(User).where(User.phone_number == req.phone_number)
    existing = await db.execute(stmt)
    user = existing.scalar_one_or_none()
    
    if user:
        return ProvisionResponse(
            bot_url=user.bot_url,
            secret_key=user.secret_key
        )
    
    # Generate secrets
    secret_key = secrets.token_hex(32)
    bot_url = f"https://managed-bots.botsapp.internal/bot/{req.user_id}"
    
    new_user = User(
        user_id=req.user_id,
        phone_number=req.phone_number,
        bot_url=bot_url,
        secret_key=secret_key
    )
    db.add(new_user)
    await db.commit()
    
    return ProvisionResponse(
        bot_url=bot_url,
        secret_key=secret_key
    )
