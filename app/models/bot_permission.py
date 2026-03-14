import uuid
from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.models import Base

class BotPermission(Base):
    __tablename__ = "bot_permissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("managed_bot_users.user_id"), nullable=False)
    integration_id = Column(UUID(as_uuid=True), ForeignKey("integrations.id"), nullable=False)
    action = Column(String, nullable=False) # e.g., 'read', 'send', 'create_event'
    level = Column(String, nullable=False) # 'read_only', 'ask_first', 'full_auto'

    user = relationship("User", back_populates="permissions")
    integration = relationship("Integration", back_populates="permissions")
