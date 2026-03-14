from pydantic import BaseModel
from typing import Optional, List

class ConnectIntegrationRequest(BaseModel):
    encrypted_creds: str # E2E encrypted JSON blob passed from frontend/BotsApp
    scopes: List[str]

class IntegrationResponse(BaseModel):
    id: str
    service: str
    connected_at: str

class PermissionUpdateRequest(BaseModel):
    integration_id: str
    action: str
    level: str # read_only, ask_first, full_auto

class InstructionUpdate(BaseModel):
    instruction_text: str

class ApprovalAction(BaseModel):
    status: str # approved, rejected

class MemoryResponse(BaseModel):
    key: str
    value: str
    updated_at: str

class UserPreferenceUpdate(BaseModel):
    preferred_llm: str
