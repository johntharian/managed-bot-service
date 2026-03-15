from pydantic import BaseModel
from typing import Any


class IncomingMessage(BaseModel):
    sender_id: str
    recipient_id: str
    content: str
    thread_id: str


class MessageEnvelope(BaseModel):
    from_: str
    to: str
    intent: str
    thread_id: int
    message_id: int
    timestamp: str
    payload: dict[str, Any]

    class Config:
        populate_by_name = True
        alias_generator = lambda string: "from" if string == "from_" else string
