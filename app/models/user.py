from sqlalchemy import Column, String, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.models import Base

class User(Base):
    __tablename__ = "managed_bot_users"

    user_id = Column(String, primary_key=True)
    phone_number = Column(String, unique=True, nullable=False)
    bot_url = Column(String, nullable=False)
    secret_key = Column(String, nullable=False)
    preferred_llm = Column(String, server_default="gemini", nullable=False)
    llm_api_keys = Column(JSONB, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    integrations = relationship("Integration", back_populates="user", cascade="all, delete-orphan")
    permissions = relationship("BotPermission", back_populates="user", cascade="all, delete-orphan")
    instructions = relationship("BotInstruction", back_populates="user", cascade="all, delete-orphan")
    approvals = relationship("PendingApproval", back_populates="user", cascade="all, delete-orphan")
    memories = relationship("UserMemory", back_populates="user", cascade="all, delete-orphan")
