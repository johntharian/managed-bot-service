from pydantic import BaseModel

class ProvisionRequest(BaseModel):
    user_id: str
    phone_number: str

class ProvisionResponse(BaseModel):
    bot_url: str
    secret_key: str
