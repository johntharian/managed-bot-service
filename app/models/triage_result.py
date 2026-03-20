# app/models/triage_result.py
from app.models import Base
from sqlalchemy import Column, BigInteger, String, Float, Text, DateTime
from sqlalchemy.sql import func


class MessageTriageResult(Base):
    __tablename__ = "message_triage_results"

    message_id = Column(BigInteger, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    outcome = Column(String, nullable=False)   # 'skipped_rules' | 'skipped_classifier' | 'passed'
    confidence = Column(Float, nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
