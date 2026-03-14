from pydantic import BaseModel
import uuid

class ProvisionRequest(BaseModel):
    user_id: uuid.UUID
    phone_number: str

class ProvisionResponse(BaseModel):
    bot_url: str
    secret_key: str
