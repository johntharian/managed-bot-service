# app/models/style_profile.py
from sqlalchemy import Column, String, Integer, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.models import Base


class StyleProfile(Base):
    __tablename__ = "style_profiles"

    user_id = Column(String, primary_key=True)
    profile = Column(JSONB, nullable=False, default=dict)
    version = Column(Integer, nullable=False, default=0)
    message_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
