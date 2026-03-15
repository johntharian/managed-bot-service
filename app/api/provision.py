import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.core.settings import settings
from app.models.user import User
from app.schemas.provision import ProvisionRequest, ProvisionResponse

router = APIRouter()

@router.post("/", response_model=ProvisionResponse)
async def provision_bot(req: ProvisionRequest, db: AsyncSession = Depends(get_db)):
    """
    Called by the BotsApp Go server when a user enables their managed bot.
    Creates a new user profile, generates an HMAC secret and bot webhook URL.
    """
    # Check if user already exists
    stmt = select(User).where(User.user_id == req.user_id)
    existing = await db.execute(stmt)
    user = existing.scalar_one_or_none()

    if user:
        return ProvisionResponse(bot_url=user.bot_url, secret_key=user.secret_key)

    # Generate a cryptographically secure secret (32 random bytes, hex-encoded)
    secret_key = secrets.token_hex(32)
    bot_url = f"{settings.BASE_URL}/bot/{req.user_id}"

    new_user = User(
        user_id=req.user_id,
        phone_number=req.phone_number,
        bot_url=bot_url,
        secret_key=secret_key,
    )
    db.add(new_user)
    await db.commit()

    return ProvisionResponse(bot_url=bot_url, secret_key=secret_key)
