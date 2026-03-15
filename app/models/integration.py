import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, func, ARRAY
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.models import Base

class Integration(Base):
    __tablename__ = "integrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, ForeignKey("managed_bot_users.user_id"), nullable=False)
    service = Column(String, nullable=False) # e.g., 'gmail', 'gcal'
    encrypted_creds = Column(String, nullable=False) # AES-256 encrypted JSON
    scopes = Column(ARRAY(String))
    connected_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="integrations")
    permissions = relationship("BotPermission", back_populates="integration", cascade="all, delete-orphan")
