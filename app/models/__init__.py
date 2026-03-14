from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

# Import all models here so Alembic can find them
from app.models.user import User
from app.models.integration import Integration
from app.models.bot_permission import BotPermission
from app.models.bot_instruction import BotInstruction
from app.models.pending_approval import PendingApproval
from app.models.user_memory import UserMemory
