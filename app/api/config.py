import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.models.integration import Integration
from app.models.bot_permission import BotPermission
from app.models.bot_instruction import BotInstruction
from app.models.pending_approval import PendingApproval
from app.models.user_memory import UserMemory
from app.models.user import User
from app.core.security import encrypt_credentials, decrypt_credentials

from app.schemas.config import (
    ConnectIntegrationRequest, IntegrationResponse,
    PermissionUpdateRequest, InstructionUpdate,
    ApprovalAction, MemoryResponse, UserPreferenceUpdate, LLMApiKeyUpdate
)

router = APIRouter()

# --- Integrations ---
@router.post("/{user_id}/integrations/{service}/connect", response_model=IntegrationResponse)
async def connect_integration(user_id: str, service: str, req: ConnectIntegrationRequest, db: AsyncSession = Depends(get_db)):
    integ = Integration(
        user_id=user_id,
        service=service,
        encrypted_creds=encrypt_credentials({"raw": req.encrypted_creds}),
        scopes=req.scopes
    )
    db.add(integ)
    await db.commit()
    await db.refresh(integ)
    return IntegrationResponse(id=str(integ.id), service=integ.service, connected_at=integ.connected_at.isoformat())


@router.get("/{user_id}/integrations")
async def list_integrations(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Integration).where(Integration.user_id == user_id, Integration.active == True)
    )
    integrations = result.scalars().all()
    return [
        {"service": i.service, "connected_at": i.connected_at.isoformat()}
        for i in integrations
    ]


# --- Instructions ---
@router.get("/{user_id}/instructions")
async def get_instructions(user_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(BotInstruction).where(BotInstruction.user_id == user_id)
    result = await db.execute(stmt)
    items = result.scalars().all()
    return [{"id": str(i.id), "instruction_text": i.instruction_text} for i in items]

@router.put("/{user_id}/instructions")
async def update_instruction(user_id: str, req: InstructionUpdate, db: AsyncSession = Depends(get_db)):
    inst = BotInstruction(user_id=user_id, instruction_text=req.instruction_text)
    db.add(inst)
    await db.commit()
    return {"status": "success"}

@router.delete("/{user_id}/instructions/{instruction_id}")
async def delete_instruction(user_id: str, instruction_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(BotInstruction).where(
        BotInstruction.id == uuid.UUID(instruction_id),
        BotInstruction.user_id == user_id,
    )
    inst = (await db.execute(stmt)).scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=404, detail="Instruction not found")
    await db.delete(inst)
    await db.commit()
    return {"status": "deleted"}


# --- Approvals ---
@router.get("/{user_id}/approvals")
async def get_approvals(user_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(PendingApproval).where(PendingApproval.user_id == user_id, PendingApproval.status == "pending")
    result = await db.execute(stmt)
    return result.scalars().all()

@router.post("/{user_id}/approvals/{approval_id}/approve")
async def approve_action(user_id: str, approval_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(PendingApproval).where(PendingApproval.id == uuid.UUID(approval_id), PendingApproval.user_id == user_id)
    approval = (await db.execute(stmt)).scalar_one_or_none()
    if not approval: raise HTTPException(404, "Not found")
    
    approval.status = "approved"
    await db.commit()
    # Resume celery task here 
    return {"status": "approved"}


# --- Long Term Memory ---
@router.get("/{user_id}/memory", response_model=List[MemoryResponse])
async def get_memory(user_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(UserMemory).where(UserMemory.user_id == user_id)
    memories = (await db.execute(stmt)).scalars().all()
    return [MemoryResponse(key=m.key, value=m.value, updated_at=m.updated_at.isoformat()) for m in memories]

# --- Preferences ---
@router.get("/{user_id}/preferences/llm")
async def get_preferred_llm(user_id: str, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    keys = user.llm_api_keys or {}
    return {
        "preferred_llm": user.preferred_llm,
        "api_keys_set": {provider: bool(key) for provider, key in keys.items()},
    }

@router.put("/{user_id}/preferences/llm")
async def update_preferred_llm(user_id: str, pref: UserPreferenceUpdate, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # Allow any string for provider extensibility per user request
    # Later we can validate against installed adapter plugins
    if not pref.preferred_llm.strip():
        raise HTTPException(status_code=400, detail="Invalid LLM provider. Cannot be empty.")
        
    user.preferred_llm = pref.preferred_llm
    await db.commit()
    return {"status": "success", "preferred_llm": user.preferred_llm}

@router.put("/{user_id}/preferences/llm/key")
async def set_llm_api_key(user_id: str, req: LLMApiKeyUpdate, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    keys = dict(user.llm_api_keys or {})
    keys[req.provider] = encrypt_credentials({"api_key": req.api_key})
    user.llm_api_keys = keys
    await db.commit()
    return {"status": "success"}
